"""Dữ liệu mẫu cho 4 route lõi của Contract Drop, để frontend dựng giao diện trước khi có route thật.

Luật mẫu dựng từ output LLM THẬT đã lưu (fallback_tactics.json) qua validator + assembler, không viết tay.
Sẽ bị thay bằng cài đặt thật (gateway/fraudops/incidents) — đừng dựa vào giá trị cụ thể.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

from app import config
from app.ai.interfaces import assemble_rule, validate_llm_output
from app.ai.rule_ai import cached_compile_output
from app.schemas.gateway import (
    BaselineView,
    ChallengeOptionOut,
    ChallengeOut,
    EvaluateResponse,
    SubmitChallengeResponse,
)
from app.schemas.incident import ActionCard, AnalyzeResponse, IncidentAnalysis, ProtectiveHold
from app.schemas.rule import RelayRule, RuleView


@lru_cache
def sample_rule() -> RelayRule:
    v = validate_llm_output(cached_compile_output("FAKE_HKD_TAX_VERIFICATION"))
    assert v.ok and v.sanitized_draft is not None, v.errors
    return assemble_rule(v.sanitized_draft, rule_id="RL-STUB-0001", version=1,
                         source_incident_id="INC-STUB-0001", ttl_hours=config.DEFAULT_RULE_TTL_HOURS)


def analyze_response() -> AnalyzeResponse:
    analysis = IncidentAnalysis(
        tactic_family="FAKE_HKD_TAX_VERIFICATION",
        tactic_summary_vi="Người tự xưng cán bộ thuế yêu cầu đóng phí xác minh tài khoản hộ kinh doanh.",
        money_lost_vnd=None, money_requested_vnd=1_800_000,
        otp_or_password_disclosed="UNKNOWN", remote_app_installed="NO",
        facts=[{"text": "Được yêu cầu chuyển 1,8 triệu phí xác minh", "provenance": "OBSERVED_IN_EVIDENCE"}],
        manipulation_cues=["giả danh cơ quan nhà nước", "hối thúc"],
    )
    return AnalyzeResponse(
        incident_id="INC-STUB-0001", mode="MANIPULATION",
        actions=[
            ActionCard(id="STOP_TRANSFER", title_vi="Không chuyển thêm tiền theo yêu cầu"),
            ActionCard(id="CALL_WALLET_HOTLINE_LOCK", title_vi="Gọi tổng đài ví để tạm khóa tài khoản"),
            ActionCard(id="VERIFY_TAX_OFFICIAL", title_vi="Kiểm tra lại với cơ quan thuế qua kênh chính thức"),
        ],
        analysis=analysis,
        policy_summary_vi="Đã tạm giữ các khoản chuyển rủi ro; hóa đơn quen thuộc vẫn đi qua.",
        protective_hold=ProtectiveHold(wallet_id="W-LAN", wallet_label="Ví cô Lan", mode="MANIPULATION"),
        consent_handoff=True, degraded=False,
    )


def rule_view() -> RuleView:
    r = sample_rule()
    now = datetime.now(timezone.utc)
    return RuleView(
        rule_id=r.rule_id, version=r.version, stage=r.lifecycle.stage, source_incident_id=r.source_incident_id,
        tactic_family=r.tactic_family, rule=r, draft=None, validation=None, regression=None,
        source="CACHED_FALLBACK", degraded=True, edited_by_human=False, corroboration_count=1,
        ttl_hours=r.lifecycle.ttl_hours, expires_at=r.lifecycle.expires_at, activated_at=None,
        compile_requested_at=now, ai_seconds=3.1,
    )


def evaluate_response() -> EvaluateResponse:
    q = sample_rule().jit_purpose_question
    return EvaluateResponse(
        tx_id="TX-STUB-0001", status="CHALLENGE_JIT", decision=None,
        challenge=ChallengeOut(
            challenge_id="CH-STUB-0001", question_vi=q.question_vi,
            options=[ChallengeOptionOut(id=o.id, label_vi=o.label_vi) for o in q.options],
            anti_coaching_notice_vi=q.anti_coaching_notice_vi,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=config.CHALLENGE_TTL_MINUTES),
        ),
        baseline=BaselineView(decision="ALLOW", risk_score=30, as_final="ALLOW"),
        reason_codes=["PARTNER_ALLOW", "RULE_MATCH"], matched_rule_id="RL-STUB-0001", receipt_id=None,
        message_vi=None, official_channels=[], retry_after=None, rule_active_for_seconds=120,
    )


def submit_response() -> SubmitChallengeResponse:
    return SubmitChallengeResponse(
        tx_id="TX-STUB-0001", decision="STOP_AND_EXPLAIN", reason_codes=["PARTNER_ALLOW", "ANSWER_TACTIC_MATCH"],
        receipt_id="RC-STUB-0001", tactic_alert_vi=sample_rule().jit_purpose_question.tactic_alert_vi,
        message_vi="Giao dịch đã dừng, 0đ rời ví. Bạn có thể tạo lại sau 30 phút.",
        official_channels=[], retry_after=datetime.now(timezone.utc) + timedelta(minutes=config.STOP_COOLDOWN_MINUTES),
    )
