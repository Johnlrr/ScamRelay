"""Bảng DB (SPEC §5.1). Mọi bảng có `workspace_id` (D8) và `created_at`.

Thời gian lưu dạng UTC; `UTCDateTime` trả về datetime có tzinfo=UTC kể cả trên SQLite.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, DateTime, LargeBinary, TypeDecorator
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _dt(nullable: bool = True, index: bool = False) -> Any:
    return Field(default=None, sa_column=Column(UTCDateTime(), nullable=nullable, index=index))


def _created() -> Any:
    return Field(default_factory=utcnow, sa_column=Column(UTCDateTime(), nullable=False))


def _json(default: Any = None) -> Any:
    factory = (lambda: []) if default == [] else (lambda: {}) if default == {} else (lambda: None)
    return Field(default_factory=factory, sa_column=Column(JSON, nullable=default is None))


class Workspace(SQLModel, table=True):
    id: str = Field(primary_key=True)
    owner: str = Field(index=True, unique=True)   # judge_01…, bench_runner, smoke, public:<cookie>
    seeded_at: datetime | None = _dt()
    created_at: datetime = _created()


class Wallet(SQLModel, table=True):
    workspace_id: str = Field(primary_key=True)
    id: str = Field(primary_key=True)
    label: str
    owner_name: str
    balance_vnd: int
    compromise_locked: bool = False
    known_contacts: list[str] = _json([])
    created_at: datetime = _created()


class Account(SQLModel, table=True):
    workspace_id: str = Field(primary_key=True)
    id: str = Field(primary_key=True)
    display_name: str
    age_days: int
    is_verified_biller: bool = False
    created_at: datetime = _created()


class Transaction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    wallet_id: str = Field(index=True)
    to_account_id: str
    amount_vnd: int
    transfer_note: str = ""
    status: str                                 # COMMITTED/HELD/STOPPED/BLOCKED/PENDING_CHALLENGE/EXPIRED
    decision: str | None = None
    reason_codes: list[str] = _json([])
    partner_decision: str | None = None
    partner_risk_score: int | None = None
    matched_rule_id: str | None = None
    matched_rule_version: int | None = None
    receipt_id: str | None = None
    release_at: datetime | None = _dt()
    retry_after: datetime | None = _dt()
    created_at: datetime = _created()


class Incident(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    submitted_at: datetime = _created()
    is_proxy: bool = False
    protected_wallet_id: str | None = None
    reporter_key: str                           # để tính corroboration: ví được bảo vệ hoặc phiên
    analysis_json: dict = _json({})             # IncidentAnalysis đã che PII
    tactic_family: str                          # = tactic_slug nếu OTHER_NEW
    mode: str                                   # MANIPULATION/COMPROMISE/UNCLEAR
    degraded: bool = False
    consent_handoff: bool = False
    created_at: datetime = _created()


class ContainmentPolicy(SQLModel, table=True):
    __tablename__ = "containment_policy"
    id: int | None = Field(default=None, primary_key=True)
    workspace_id: str = Field(index=True)
    incident_id: str
    wallet_id: str
    mode: str                                   # MANIPULATION / COMPROMISE (chỉ nâng)
    active: bool = True
    version: int = 1
    requested_by_proxy: bool = False
    updated_at: datetime = _created()
    created_at: datetime = _created()


class ExternalAction(SQLModel, table=True):
    __tablename__ = "external_action"
    id: int | None = Field(default=None, primary_key=True)
    workspace_id: str = Field(index=True)
    incident_id: str
    action_id: str
    status: str = "OPEN"                        # OPEN / USER_REPORTED_DONE / PENDING_EXTERNAL_CONFIRMATION
    created_at: datetime = _created()


class RelayRuleRow(SQLModel, table=True):
    __tablename__ = "relay_rule"
    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    source_incident_id: str
    tactic_family: str                          # họ thủ đoạn của sự cố nguồn (để tính corroboration)
    version: int = 1
    stage: str                                  # DRAFT_INVALID/SHADOW_LOG/ASK_ONLY/ENFORCE_HOLD/ROLLED_BACK/EXPIRED
    source: str | None = None                   # LLM / CACHED_FALLBACK
    degraded: bool = False
    draft_json: dict | None = _json()
    rule_json: dict | None = _json()
    validation_json: dict | None = _json()
    regression_json: dict | None = _json()
    regression_version: int | None = None
    edited_by_human: bool = False
    ttl_hours: int = 24
    expires_at: datetime | None = _dt()
    activated_at: datetime | None = _dt()
    corroboration_count: int = 1
    approvals: list[dict] = _json([])
    compile_requested_at: datetime | None = _dt()
    ai_seconds: float = 0.0
    created_at: datetime = _created()


class RuleEvent(SQLModel, table=True):
    __tablename__ = "rule_event"
    id: int | None = Field(default=None, primary_key=True)
    workspace_id: str = Field(index=True)
    rule_id: str = Field(index=True)
    version: int
    event: str                                  # COMPILED/VALIDATED/EDITED/TESTED/APPROVED/OVERRIDE/ROLLED_BACK/...
    actor: str
    payload: dict = _json({})
    created_at: datetime = _created()


class Challenge(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    tx_id: str = Field(index=True)
    rule_id: str
    rule_version: int
    options_json: list[dict] = _json([])        # có outcome — CHỈ server đọc (INV-12)
    floor_decision: str
    floor_reasons: list[str] = _json([])
    expires_at: datetime = Field(sa_column=Column(UTCDateTime(), nullable=False))
    used: bool = False
    answered_option_id: str | None = None
    answered_outcome: str | None = None
    created_at: datetime = _created()


class Receipt(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    tx_id: str = Field(index=True)
    decision: str
    reason_codes: list[str] = _json([])
    policy_refs: list[dict] = _json([])
    hash: str
    created_at: datetime = _created()


class EmbeddingCacheRow(SQLModel, table=True):
    __tablename__ = "embedding_cache"
    text_hash: str = Field(primary_key=True)    # sha256(model|dim|norm_match(text)), đã gồm model và dim
    model: str
    dim: int
    vector: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = _created()


WORKSPACE_TABLES = (Wallet, Account, Transaction, Incident, ContainmentPolicy, ExternalAction,
                    RelayRuleRow, RuleEvent, Challenge, Receipt)
