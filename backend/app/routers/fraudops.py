"""Luồng 2 — Tiếp sức, FraudOps Workspace (SPEC §7.2). Mọi route cần JWT giám khảo.

LLM chỉ đề xuất bản nháp; stage, threshold, điều kiện sàn, hành động đều do server gắn (D4).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app import config
from app.ai.interfaces import assemble_rule, compile_rule, run_regression, validate_llm_output
from app.core.assembler import AssembleError
from app.core.gateway import anchors_for, expire_rules_lazily, log_event, rule_of
from app.db import get_session
from app.models import Incident, RelayRuleRow, new_id, utcnow
from app.routers.deps import Principal, require_judge
from app.routers.errors import ApiError
from app.schemas.incident import IncidentAnalysis, IncidentDetail, IncidentSummary
from app.schemas.rule import (
    ActivationClock,
    ApproveRequest,
    ApproveResponse,
    CompileRequest,
    RegressionResult,
    RelayRule,
    RelayRuleDraft,
    RuleSummary,
    RuleView,
    ValidationResult,
)

router = APIRouter(prefix="/v1/fraudops", tags=["Tiếp sức"])

EDITABLE = ("DRAFT_INVALID", "SHADOW_LOG")
ROLLBACKABLE = ("DRAFT_INVALID", "SHADOW_LOG", "ASK_ONLY", "ENFORCE_HOLD")


# ---------------------------------------------------------------- helpers


def corroboration(s: Session, workspace_id: str, family: str) -> int:
    """Số sự cố đã đồng ý, cùng họ thủ đoạn, từ các ví/phiên khác nhau (SPEC §5.2)."""
    keys = s.exec(select(Incident.reporter_key).where(
        Incident.workspace_id == workspace_id, Incident.tactic_family == family,
        Incident.consent_handoff == True)).all()  # noqa: E712
    return max(1, len(set(keys)))


def _incident(s: Session, p: Principal, incident_id: str) -> Incident:
    inc = s.get(Incident, incident_id)
    if inc is None or inc.workspace_id != p.workspace_id:
        raise ApiError(404, "INCIDENT_NOT_FOUND", "Không tìm thấy sự cố.")
    return inc


def _row(s: Session, p: Principal, rule_id: str) -> RelayRuleRow:
    expire_rules_lazily(s, p.workspace_id)
    row = s.get(RelayRuleRow, rule_id)
    if row is None or row.workspace_id != p.workspace_id:
        raise ApiError(404, "RULE_NOT_FOUND", "Không tìm thấy luật.")
    return row


def _regression(row: RelayRuleRow) -> RegressionResult | None:
    if row.regression_json and row.regression_version == row.version:
        return RegressionResult.model_validate(row.regression_json)
    return None


def rule_view(row: RelayRuleRow) -> RuleView:
    return RuleView(
        rule_id=row.id, version=row.version, stage=row.stage, source_incident_id=row.source_incident_id,
        tactic_family=row.rule_json["tactic_family"] if row.rule_json else row.tactic_family,
        rule=RelayRule.model_validate(row.rule_json) if row.rule_json else None,
        draft=RelayRuleDraft.model_validate(row.draft_json) if row.draft_json else None,
        validation=ValidationResult.model_validate(row.validation_json) if row.validation_json else None,
        regression=_regression(row), source=row.source, degraded=row.degraded,
        edited_by_human=row.edited_by_human, corroboration_count=row.corroboration_count,
        ttl_hours=row.ttl_hours, expires_at=row.expires_at, activated_at=row.activated_at,
        compile_requested_at=row.compile_requested_at, ai_seconds=round(row.ai_seconds, 3),
    )


def _summary(inc: Incident, rule_id: str | None) -> IncidentSummary:
    a = IncidentAnalysis.model_validate(inc.analysis_json)
    return IncidentSummary(
        incident_id=inc.id, submitted_at=inc.submitted_at, is_proxy=inc.is_proxy, mode=inc.mode,
        tactic_family=inc.tactic_family, tactic_summary_vi=a.tactic_summary_vi, money_lost_vnd=a.money_lost_vnd,
        money_requested_vnd=a.money_requested_vnd, otp_or_password_disclosed=a.otp_or_password_disclosed,
        degraded=inc.degraded, rule_id=rule_id,
    )


def _try_draft(raw: dict) -> dict | None:
    """Bản nháp lỗi vẫn cố hiện cho chuyên viên sửa (nếu đúng hình dạng)."""
    try:
        clean = {k: v for k, v in raw.items() if k in RelayRuleDraft.model_fields}
        return RelayRuleDraft.model_validate(clean).model_dump(mode="json")
    except Exception:  # noqa: BLE001
        return None


async def _build(row: RelayRuleRow, draft: RelayRuleDraft, *, version: int, corroboration_count: int,
                 edited: bool) -> float:
    """Dựng luật bằng assembler, chuẩn bị anchor (embed theo lô). Trả số giây máy đã dùng."""
    from app.core.assembler import rule_to_draft

    rule = assemble_rule(draft, rule_id=row.id, version=version, source_incident_id=row.source_incident_id,
                         ttl_hours=row.ttl_hours, corroboration_count=corroboration_count, edited_by_human=edited)
    t0 = time.perf_counter()
    await anchors_for(rule)
    row.version, row.stage = version, "SHADOW_LOG"
    row.rule_json = rule.model_dump(mode="json")
    row.draft_json = rule_to_draft(rule).model_dump(mode="json")
    row.expires_at = rule.lifecycle.expires_at
    row.corroboration_count = corroboration_count
    row.edited_by_human = edited
    row.regression_json, row.regression_version = None, None
    return time.perf_counter() - t0


# ---------------------------------------------------------------- sự cố


@router.get("/incidents", response_model=list[IncidentSummary], summary="Hàng đợi sự cố đã đồng ý chia sẻ")
def list_incidents(p: Principal = Depends(require_judge), s: Session = Depends(get_session)) -> list[IncidentSummary]:
    incs = s.exec(select(Incident).where(Incident.workspace_id == p.workspace_id,
                                         Incident.consent_handoff == True)  # noqa: E712
                  .order_by(Incident.submitted_at.desc())).all()
    latest: dict[str, str] = {}
    for r in s.exec(select(RelayRuleRow).where(RelayRuleRow.workspace_id == p.workspace_id)
                    .order_by(RelayRuleRow.created_at)).all():
        latest[r.source_incident_id] = r.id
    return [_summary(i, latest.get(i.id)) for i in incs]


@router.get("/incidents/{incident_id}", response_model=IncidentDetail, summary="Chi tiết sự cố")
def get_incident(incident_id: str, p: Principal = Depends(require_judge),
                 s: Session = Depends(get_session)) -> IncidentDetail:
    inc = _incident(s, p, incident_id)
    if not inc.consent_handoff:
        raise ApiError(403, "CONSENT_REQUIRED", "Sự cố chưa được đồng ý chia sẻ sang FraudOps.")
    rid = s.exec(select(RelayRuleRow.id).where(RelayRuleRow.source_incident_id == inc.id)
                 .order_by(RelayRuleRow.created_at.desc())).first()
    return IncidentDetail(**_summary(inc, rid).model_dump(), analysis=IncidentAnalysis.model_validate(inc.analysis_json))


# ---------------------------------------------------------------- luật


@router.post("/rules/compile", response_model=RuleView, summary="AI biên dịch RelayRule từ sự cố đã đồng ý",
             description="LLM → validator → assembler. Đạt: luật version 1 ở `SHADOW_LOG`. Không đạt: `DRAFT_INVALID` "
                         "kèm lỗi. LLM lỗi/429: dùng output thật đã lưu (`CACHED_FALLBACK`, `degraded`).")
async def compile_rule_route(req: CompileRequest, p: Principal = Depends(require_judge),
                             s: Session = Depends(get_session)) -> RuleView:
    from app.ai.rule_ai import CompileUnavailable

    inc = _incident(s, p, req.incident_id)
    if not inc.consent_handoff:
        raise ApiError(403, "CONSENT_REQUIRED", "Sự cố chưa được đồng ý chia sẻ sang FraudOps.")
    requested_at = utcnow()
    try:
        cr = await compile_rule(IncidentAnalysis.model_validate(inc.analysis_json))
    except CompileUnavailable as e:
        raise ApiError(503, "COMPILE_UNAVAILABLE",
                       "AI đang quá tải và chưa có kết quả đã lưu cho thủ đoạn này. Hãy bấm \"Biên dịch lại\".") from e

    v = validate_llm_output(cr.raw)
    row = RelayRuleRow(
        id=new_id("RL"), workspace_id=p.workspace_id, source_incident_id=inc.id, tactic_family=inc.tactic_family,
        version=1, stage="DRAFT_INVALID", source=cr.source, degraded=cr.degraded,
        validation_json=v.model_dump(mode="json", exclude={"sanitized_draft"}),
        ttl_hours=config.DEFAULT_RULE_TTL_HOURS, compile_requested_at=requested_at,
        corroboration_count=corroboration(s, p.workspace_id, inc.tactic_family),
    )
    machine = cr.llm_seconds
    built = False
    if v.ok and v.sanitized_draft is not None:
        try:
            machine += await _build(row, v.sanitized_draft, version=1, corroboration_count=row.corroboration_count,
                                    edited=False)
            built = True
        except AssembleError as e:
            row.validation_json = {**row.validation_json, "ok": False, "errors": [str(e)]}
    if not built:
        row.stage, row.rule_json = "DRAFT_INVALID", None
        row.draft_json = _try_draft(cr.raw)
    row.ai_seconds = machine
    s.add(row)
    log_event(s, row, "COMPILED", p.username or "?", {"source": cr.source, "degraded": cr.degraded})
    log_event(s, row, "VALIDATED", "system", {"ok": v.ok, "errors": v.errors, "warnings": v.warnings})
    s.commit()
    return rule_view(row)


@router.get("/rules", response_model=list[RuleSummary], summary="Danh sách luật")
def list_rules(p: Principal = Depends(require_judge), s: Session = Depends(get_session)) -> list[RuleSummary]:
    expire_rules_lazily(s, p.workspace_id)
    s.commit()
    rows = s.exec(select(RelayRuleRow).where(RelayRuleRow.workspace_id == p.workspace_id)
                  .order_by(RelayRuleRow.created_at.desc())).all()
    out = []
    for r in rows:
        reg = _regression(r)
        out.append(RuleSummary(
            rule_id=r.id, version=r.version, stage=r.stage,
            tactic_family=r.rule_json["tactic_family"] if r.rule_json else r.tactic_family,
            source_incident_id=r.source_incident_id, edited_by_human=r.edited_by_human, expires_at=r.expires_at,
            activated_at=r.activated_at, benign_flagged=reg.benign_flagged if reg else None))
    return out


@router.get("/rules/{rule_id}", response_model=RuleView, summary="Chi tiết luật")
def get_rule(rule_id: str, p: Principal = Depends(require_judge), s: Session = Depends(get_session)) -> RuleView:
    row = _row(s, p, rule_id)
    s.commit()
    return rule_view(row)


@router.put("/rules/{rule_id}/draft", response_model=RuleView, summary="Chuyên viên sửa bản nháp",
            description="Chỉ khi stage là `DRAFT_INVALID`/`SHADOW_LOG`. Chạy lại validator, tăng version, "
                        "`edited_by_human = true`, hủy kết quả regression cũ.")
async def edit_draft(rule_id: str, draft: RelayRuleDraft, p: Principal = Depends(require_judge),
                     s: Session = Depends(get_session)) -> RuleView:
    row = _row(s, p, rule_id)
    if row.stage not in EDITABLE:
        raise ApiError(409, "RULE_NOT_EDITABLE", "Chỉ sửa được luật chưa duyệt (bản nháp hoặc chỉ ghi log).")
    v = validate_llm_output(draft.model_dump(mode="json"))
    if not v.ok or v.sanitized_draft is None:
        raise ApiError(422, "VALIDATION_FAILED", "Bản nháp chưa hợp lệ, luật chưa thay đổi.", v.errors)

    def anchors(d: dict | None) -> set[str]:
        return {a for c in (d or {}).get("conditions", []) for a in (c.get("anchor_phrases") or [])}

    before = anchors(row.draft_json)
    try:
        machine = await _build(row, v.sanitized_draft, version=row.version + 1,
                               corroboration_count=corroboration(s, p.workspace_id, row.tactic_family), edited=True)
    except AssembleError as e:
        s.rollback()
        raise ApiError(422, "VALIDATION_FAILED", "Bản nháp chưa hợp lệ, luật chưa thay đổi.", [str(e)]) from e
    row.ai_seconds += machine
    row.validation_json = v.model_dump(mode="json", exclude={"sanitized_draft"})
    after = anchors(row.draft_json)
    log_event(s, row, "EDITED", p.username or "?",
              {"anchors_added": sorted(after - before), "anchors_removed": sorted(before - after)})
    s.add(row)
    s.commit()
    return rule_view(row)


@router.post("/rules/{rule_id}/regression-test", response_model=RegressionResult,
             summary="Kiểm thử hồi quy trên tập sạch và biến thể",
             description="Chạy đúng hàm `layer1_match` của gateway trên ≥ 200 giao dịch sạch. "
                         "`flags_by_anchor` cho biết câu mẫu nào gây khớp nhầm.")
async def regression_test(rule_id: str, p: Principal = Depends(require_judge),
                          s: Session = Depends(get_session)) -> RegressionResult:
    row = _row(s, p, rule_id)
    if not row.rule_json:
        raise ApiError(409, "RULE_INVALID", "Bản nháp chưa qua validator; hãy sửa hoặc biên dịch lại trước.")
    rule = rule_of(row)
    s.commit()                                   # nhả khóa trước khi chờ embedding
    result = await run_regression(rule, await anchors_for(rule))
    row = s.get(RelayRuleRow, rule_id)
    if row.version != rule.version:
        raise ApiError(409, "RULE_CHANGED", "Luật vừa được sửa trong lúc kiểm thử; hãy chạy lại.")
    row.regression_json = result.model_dump(mode="json")
    row.regression_version = row.version
    row.ai_seconds += result.seconds
    lc = row.rule_json["lifecycle"]
    row.rule_json = {**row.rule_json, "lifecycle": {
        **lc, "benign_regression": {"checked": result.benign_checked, "flagged": result.benign_flagged},
        "variant_coverage": {"checked": result.variants_checked, "triggered": result.variants_triggered}}}
    log_event(s, row, "TESTED", p.username or "?",
              {"benign": f"{result.benign_flagged}/{result.benign_checked}",
               "variants": f"{result.variants_triggered}/{result.variants_checked}", "degraded": result.degraded})
    s.add(row)
    s.commit()
    return result


@router.post("/rules/{rule_id}/approve", response_model=ApproveResponse, summary="Duyệt luật vào gateway",
             responses={409: {"description": "REGRESSION_REQUIRED / APPROVE_LOCKED / CORROBORATION_REQUIRED / "
                                             "INVALID_STAGE_TRANSITION"}})
def approve(rule_id: str, req: ApproveRequest, p: Principal = Depends(require_judge),
            s: Session = Depends(get_session)) -> ApproveResponse:
    row = _row(s, p, rule_id)
    if req.stage == "ASK_ONLY" and row.stage != "SHADOW_LOG":
        raise ApiError(409, "INVALID_STAGE_TRANSITION", "Chỉ duyệt ASK_ONLY từ luật đang ở SHADOW_LOG.")
    if req.stage == "ENFORCE_HOLD":
        if row.stage != "ASK_ONLY":
            raise ApiError(409, "INVALID_STAGE_TRANSITION",
                           "ENFORCE_HOLD là lần duyệt thứ hai, chỉ duyệt được từ luật đang ở ASK_ONLY.")
        row.corroboration_count = corroboration(s, p.workspace_id, row.tactic_family)
        if row.corroboration_count < 2:
            raise ApiError(409, "CORROBORATION_REQUIRED",
                           "Cần ít nhất 2 báo cáo độc lập cùng thủ đoạn để nâng lên ENFORCE_HOLD.",
                           [{"corroboration_count": row.corroboration_count}])
    reg = _regression(row)
    if reg is None:
        raise ApiError(409, "REGRESSION_REQUIRED", "Cần chạy kiểm thử hồi quy cho đúng phiên bản hiện tại trước khi duyệt.")
    override = (req.override_reason or "").strip() or None
    if reg.benign_flagged > 0:
        if override is None or len(override) < config.OVERRIDE_REASON_MIN_LEN:
            raise ApiError(409, "APPROVE_LOCKED",
                           f"Có {reg.benign_flagged}/{reg.benign_checked} giao dịch sạch bị khớp nhầm. Hãy sửa câu mẫu "
                           f"hoặc nhập lý do ghi đè (≥ {config.OVERRIDE_REASON_MIN_LEN} ký tự).",
                           [{"benign_flagged": reg.benign_flagged, "flags_by_anchor": reg.flags_by_anchor}])
        log_event(s, row, "OVERRIDE", p.username or "?", {"reason": override, "benign_flagged": reg.benign_flagged})

    from datetime import timedelta

    now = utcnow()
    approval = {"by": p.username, "stage": req.stage, "at": now.isoformat(), "override_reason": override}
    row.approvals = [*row.approvals, approval]
    row.stage = req.stage
    row.ttl_hours = req.ttl_hours
    row.expires_at = now + timedelta(hours=req.ttl_hours)
    row.activated_at = row.activated_at or now
    lc = row.rule_json["lifecycle"]
    row.rule_json = {**row.rule_json, "lifecycle": {
        **lc, "stage": req.stage, "ttl_hours": req.ttl_hours, "expires_at": row.expires_at.isoformat(),
        "corroboration_count": row.corroboration_count, "approvals": row.approvals}}
    log_event(s, row, "APPROVED", p.username or "?", {"stage": req.stage, "ttl_hours": req.ttl_hours})
    s.add(row)

    inc = s.get(Incident, row.source_incident_id)
    elapsed = (now - row.compile_requested_at).total_seconds() if row.compile_requested_at else 0.0
    clock = ActivationClock(
        ai_seconds=round(row.ai_seconds, 2),
        human_seconds=round(max(0.0, elapsed - row.ai_seconds), 2),
        report_to_live_seconds=round((row.activated_at - inc.submitted_at).total_seconds(), 2) if inc else None,
    )
    s.commit()
    return ApproveResponse(rule=rule_view(row), clock=clock)


@router.post("/rules/{rule_id}/rollback", response_model=RuleView, summary="Thu hồi luật (1 chạm)")
def rollback(rule_id: str, p: Principal = Depends(require_judge), s: Session = Depends(get_session)) -> RuleView:
    row = _row(s, p, rule_id)
    if row.stage not in ROLLBACKABLE:
        raise ApiError(409, "RULE_INACTIVE", "Luật đã bị thu hồi hoặc đã hết hạn.")
    row.stage = "ROLLED_BACK"
    if row.rule_json:
        row.rule_json = {**row.rule_json, "lifecycle": {**row.rule_json["lifecycle"], "stage": "ROLLED_BACK"}}
    log_event(s, row, "ROLLED_BACK", p.username or "?")
    s.add(row)
    s.commit()
    return rule_view(row)
