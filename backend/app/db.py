"""Engine và session (SPEC §14.3). SQLite khi dev, Neon Postgres khi deploy — chỉ khác DATABASE_URL."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from app import config
from app import models  # noqa: F401  (đăng ký bảng)
from app.models import EmbeddingCacheRow

_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

        # SQLite không có SELECT … FOR UPDATE. Transaction thường: BEGIN (deferred).
        # Transaction cần khóa ghi từ đầu (submit-challenge): Session.connection(execution_options=IMMEDIATE).
        @event.listens_for(eng, "connect")
        def _no_autobegin(dbapi_conn, _rec):  # noqa: ANN001
            dbapi_conn.isolation_level = None

        @event.listens_for(eng, "begin")
        def _begin(conn):  # noqa: ANN001
            # COMMIT thất bại (database is locked) có thể trả kết nối về pool khi transaction còn dở;
            # dọn trước, không thì BEGIN lỗi "cannot start a transaction within a transaction" (PLAN H4).
            dbapi = conn.connection.dbapi_connection
            if dbapi is not None and dbapi.in_transaction:
                dbapi.execute("ROLLBACK")
            immediate = conn.get_execution_options().get("sqlite_immediate", False)
            conn.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

        return eng
    return create_engine(
        url,
        pool_pre_ping=True,          # Neon ngủ sau 5 phút sẽ cắt kết nối TCP cũ
        pool_recycle=240,
        pool_size=5, max_overflow=5,
        connect_args={"prepare_threshold": None},   # chạy an toàn qua PgBouncer (host -pooler)
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(config.DATABASE_URL)
    return _engine


def set_engine(engine: Engine) -> None:
    """Cho test: dùng engine riêng."""
    global _engine
    _engine = engine


IMMEDIATE = {"sqlite_immediate": True}   # bỏ qua trên Postgres (dùng SELECT … FOR UPDATE)


def init_db(engine: Engine | None = None) -> None:
    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as s:
        yield s


class DbEmbeddingCache:
    """`EmbeddingCache` (ai/interfaces.py) lưu trong bảng embedding_cache (vector float32)."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine or get_engine()

    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]:
        if not keys:
            return {}
        out: dict[str, np.ndarray] = {}
        with Session(self.engine) as s:
            for i in range(0, len(keys), 500):
                rows = s.exec(select(EmbeddingCacheRow).where(EmbeddingCacheRow.text_hash.in_(keys[i:i + 500])))
                for r in rows:
                    out[r.text_hash] = np.frombuffer(r.vector, dtype=np.float32).copy()
        return out

    def put_many(self, items: dict[str, np.ndarray]) -> None:
        if not items:
            return
        with Session(self.engine) as s:
            existing = set()
            keys = list(items)
            for i in range(0, len(keys), 500):
                existing |= set(s.exec(select(EmbeddingCacheRow.text_hash)
                                                   .where(EmbeddingCacheRow.text_hash.in_(keys[i:i + 500]))))
            for k, v in items.items():
                if k in existing:
                    continue
                vec = np.asarray(v, dtype=np.float32)
                s.add(EmbeddingCacheRow(text_hash=k, model=config.EMBED_MODEL, dim=int(vec.shape[-1]),
                                        vector=vec.tobytes()))
            try:
                s.commit()
            except Exception:
                s.rollback()   # cache chỉ là tối ưu; lần sau embed lại
                raise
