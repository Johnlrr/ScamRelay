import pytest

from app.core.preprocess import clean_input, mask_pii, norm, norm_light


# --- 3 ca bắt buộc trong SPEC §7.1
def test_money_after_chuyen_kept():
    assert mask_pii("chuyen 10000000 dong").text == "chuyen 10000000 dong"


def test_short_stk_after_keyword_masked():
    assert mask_pii("stk 12345678").text == "stk [STK]"


def test_spaced_phone_masked():
    assert mask_pii("goi 0912 345 678 nhe").text == "goi [SĐT] nhe"


# --- tiền
@pytest.mark.parametrize(
    "text",
    [
        "phí xác minh 1.800.000đ",
        "chuyển 1,8tr cho em",
        "nap 500k",
        "phi: 2500000",
        "dong 1200000 vnd",
        "chuyen 15000000 trieu",  # dãy 8 chữ số dính đơn vị: không bị che thành STK
        "mất 3 triệu",
    ],
)
def test_money_kept(text):
    assert mask_pii(text).text == text


def test_money_protected_from_otp_window():
    r = mask_pii("mã giảm giá 50000đ cho đơn hàng")
    assert r.text == "mã giảm giá 50000đ cho đơn hàng"
    assert r.counts["otp"] == 0


def test_phone_after_chuyen_is_not_money():
    assert mask_pii("chuyen 0912345678 ngay").text == "chuyen [SĐT] ngay"


# --- SĐT / CCCD
@pytest.mark.parametrize("phone", ["0912345678", "0912.345.678", "+84 912 345 678", "+84912345678"])
def test_phone_variants(phone):
    assert mask_pii(f"lh {phone}").text == f"lh [SĐT]"


def test_cccd():
    assert mask_pii("cccd 001203004567 cua toi").text == "cccd [CCCD] cua toi"


# --- OTP
def test_otp_near_keyword():
    r = mask_pii("Ma OTP cua ban la 482913, khong chia se")
    assert "482913" not in r.text and "[OTP]" in r.text
    assert r.otp_mentioned


def test_otp_accented_keyword():
    r = mask_pii("mã xác thực: 1234")
    assert r.text == "mã xác thực: [OTP]"


def test_digits_far_from_keyword_not_otp():
    r = mask_pii("phong 4821 " + "x" * 40 + " otp")
    assert "4821" in r.text


def test_otp_flag_without_digits():
    r = mask_pii("Mẹ lỡ đọc OTP cho nó rồi")
    assert r.otp_mentioned and r.counts["otp"] == 0


def test_no_otp_flag_on_plain_text():
    assert not mask_pii("mua hang online").otp_mentioned


# --- STK
def test_long_stk_masked():
    assert mask_pii("chuyen vao 1903456789012 nhe").text == "chuyen vao [STK] nhe"


def test_short_digits_without_keyword_kept():
    assert mask_pii("don hang 12345678").text == "don hang 12345678"


@pytest.mark.parametrize("text", ["số tài khoản: 7654321", "tk la 7654321", "STK 7654321"])
def test_short_stk_keyword_variants(text):
    assert mask_pii(text).text.endswith("[STK]")


def test_order_and_counts():
    r = mask_pii("chuyen 2000000d vao stk 0123456789012, goi 0987654321, otp 9999")
    assert r.text == "chuyen 2000000d vao stk [STK], goi [SĐT], otp [OTP]"
    assert r.counts == {"phone": 1, "cccd": 0, "otp": 1, "stk": 1}


def test_masking_is_idempotent():
    once = mask_pii("stk 12345678, sdt 0912345678").text
    assert mask_pii(once).text == once


# --- chuẩn hóa
def test_clean_input_strips_control_and_nfc():
    decomposed = "thué"  # "thué" dạng NFD
    assert clean_input("a​b\x07" + decomposed) == "ab" + "thué"


def test_norm_mode_a():
    assert norm("  Đóng PHÍ xác-minh, HKD 2026!! ") == "dong phi xac minh hkd 2026"


def test_norm_collides_thue_thue():
    assert norm("thuế") == norm("thuê") == "thue"


def test_norm_light_keeps_diacritics():
    assert norm_light("  Đóng   Phí ") == "đóng phí"
