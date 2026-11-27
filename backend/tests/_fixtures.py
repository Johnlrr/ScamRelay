"""Dữ liệu tổng hợp dùng chung cho test (không có PII thật)."""

import copy

from app.core._contract_draft import DerivedTx
from app.core.preprocess import norm_match

HKD_ANCHORS = [
    "dong phi xac minh ho kinh doanh",
    "cap nhat thue ho kinh doanh 2026",
    "phi kich hoat ma so thue dien tu",
]

VALID_DRAFT = {
    "tactic_family": "FAKE_HKD_TAX_VERIFICATION",
    "match_mode": "ALL",
    "conditions": [
        {"field": "transfer_note", "op": "SEMANTIC_MATCH", "anchor_phrases": list(HKD_ANCHORS)},
        {"field": "transfer_note", "op": "NOT_CONTAINS_ANY", "value_str_list": ["thue nha", "thue mat bang"]},
    ],
    "purpose_question": {
        "question_vi": "Khoản chuyển này dùng để làm gì?",
        "options": [
            {"label_vi": "Mua hàng, trả tiền dịch vụ", "outcome": "BENIGN"},
            {"label_vi": "Trả tiền cho người thân, người quen", "outcome": "BENIGN"},
            {"label_vi": "Đóng phí để cơ quan hoặc tổ chức xử lý hồ sơ, tài khoản", "outcome": "TACTIC_MATCH"},
        ],
        "tactic_alert_vi": "Cơ quan thuế không yêu cầu chuyển phí vào tài khoản cá nhân để xác minh hộ kinh doanh.",
    },
    "variants": [
        {"transfer_note": f"xac thuc ho so thue HKD lan {i}", "amount_vnd": 1_000_000 + i * 100_000,
         "manipulation_intent": "giả danh cán bộ thuế, ép đóng phí"}
        for i in range(5)
    ],
}


def draft_dict(**patch):
    d = copy.deepcopy(VALID_DRAFT)
    d.update(patch)
    return d


def make_tx(note: str = "xac thuc ho so cap nhat thue HKD", amount: int = 1_200_000, **kw) -> DerivedTx:
    base = dict(
        wallet_id="W-HUNG", to_account_id="ACC-OLD-7731", amount_vnd=amount, transfer_note=note,
        note_norm=norm_match(note), recipient_is_new=True, recipient_account_age_days=420,
        tx_count_10m=0, is_verified_biller=False, is_known_contact=False, account_compromise_flag=False,
    )
    base.update(kw)
    return DerivedTx(**base)


class FakeEmbedder:
    """Embedder giả, tất định: vector = trigram băm vào 64 chiều (đã L2). Đếm số lần gọi."""

    dim = 64

    def __init__(self, fail: bool = False):
        self.calls: list[list[str]] = []
        self.fail = fail

    async def embed_batch(self, texts):
        import numpy as np

        from app.core.semantic import EmbeddingError, l2_normalize, trigrams

        self.calls.append(list(texts))
        if self.fail:
            raise EmbeddingError("429 giả lập")
        m = np.zeros((len(texts), self.dim), np.float32)
        for i, t in enumerate(texts):
            for g, n in trigrams(t).items():
                m[i, sum(map(ord, g)) * 2654435761 % self.dim] += n
        return l2_normalize(m)


class FakeLLM:
    """Thay LLMClient trong test: trả `responses` lần lượt; phần tử là Exception thì ném ra."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    async def generate_json(self, prompt, schema, **kw):
        from app.ai.llm_client import LLMResponse

        self.prompts.append(prompt)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(data=r, seconds=0.5, model="fake")


HKD_ANALYSIS = {
    "tactic_family": "FAKE_HKD_TAX_VERIFICATION",
    "tactic_slug": None,
    "tactic_summary_vi": "Giả danh cán bộ thuế, đòi phí xác minh hồ sơ hộ kinh doanh.",
    "money_lost_vnd": 1_500_000,
    "money_requested_vnd": None,
    "otp_or_password_disclosed": "NO",
    "remote_app_installed": "UNKNOWN",
    "facts": [{"text": "Người gọi xưng là cán bộ chi cục thuế.", "provenance": "OBSERVED_IN_EVIDENCE"}],
    "manipulation_cues": ["đe dọa khóa mã số thuế"],
}
