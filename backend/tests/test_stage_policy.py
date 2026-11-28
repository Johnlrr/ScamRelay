import json
from pathlib import Path

import pytest

from app.core.stage_policy import (
    PARTNER_MAP,
    SEVERITY,
    STAGE_POLICY,
    Floor,
    max_severity,
    stage_action,
)
from app.schemas.gateway import ChallengeOut


def test_stage_policy_table_matches_spec():
    assert STAGE_POLICY["ASK_ONLY"] == {
        "TACTIC_MATCH": "STOP_AND_EXPLAIN", "BENIGN": "ALLOW_WITH_WARNING", "UNCLEAR": "HOLD_15M"}
    assert STAGE_POLICY["ENFORCE_HOLD"] == {
        "TACTIC_MATCH": "HOLD_UNTIL_VERIFIED", "BENIGN": "ALLOW_WITH_WARNING", "UNCLEAR": "HOLD_15M"}


@pytest.mark.parametrize("stage", ["SHADOW_LOG", "DRAFT_INVALID", "ROLLED_BACK", "EXPIRED"])
def test_inactive_stage_has_no_action(stage):
    assert stage_action(stage, "TACTIC_MATCH") is None


def test_severity_order():
    order = ["ALLOW", "ALLOW_WITH_WARNING", "HOLD_15M", "STOP_AND_EXPLAIN", "HOLD_UNTIL_VERIFIED", "BLOCK"]
    assert sorted(SEVERITY, key=SEVERITY.get) == order
    assert max_severity() == "ALLOW"
    assert max_severity("HOLD_15M", "ALLOW_WITH_WARNING") == "HOLD_15M"


def test_partner_map():
    assert PARTNER_MAP == {"ALLOW": "ALLOW", "WARN": "HOLD_15M", "BLOCK": "BLOCK"}


def test_floor_only_raises():
    f = Floor("HOLD_15M", ["PARTNER_WARN"])
    f.raise_to("ALLOW", "X")
    assert f.decision == "HOLD_15M"
    f.raise_to("HOLD_UNTIL_VERIFIED", "CONTAINMENT_MANIPULATION")
    assert f.decision == "HOLD_UNTIL_VERIFIED"
    assert Floor.from_dict(f.to_dict()) == f


def test_benign_with_partner_warn_is_hold():
    # SPEC §7.3: chọn BENIGN khi lớp đối tác WARN → HOLD_15M, không phải ALLOW_WITH_WARNING
    assert max_severity(PARTNER_MAP["WARN"], STAGE_POLICY["ASK_ONLY"]["BENIGN"]) == "HOLD_15M"


def test_challenge_out_hides_outcome_schema():
    assert "outcome" not in json.dumps(ChallengeOut.model_json_schema())


def test_seed_ids_match_spec():
    seed = json.loads((Path(__file__).resolve().parents[1] / "data" / "seed_workspace.json").read_text("utf-8"))
    assert {w["id"] for w in seed["wallets"]} == {"W-LAN", "W-HUNG"}
    assert {a["id"] for a in seed["accounts"]} == {
        "ACC-EVN", "ACC-WATER", "ACC-TAX-GOV", "ACC-TUAN", "ACC-LANDLORD", "ACC-SUPPLIER", "ACC-SHOP",
        "ACC-OLD-7731", "ACC-OLD-5520", "ACC-NEW-01", "ACC-NEW-02", "ACC-NEW-03"}
    billers = {a["id"] for a in seed["accounts"] if a["is_verified_biller"]}
    assert billers == {"ACC-EVN", "ACC-WATER", "ACC-TAX-GOV"}
