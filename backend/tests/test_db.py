"""db.py: engine SQLite tự dọn transaction dở trên kết nối lấy từ pool (PLAN H4)."""

from __future__ import annotations

from sqlmodel import Session, select

from app import db
from app.models import Workspace


def test_begin_recovers_from_dangling_transaction(tmp_path):
    eng = db.make_engine(f"sqlite:///{tmp_path / 'h4.db'}")
    db.init_db(eng)
    with eng.connect() as c:
        raw = c.connection.dbapi_connection
        raw.execute("BEGIN")            # giống COMMIT thất bại để lại transaction dở
        assert raw.in_transaction
        c.begin()                       # trước khi sửa: "cannot start a transaction within a transaction"
        c.rollback()

    with Session(eng) as s:             # kết nối dùng lại từ pool vẫn ghi được
        s.add(Workspace(id="WS-h4", owner="h4"))
        s.commit()
        assert s.exec(select(Workspace).where(Workspace.id == "WS-h4")).first() is not None


def test_immediate_still_works_after_recovery(tmp_path):
    eng = db.make_engine(f"sqlite:///{tmp_path / 'h4b.db'}")
    db.init_db(eng)
    with eng.connect() as c:
        c.connection.dbapi_connection.execute("BEGIN")
        c2 = c.execution_options(**db.IMMEDIATE)
        c2.begin()
        c2.rollback()
