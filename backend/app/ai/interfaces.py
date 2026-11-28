"""Hợp đồng giữa phần AI/luật (bao) và API/gateway (linh) — PLAN §4, SPEC §6.4.

Router và core của linh CHỈ gọi các hàm ở đây; phần cài đặt nằm trong module của bao.
Import bên trong thân hàm để tránh import vòng (module của bao import kiểu từ app.schemas).
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app.schemas.gateway import BaselineResult, DerivedTx
from app.schemas.incident import AnalyzeResult, IncidentAnalysis
from app.schemas.rule import (
    AnchorSet,
    CompileResult,
    RegressionResult,
    RelayRule,
    RelayRuleDraft,
    ValidationResult,
)

__all__ = [
    "AnalyzeResult", "AnchorSet", "BaselineResult", "CompileResult", "DerivedTx", "EmbeddingCache",
    "RegressionResult", "RelayRule", "RelayRuleDraft", "SemanticMatcher", "ValidationResult",
    "analyze_incident", "assemble_rule", "baseline_score", "compile_rule", "layer1_match",
    "run_regression", "validate_llm_output",
]


# ---------------------------------------------------------------- protocol


class SemanticMatcher(Protocol):
    async def prepare_anchors(self, anchors: list[str]) -> AnchorSet: ...
    async def score(self, note_norm: str, anchors: AnchorSet) -> float | None: ...


class EmbeddingCache(Protocol):                  # linh cài trên DB (core/... DbEmbeddingCache)
    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]: ...
    def put_many(self, items: dict[str, np.ndarray]) -> None: ...


# ---------------------------------------------------------------- AI (bao cài trong app/ai)


async def analyze_incident(masked_text: str, image_b64: str | None, otp_mentioned: bool,
                           history: list[IncidentAnalysis]) -> AnalyzeResult:
    from app.ai.incident_ai import analyze_incident as impl
    return await impl(masked_text, image_b64, otp_mentioned, history)


async def compile_rule(analysis: IncidentAnalysis) -> CompileResult:
    """Raw dict + source. Lỗi/429 → CACHED_FALLBACK; thủ đoạn không có trong file dự phòng → ném lỗi."""
    from app.ai.rule_ai import compile_rule as impl
    return await impl(analysis)


# ---------------------------------------------------------------- luật (bao cài trong app/core)


def validate_llm_output(raw: dict) -> ValidationResult:
    from app.core.validator import validate_llm_output as impl
    return impl(raw)


def assemble_rule(draft: RelayRuleDraft, *, rule_id: str, version: int, source_incident_id: str,
                  ttl_hours: int, **kw) -> RelayRule:
    from app.core.assembler import assemble_rule as impl
    return impl(draft, rule_id=rule_id, version=version, source_incident_id=source_incident_id,
                ttl_hours=ttl_hours, **kw)


def baseline_score(tx: DerivedTx) -> BaselineResult:
    from app.core.baseline import baseline_score as impl
    return impl(tx)


def layer1_match(rule: RelayRule, tx: DerivedTx, anchors: AnchorSet, *,
                 note_vec: np.ndarray | None = None) -> float | None:
    from app.core.layer1 import layer1_match as impl
    return impl(rule, tx, anchors, note_vec=note_vec)


async def run_regression(rule: RelayRule, anchors: AnchorSet) -> RegressionResult:
    from app.core.regression import run_regression as impl
    return await impl(rule, anchors)
