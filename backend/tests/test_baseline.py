import pytest

from app.core.baseline import baseline_score, load_keywords
from tests._fixtures import make_tx


def test_demo_hung_is_allowed_by_partner():
    # SPEC §9: 1,2tr tới ACC-OLD-7731 (420 ngày), người nhận mới, không có giao dịch khác → 30 → ALLOW
    r = baseline_score(make_tx())
    assert (r.decision, r.risk_score, r.reasons) == ("ALLOW", 30, ["RECIPIENT_NEW"])


def test_known_keyword_warns():
    r = baseline_score(make_tx("nap tien lam nhiem vu nhan thuong", recipient_is_new=False))
    assert r.decision == "WARN" and r.risk_score == 60 and "KNOWN_SCAM_KEYWORD" in r.reasons


def test_keyword_match_is_whole_phrase_after_normalization():
    assert "KNOWN_SCAM_KEYWORD" in baseline_score(make_tx("Nhận THƯỞNG tri ân")).reasons
    assert "KNOWN_SCAM_KEYWORD" not in baseline_score(make_tx("nhan thuongxuyen")).reasons


@pytest.mark.parametrize(
    "kw, score, decision",
    [
        (dict(recipient_is_new=True, recipient_account_age_days=5), 45, "ALLOW"),
        (dict(recipient_is_new=True, amount=5_000_000), 55, "WARN"),
        (dict(recipient_is_new=False, amount=5_000_000, recipient_account_age_days=2), 40, "ALLOW"),
        (dict(recipient_is_new=False, tx_count_10m=3), 50, "WARN"),
        (dict(recipient_is_new=False, tx_count_10m=2), 0, "ALLOW"),
    ],
)
def test_scores_and_threshold(kw, score, decision):
    amount = kw.pop("amount", 1_200_000)
    r = baseline_score(make_tx(amount=amount, **kw))
    assert (r.risk_score, r.decision) == (score, decision)


def test_score_clamped_to_100():
    r = baseline_score(make_tx("nhan thuong", amount=9_000_000, recipient_account_age_days=1, tx_count_10m=5))
    assert r.risk_score == 100 and r.decision == "WARN"


def test_compromise_locked_blocks_even_with_low_score():
    r = baseline_score(make_tx(recipient_is_new=False, account_compromise_flag=True))
    assert r.decision == "BLOCK" and r.risk_score == 0


def test_static_keywords_do_not_know_hkd_tactic():
    # Baseline đại diện hệ thống tốt nhưng CHƯA biết thủ đoạn HKD 2026 (SPEC §9)
    for k in load_keywords():
        assert "ho kinh doanh" not in k and "thue" not in k and "ma so" not in k, k
    assert baseline_score(make_tx("dong phi xac minh ho kinh doanh", recipient_is_new=False)).risk_score == 0
