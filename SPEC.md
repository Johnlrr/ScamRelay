# ScamRelay — Technical Specification (SPEC.md)

**Phiên bản:** 2.0 | **Ngày:** 27/11/2026, 22:30 | **Tài liệu gốc:** `SCAMRELAY_ABOUT.md` (gọi tắt **ABOUT**) | **Kế hoạch:** `PLAN.md` (v3)
**Nguyên tắc chung:** Làm kỹ những chỗ giám khảo sẽ vặn: an toàn, tính đúng của quyết định, đo lường. Làm nhanh mọi chỗ còn lại: hạ tầng, UI, xuất file.
**Khi các tài liệu lệch nhau:** chi tiết kỹ thuật theo SPEC; phạm vi và mức ưu tiên theo ABOUT §8.1; ai làm gì, khi nào theo PLAN. Ví dụ JSON ở ABOUT §5.1 là dạng trình bày cho slide; dạng chính xác của API nằm ở §6 dưới đây.

---

## Thay đổi so với SPEC v1

| # | Thay đổi | Mục |
|---|---|---|
| S1 | Phương án trả lời mang **nhãn ý nghĩa** `BENIGN` / `TACTIC_MATCH` / `UNCLEAR`, thay cho `role`. LLM viết 3 phương án (2 `BENIGN` + 1 `TACTIC_MATCH`); server tự thêm "Mục đích khác" (`UNCLEAR`). Client chỉ thấy `option_id` và nhãn chữ, **không thấy nhãn ý nghĩa** | §6.3, §7.3 |
| S2 | **StagePolicy** thay bảng ROLE×STAGE, với các hành động mới `ALLOW_WITH_WARNING`, `STOP_AND_EXPLAIN` (dừng mềm, được tạo lại sau 30 phút), `HOLD_UNTIL_VERIFIED`. `BLOCK` chỉ còn dùng cho khoanh vùng `COMPROMISE` | §7.3 |
| S3 | **Lớp đối tác:** quyết định cuối là mức nghiêm nhất trong ba lớp: lớp đối tác, khoanh vùng, luật tiếp sức. Trong sandbox, lớp đối tác chính là baseline, và `partner_risk_score` là điểm của baseline. Nhờ vậy ScamRelay không bao giờ lỏng hơn baseline | §7.3, §9 |
| S4 | **Điều kiện sàn do server gắn** vào mọi luật: `amount_vnd ≥ 200.000` và `is_verified_biller = false`. Biller đã xác minh không bao giờ bị hỏi | §6.3, §7.3 |
| S5 | Chuẩn hóa cố định: bỏ dấu và **mở rộng viết tắt** (HKD, MST…). Bỏ chế độ B; bước hiệu chỉnh chỉ còn quét ngưỡng | §8 |
| S6 | Luật qua validator thì tự vào `SHADOW_LOG`. **Chuyên viên sửa được bản nháp** (endpoint mới), sau đó validator và kiểm thử hồi quy chạy lại. Tập sạch **≥ 200 mẫu**. **Approve bị khóa khi `flagged > 0`**, trừ khi có lý do ghi đè | §7.2 |
| S7 | Đồng hồ kích hoạt ghi **2 mốc**: thời gian máy (biên dịch + kiểm thử) và thời gian con người | §7.2f |
| S8 | Bảng theo dõi luật, nút "Báo nhầm", chống dò đáp án (đều là "có thể có") | §7.2h, §7.3 |
| S9 | Kích hoạt hộ **chỉ làm tài khoản an toàn hơn**: thông báo cho chủ ví, người thân không thấy số dư. Khoanh vùng `MANIPULATION` dùng `HOLD_UNTIL_VERIFIED` | §7.1 |
| S10 | Đồng ý chia sẻ là cờ `consent_handoff` gửi kèm `analyze`, sau phần giải thích 3 điểm | §7.1c |
| S11 | Gói hồ sơ "Kể 1 lần" dựng **ở frontend** thành Markdown, tải bằng Blob; PDF do trình duyệt in (có thể có). Không có endpoint export-pack | §7.1b |
| S12 | Held-out **10–12 ca**, quynh viết tối 30/11 trên máy riêng, bao không xem. Câu trả lời của nạn nhân viết bằng lời tự do; **linh ánh xạ** sang phương án khi chạy. Chỉ chạy **1 lượt** sau freeze | §13 |
| S13 | `ENFORCE_HOLD` cần `corroboration_count ≥ 2` và một lần duyệt thứ hai | §7.2f |
| S14 | Đọc ảnh hạ xuống "có thể có" | §1 |
| S15 | Bỏ hẳn: `usage_counter` / `DAILY_*_CAP`, `REGISTRY_STRICT`, endpoint `unlock` và `merge-incident`, workflow deploy / WIF, Jinja2, `SEMANTIC_MODE` | — |
| S16 | **Cắt cho hackathon (27/11, 23:20):** bỏ mã hóa và hash held-out; bỏ bảng `notification`, endpoint `consent` và xóa theo TTL; bỏ endpoint export-pack; dự phòng biên dịch còn 2 tầng; dừng mềm 30 phút, bảng theo dõi luật, "Báo nhầm", chống dò đáp án và ablation chỉ làm nếu 30/11 còn dư giờ | — |

---

## 0. Quyết định kỹ thuật cốt lõi

| # | Quyết định | Lý do |
|---|---|---|
| D1 | **1 repo, 1 service, 1 Docker image.** FastAPI phục vụ cả API lẫn bản build tĩnh của frontend (`/` → SPA, `/v1/*` → API, `/docs` → Swagger) | Không CORS, một lần deploy, một URL cho giám khảo |
| D2 | **Postgres miễn phí trên Neon + SQLModel**; dev local dùng SQLite, chỉ đổi `DATABASE_URL` | Cloud Run không có ổ đĩa bền |
| D3 | **Gemini API cho cả LLM và embedding** (`gemini-embedding-001`), một API key | Không cần GPU, image nhỏ |
| D4 | **LLM chỉ sinh nội dung và nhãn ý nghĩa, không sinh quyền.** `threshold`, điều kiện sàn, hành động, `stage` và `option_id` đều do server gán | Separation of Authority thật sự |
| D5 | **Không có message queue hay worker nền.** Mọi request chạy đồng bộ, có timeout | Ít thành phần, ít điểm hỏng |
| D6 | **Không render PDF ở server.** Export-pack trả Markdown; PDF do trình duyệt in | Không cần thư viện hệ thống |
| D7 | **Hai tầng dự phòng khi biên dịch:** gọi LLM → nếu lỗi hoặc 429 thì đọc output LLM *thật* đã lưu sẵn cho 3 thủ đoạn mẫu (`fallback_tactics.json`), gắn `source="CACHED_FALLBACK"` và `degraded: true` | Demo không chết, và không giả làm output trực tiếp |
| D8 | **Cô lập theo workspace.** Mỗi tài khoản giám khảo có ví, luật, sự cố riêng, kèm nút Reset | Giám khảo X không ảnh hưởng giám khảo Y |
| D9 | **ScamRelay là lớp nằm trên hệ thống của ví.** Quyết định cuối = mức nghiêm nhất của (lớp đối tác, khoanh vùng, luật tiếp sức) | ScamRelay không bao giờ yếu hơn hệ thống sẵn có |
| D10 | **Gateway không gọi LLM.** Mỗi giao dịch chỉ tốn tối đa 1 lần embed, có cache | Latency và quota ổn định khi giám khảo dùng |

**Đã chốt (27/11):**
1. **LLM:** `gemini-3.5-flash-lite` (bao chốt 28/11: đêm 27/11 các bản Flash thường 503/timeout, `gemini-2.5-flash` không còn mở cho người dùng mới; flash-lite: compile P50 2,90 giây, analyze P50 1,32 giây trên 12 ca dev, `bench/results/latency_20261128T0044Z.md`). Bản ổn định, có structured output; không dùng bản preview hoặc experimental. Gọi qua lớp `LLMClient`; đổi model thì chạy lại `compile_dev` → `calibrate` → `save_fallback`.
2. **Embedding:** `gemini-embedding-001`, dùng chung API key.
3. **Hosting:** Cloud Run (`asia-southeast1`) + Neon Postgres (Singapore). CI chỉ chạy `pytest`; deploy tay bằng `scripts/deploy.sh`.

---

## 1. Phạm vi

| Mức (ABOUT §8.1) | Hạng mục kỹ thuật |
|---|---|
| **Bắt buộc có** | `analyze` (văn bản) + containment; `compile` + validator + assembler; kiểm thử hồi quy trên ≥ 200 ca sạch, có khóa Approve; sửa bản nháp; approve và rollback; gateway `evaluate` / `submit` theo StagePolicy và lớp đối tác; `/wallet` so sánh trước và sau; `/docs`; `run_bench.py`; deploy public cùng dự phòng (D7) |
| **Nên có** | Kích hoạt hộ đủ các giới hạn ở §7.1; nâng khóa khi lộ OTP; gói hồ sơ `.md` dựng ở frontend; `ALLOW_WITH_WARNING` (nếu cắt thì `BENIGN` → `ALLOW` và chỉ mất dòng cảnh báo trên màn kết quả) |
| **Có thể có** (chỉ làm nếu 30/11 còn dư giờ) | Dừng mềm 30 phút (`STOP_COOLDOWN`); bảng theo dõi luật và "Báo nhầm"; ablation từ khóa; chống dò đáp án; PDF; đọc ảnh chụp màn hình; biến thể do LLM sinh (nếu cắt, dùng 5 biến thể cố định cho mỗi thủ đoạn) |
| **Ngoài phạm vi** (ghi rõ trong README và slide) | Ví hoặc ngân hàng thật; API MoMo; đọc SMS hay tin nhắn của người B; xác thực danh tính thật; thu thập OTP, CCCD hay mật khẩu. Luồng `/help` công khai **không** chuyển hồ sơ cho đội vận hành thật (chỉ chuyển trong workspace demo) |

---

## 2. Kiến trúc

```
                 ┌──────────────────────────── 1 Docker container ─────────────────────────────┐
Browser ──HTTPS──►  FastAPI (uvicorn, 1 worker)                                                  │
                 │   ├─ /            → SPA tĩnh (React build)                                    │
                 │   ├─ /docs        → Swagger                                                   │
                 │   └─ /v1/*                                                                    │
                 │        ├─ incidents/  (Luồng 1) preprocess → LLM extract → containment        │
                 │        ├─ fraudops/   (Luồng 2) LLM compile → validator → assembler           │
                 │        │                         → regression → [chuyên viên sửa] → approve   │
                 │        ├─ gateway/    (Luồng 3) derive → lớp đối tác → khoanh vùng           │
                 │        │                         → layer1 → challenge → StagePolicy → ledger  │
                 │        └─ auth/, wallets/, demo/, healthz                                     │
                 │   Core: Validator · Assembler · Layer1 (dùng chung cho regression và gateway) │
                 │         SemanticMatcher · Baseline · StagePolicy · Ledger · Containment       │
                 │   Storage: Neon Postgres (prod) / SQLite (dev) · embedding cache trong DB     │
                 └──────────────┬───────────────────────────────┬──────────────────────────────┘
                                │ chỉ cho phép gọi ra ngoài tới generativelanguage.googleapis.com
                   Gemini Flash (JSON, vision)          gemini-embedding-001
```

| Module | Trách nhiệm | Dùng AI? |
|---|---|---|
| `preprocess` | `clean_input`, che PII bằng regex, `norm`, `norm_match` (bỏ dấu + mở rộng viết tắt) | Không |
| `incident_ai` | Trích xuất sự cố từ đoạn chat (ảnh nếu kịp), có nhãn nguồn gốc | **Có** |
| `containment` | Tính tất định `mode`, 3 việc cần làm, tạm giữ bảo vệ | Không |
| `rule_ai` | Sinh bản nháp RelayRule: anchor, câu hỏi kèm nhãn ý nghĩa, biến thể | **Có** |
| `validator` | V1–V8, chuyển điều kiện hành vi sang `behavior_hints` | Không |
| `assembler` | Gắn các trường do server quyết định: id, điều kiện sàn, ngưỡng, phương án `UNCLEAR`, dòng chống dặn trước, stage | Không |
| `layer1` | `layer1_match(rule, tx)`; **cùng một hàm** cho regression và gateway | Gián tiếp (embedding) |
| `semantic` | Gọi embedding, cache, cosine; fallback trigram | **Có** (embedding) |
| `regression` | Chạy `layer1` trên tập sạch và tập biến thể, quy khớp nhầm về từng anchor | Gián tiếp |
| `baseline` | Lớp đối tác mô phỏng: điểm 0–100 và quyết định | Không |
| `stage_policy` | Bảng nhãn ý nghĩa × giai đoạn → hành động; thứ tự mức nghiêm | Không |
| `gateway`, `ledger` | Ra quyết định, cấp challenge, ghi sổ, tạo biên lai | Không |
| `stats` (có thể có) | Thống kê theo luật, phản hồi báo nhầm | Không |

---

## 3. Tech stack

| Lớp | Lựa chọn | Ghi chú |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLModel, uvicorn | Swagger tự sinh |
| DB driver | `psycopg[binary]` cho Postgres; `sqlite3` khi dev | Chỉ khác nhau ở `DATABASE_URL` |
| AI SDK | `google-genai` | Structured output qua `response_schema` lấy từ LLM schema |
| HTTP client | `httpx` (async), có danh sách host được phép gọi ra | Chỉ cho phép `generativelanguage.googleapis.com` |
| Toán | `numpy` | Cosine |
| Auth | `pyjwt`; tài khoản giám khảo seed từ biến môi trường | Không có đăng ký |
| Rate limit | `slowapi` | Theo IP và cookie phiên |
| Prompt | File `ai/prompts/*.txt`, điền bằng `string.Template`; tên file mang số phiên bản (`rule_compile.v3.txt`) | Không cần Jinja2 |
| Ảnh (có thể có) | `Pillow` | Resize ≤ 1600px, bỏ EXIF |
| Frontend | React + Vite + TypeScript + Tailwind | shadcn/ui tùy chọn |
| Kiểu dữ liệu FE | `openapi-typescript` sinh từ `/openapi.json` | Tránh lệch hợp đồng |
| Test | `pytest` | LLM được mock; test race chạy trên Postgres trong CI |
| Deploy | Dockerfile multi-stage (node build → python runtime) | Một image |

---

## 4. Cấu trúc repo

```
scamrelay/
├─ backend/
│  ├─ app/
│  │  ├─ main.py, config.py, db.py, models.py
│  │  ├─ schemas/          # incident.py, rule.py, gateway.py, llm_incident.py, llm_rule.py
│  │  ├─ routers/          # incidents.py, fraudops.py, gateway.py, aux.py
│  │  ├─ core/             # preprocess, validator, assembler, layer1, semantic, regression, baseline,
│  │  │                    # stage_policy, gateway, ledger, containment, stats
│  │  └─ ai/               # interfaces.py, llm_client.py, incident_ai.py, rule_ai.py, prompts/
│  ├─ data/
│  │  ├─ action_registry.json       # hotline/link ĐÃ KIỂM CHỨNG (có source_url, verified_at)
│  │  ├─ seed_workspace.json        # ví, tài khoản nhận, biller (§5.2)
│  │  ├─ abbreviations.json         # bảng mở rộng viết tắt (§8)
│  │  ├─ benign_corpus.json         # ≥ 200 mẫu sinh bằng template + ≥ 20 ca bẫy viết tay
│  │  ├─ static_scam_keywords.json  # từ khóa thủ đoạn ĐÃ BIẾT, cho baseline (không có thủ đoạn HKD)
│  │  └─ fallback_tactics.json      # 3 thủ đoạn mẫu: từ khóa (fallback analyze) + output compile THẬT đã lưu (D7)
│  ├─ tests/
│  └─ requirements.txt, requirements-dev.txt, pytest.ini
├─ frontend/                        # /, /help, /ops, /wallet
├─ bench/
│  ├─ cases/dev/*.json
│  ├─ gen_benign.py, calibrate.py, check_demo.py, run_bench.py
│  └─ results/
├─ scripts/deploy.sh, smoke.sh
├─ .github/workflows/test.yml
├─ Dockerfile
└─ README.md
```

---

## 5. Dữ liệu

### 5.1 Bảng (Postgres trên Neon; SQLite khi dev)

Mọi bảng đều có `workspace_id` (D8) và `created_at`.

| Bảng | Trường chính |
|---|---|
| `workspace` | `id`, `owner` (`judge_01…`, `bench_runner`, `smoke`, `public:<cookie>`), `seeded_at` |
| `wallet` | `id`, `label`, `owner_name`, `balance_vnd`, `compromise_locked: bool`, `known_contacts: list[account_id]` (JSON) |
| `account` | `id` (mã sandbox), `display_name`, `age_days`, `is_verified_biller` |
| `transaction` | `id`, `wallet_id`, `to_account_id`, `amount_vnd`, `transfer_note`, `status` (`COMMITTED/HELD/STOPPED/BLOCKED/PENDING_CHALLENGE/EXPIRED`), `decision`, `reason_codes`, `partner_decision`, `partner_risk_score`, `matched_rule_id`, `matched_rule_version`, `receipt_id`, `release_at?`, `retry_after?` |
| `incident` | `id`, `submitted_at`, `is_proxy`, `protected_wallet_id?`, `analysis_json` (đã che PII), `mode` (`MANIPULATION/COMPROMISE/UNCLEAR`), `degraded`, `consent_handoff: bool` |
| `containment_policy` | `id`, `incident_id`, `wallet_id`, `mode`, `active`, `version`, `requested_by_proxy` |
| `external_action` | `id`, `incident_id`, `action_id`, `status` (`OPEN/USER_REPORTED_DONE/PENDING_EXTERNAL_CONFIRMATION`). **Không bao giờ có trạng thái "đã khóa"** cho tổ chức bên ngoài |
| `relay_rule` | `id`, `source_incident_id`, `version`, `stage` (`DRAFT_INVALID/SHADOW_LOG/ASK_ONLY/ENFORCE_HOLD/ROLLED_BACK/EXPIRED`), `draft_json`, `rule_json`, `validation_json`, `regression_json`, `regression_version`, `edited_by_human`, `ttl_hours`, `expires_at`, `activated_at?`, `corroboration_count`, `approvals` (JSON), `compile_requested_at`, `ai_seconds` |
| `rule_event` | Audit log: `rule_id`, `version`, `event` (`COMPILED/VALIDATED/EDITED/TESTED/APPROVED/OVERRIDE/ROLLED_BACK/EXPIRED/SHADOW_HIT/CHALLENGE_ISSUED/ANSWERED/FP_REPORTED`), `actor`, `payload` |
| `challenge` | `id`, `tx_id`, `rule_id`, `rule_version`, `options_json` (có `outcome`, **chỉ server đọc**), `floor_decision`, `floor_reasons`, `expires_at` (+5 phút), `used`, `answered_option_id?`, `answered_outcome?` |
| `receipt` | `id`, `tx_id`, `decision`, `reason_codes`, `policy_refs`, `hash` (sha256 của JSON chuẩn hóa) |
| `embedding_cache` | `text_hash`, `model`, `dim`, `vector` (BLOB float32) |

### 5.2 Seed workspace (hợp đồng cho người viết ca benchmark)

Danh sách id này **chốt cùng Contract Drop**; quynh dùng nó khi viết held-out. Muốn thêm id thì chỉ được thêm, không đổi hay xóa id cũ.

| Ví | Chủ | Số dư | `known_contacts` |
|---|---|---|---|
| `W-LAN` | Cô Lan (tiệm tạp hóa) | 6.000.000đ | `ACC-TUAN` |
| `W-HUNG` | Chú Hùng (tiệm sửa xe) | 8.000.000đ | `ACC-LANDLORD`, `ACC-SUPPLIER` |

| Tài khoản | Mô tả | `age_days` | Biller đã xác minh |
|---|---|---|---|
| `ACC-EVN` | Điện lực | 3000 | ✅ |
| `ACC-WATER` | Cấp nước | 3000 | ✅ |
| `ACC-TAX-GOV` | Nộp thuế điện tử (kênh chính thức) | 3000 | ✅ |
| `ACC-TUAN` | Tuấn, con trai cô Lan | 1500 | |
| `ACC-LANDLORD` | Chủ nhà của chú Hùng | 1200 | |
| `ACC-SUPPLIER` | Đại lý phụ tùng | 900 | |
| `ACC-SHOP` | Shop online quen | 700 | |
| `ACC-OLD-7731` | Tài khoản cá nhân lâu năm (nhận tiền lừa trong demo) | 420 | |
| `ACC-OLD-5520` | Tài khoản cá nhân lâu năm | 380 | |
| `ACC-NEW-01`, `ACC-NEW-02`, `ACC-NEW-03` | Tài khoản cá nhân mới mở | 2 / 5 / 12 | |

`recipient_is_new` = người nhận **không** nằm trong `known_contacts` của ví **và** ví chưa có giao dịch `COMMITTED` nào tới người nhận đó.

`corroboration_count` được tính lúc compile và lúc approve: là số sự cố **đã đồng ý chia sẻ**, cùng `tactic_family`, đến từ các ví hoặc phiên khác nhau trong workspace. Seed demo **không** có sẵn sự cố HKD nào khác, nên luật của cô Lan có `corroboration_count = 1`. Nhờ vậy cổng `ENFORCE_HOLD` hiện ở trạng thái bị khóa kèm lý do (§7.2f). Muốn minh họa trường hợp mở khóa thì gửi thêm một sự cố HKD từ phiên khác.

---

## 6. Schema hợp đồng

### 6.0 Hai lớp schema (bắt buộc)

Structured output của Gemini chỉ hỗ trợ một phần JSON Schema, nên chia làm hai lớp:

| Lớp | Đặt ở | Quy tắc |
|---|---|---|
| **LLM schema** (`schemas/llm_*.py`, hậu tố `LLM`) | Truyền vào `response_schema` | Phẳng; chỉ dùng `str`, `int`, `bool`, `list[str]`, `Literal`, `X \| None`; không union đa kiểu, không regex, không `extra="forbid"`, không giới hạn độ dài |
| **Domain schema** (`schemas/*.py`) | Sau khi nhận JSON | `extra="forbid"`; ràng buộc nghiệp vụ nằm ở validator (§7.2b) |

Luồng xử lý: Gemini trả JSON → `dict` → `validate_llm_output()` (gỡ trường quyền V8 → parse strict V1 → V2–V7) → assembler. Bước nào lỗi cũng trả 422 kèm danh sách lỗi. Mọi thay đổi tự động (V3, V8) đều được ghi vào `warnings`; không có nhánh nào tự sửa im lặng.

### 6.1 `IncidentAnalysis` (đầu ra LLM của Luồng 1)

```python
class Fact(BaseModel):
    text: str                                   # ≤ 200 ký tự
    provenance: Literal["OBSERVED_IN_EVIDENCE","USER_REPORTED","INFERRED","UNKNOWN"]

class IncidentAnalysis(BaseModel):
    tactic_family: Literal["FAKE_HKD_TAX_VERIFICATION","RECOVERY_FEE_SCAM",
                           "FAKE_SUPPORT_REMOTE_APP","IMPERSONATE_AUTHORITY",
                           "JOB_TASK_SCAM","OTHER_NEW"]
    tactic_slug: str | None                     # khi OTHER_NEW; domain kiểm ^[A-Z0-9_]{3,40}$
    tactic_summary_vi: str                      # ≤ 300 ký tự
    money_lost_vnd: int | None
    money_requested_vnd: int | None
    otp_or_password_disclosed: Literal["YES","NO","UNKNOWN"]
    remote_app_installed: Literal["YES","NO","UNKNOWN"]
    facts: list[Fact]                           # ≤ 12
    manipulation_cues: list[str]                # ≤ 8
```

LLM **không** trả `mode` hay `actions`; `containment.py` tự tính:

```
mode = COMPROMISE   nếu otp_or_password_disclosed == YES hoặc remote_app_installed == YES
     = MANIPULATION nếu có money_requested_vnd hoặc manipulation_cues không rỗng
     = UNCLEAR      còn lại → vẫn trả 3 việc an toàn mặc định (INV-03)
actions = ACTION_MAP[mode][tactic_family][:3]   # bảng tĩnh; text và kênh liên hệ lấy từ action_registry.json
```

### 6.2 `action_registry.json` (tĩnh, do người kiểm chứng)

```json
{ "id": "CALL_WALLET_HOTLINE_LOCK",
  "title_vi": "Gọi tổng đài ví để tạm khóa tài khoản",
  "contact": { "type": "tel", "value": "<ĐIỀN SAU KHI KIỂM CHỨNG>" },
  "source_url": "<URL trang chính thức>", "verified_at": "2026-11-28",
  "external_status_on_click": "PENDING_EXTERNAL_CONFIRMATION" }
```

Mục thiếu `source_url` hoặc `verified_at` vẫn hiện thẻ hướng dẫn chung, nhưng **không có số gọi hay link**, và `/healthz` báo `registry_unverified: [ids]`. LLM không bao giờ sinh số điện thoại hay đường dẫn. Kênh chính thức hiển thị khi giao dịch bị dừng hoặc giữ (§7.3) cũng lấy từ registry này.

### 6.3 RelayRule

**a) Lớp LLM (bản nháp do LLM viết)**

```python
FieldName = Literal["transfer_note","amount_vnd","recipient_is_new","recipient_account_age_days",
                    "tx_count_10m","is_verified_biller","account_compromise_flag","partner_risk_score"]
OpName = Literal["EQ","LTE","GTE","SEMANTIC_MATCH","CONTAINS_ANY","NOT_CONTAINS_ANY"]

class ConditionLLM(BaseModel):                  # mỗi kiểu giá trị một trường riêng
    field: FieldName
    op: OpName
    value_int: int | None = None
    value_bool: bool | None = None
    value_str_list: list[str] | None = None     # CONTAINS_ANY / NOT_CONTAINS_ANY
    anchor_phrases: list[str] | None = None     # SEMANTIC_MATCH

class PurposeOptionLLM(BaseModel):
    label_vi: str
    outcome: Literal["BENIGN","TACTIC_MATCH"]   # UNCLEAR do server thêm

class PurposeQuestionLLM(BaseModel):
    question_vi: str
    options: list[PurposeOptionLLM]             # đúng 3: 2 BENIGN + 1 TACTIC_MATCH
    tactic_alert_vi: str                        # giải thích thủ đoạn, hiện khi bị dừng

class StructuredVariantLLM(BaseModel):          # chỉ để kiểm thử, KHÔNG phải kịch bản lừa
    transfer_note: str
    amount_vnd: int
    manipulation_intent: str

class RelayRuleDraftLLM(BaseModel):
    tactic_family: str
    conditions: list[ConditionLLM]
    purpose_question: PurposeQuestionLLM
    variants: list[StructuredVariantLLM]
```

**Lớp domain** dùng cùng tên trường, bỏ hậu tố `LLM`, đặt `extra="forbid"`, và thêm `match_mode: Literal["ALL"] = "ALL"` cùng `behavior_hints: list[Condition] = []` vào `RelayRuleDraft`. Chuyên viên sửa cũng chính là sửa `RelayRuleDraft` (§7.2d).

**b) Luật hoàn chỉnh (server dựng, lưu trong `rule_json`)**

```python
Outcome = Literal["BENIGN","TACTIC_MATCH","UNCLEAR"]
Stage   = Literal["DRAFT_INVALID","SHADOW_LOG","ASK_ONLY","ENFORCE_HOLD","ROLLED_BACK","EXPIRED"]

class RuleOption(BaseModel):
    id: str                                     # "o1".."o4", server gán
    label_vi: str
    outcome: Outcome

class Approval(BaseModel):
    by: str; stage: Stage; at: datetime; override_reason: str | None = None

class Lifecycle(BaseModel):
    stage: Stage
    ttl_hours: int
    expires_at: datetime
    corroboration_count: int
    approvals: list[Approval]
    benign_regression: dict | None              # {"checked": 240, "flagged": 0}
    variant_coverage: dict | None               # {"checked": 6, "triggered": 6}
    edited_by_human: bool

class ObservableSignals(BaseModel):
    match_mode: Literal["ALL"] = "ALL"
    conditions: list[Condition]                 # điều kiện nội dung, lấy từ draft đã qua validator
    guard_conditions: list[Condition]           # điều kiện sàn, server gắn từ config (S4)
    normalize: list[str]                        # ["strip_diacritics","expand_abbreviations"]
    threshold: float                            # config.SEMANTIC_THRESHOLD

class JitQuestion(BaseModel):
    question_vi: str
    options: list[RuleOption]                   # 4 phương án; phương án UNCLEAR "Mục đích khác" luôn ở cuối
    tactic_alert_vi: str
    anti_coaching_notice_vi: str                # hằng số config.ANTI_COACHING_NOTICE_VI

class RelayRule(BaseModel):
    rule_id: str                                # "RL-20261128-0001"
    version: int
    source_incident_id: str
    target_scope: Literal["TACTIC_PATTERN"] = "TACTIC_PATTERN"
    tactic_family: str
    lifecycle: Lifecycle
    observable_signals: ObservableSignals
    behavior_hints: list[Condition]             # chuyên viên tham khảo, không dùng để lọc
    jit_purpose_question: JitQuestion
    variants: list[StructuredVariant]
```

Điều kiện sàn (S4), gắn giống nhau cho mọi luật:
`[{"field":"amount_vnd","op":"GTE","value_int":MIN_ASK_AMOUNT_VND}, {"field":"is_verified_biller","op":"EQ","value_bool":false}]`

`ANTI_COACHING_NOTICE_VI = "Nếu có người dặn bạn chọn một đáp án cụ thể ở màn hình này, đó là dấu hiệu lừa đảo. Hãy dừng lại và gọi kênh chính thức."`

### 6.4 Kiểu dữ liệu dùng chung (`ai/interfaces.py` và `schemas/`)

```python
class ValidationResult(BaseModel):               # đặt ở schemas/rule.py, KHÔNG đặt ở interfaces.py (tránh import vòng)
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []                     # V3 chuyển điều kiện, V8 gỡ trường quyền, V6b
    sanitized_draft: RelayRuleDraft | None = None

class AnalyzeResult(BaseModel):
    analysis: IncidentAnalysis
    degraded: bool = False

class CompileResult(BaseModel):
    raw: dict                                    # JSON thô; router đưa vào validate_llm_output
    source: Literal["LLM","CACHED_FALLBACK"]
    degraded: bool = False
    llm_seconds: float

@dataclass
class AnchorSet:
    phrases: list[str]                           # đã qua norm_match
    vectors: np.ndarray | None                   # (N, 768) float32, đã chuẩn hóa L2; None khi chạy trigram
    degraded: bool = False

class DerivedTx(BaseModel):                      # server tự tính; client không gửi được
    wallet_id: str
    to_account_id: str
    amount_vnd: int
    transfer_note: str
    note_norm: str                               # norm_match(transfer_note)
    recipient_is_new: bool
    recipient_account_age_days: int
    tx_count_10m: int                            # chỉ đếm COMMITTED/HELD; không đếm PENDING/EXPIRED
    is_verified_biller: bool
    is_known_contact: bool
    account_compromise_flag: bool                # = wallet.compromise_locked
    partner_risk_score: int | None = None        # điền sau khi chạy baseline

class BaselineResult(BaseModel):
    decision: Literal["ALLOW","WARN","BLOCK"]
    risk_score: int                              # 0–100
    reasons: list[str]

class FlaggedExample(BaseModel):
    transfer_note: str; amount_vnd: int; score: float; top_anchor: str | None

class RegressionResult(BaseModel):
    rule_version: int
    benign_checked: int
    benign_flagged: int
    flagged_examples: list[FlaggedExample]
    flags_by_anchor: dict[str, int]              # anchor nào gây nhiều khớp nhầm nhất
    variants_checked: int
    variants_triggered: int
    variants_missed: list[str]
    seconds: float
    degraded: bool
```

### 6.5 Gateway

```python
Decision = Literal["ALLOW","ALLOW_WITH_WARNING","HOLD_15M","STOP_AND_EXPLAIN","HOLD_UNTIL_VERIFIED","BLOCK"]

class TransferRequest(BaseModel):
    wallet_id: str
    to_account_id: str
    amount_vnd: conint(gt=0, le=50_000_000)
    transfer_note: constr(max_length=120) = ""

class ChallengeOptionOut(BaseModel):
    id: str; label_vi: str                       # KHÔNG có outcome

class ChallengeOut(BaseModel):
    challenge_id: str
    question_vi: str
    options: list[ChallengeOptionOut]
    anti_coaching_notice_vi: str
    expires_at: datetime

class BaselineView(BaseModel):                   # để /wallet hiển thị song song
    decision: Literal["ALLOW","WARN","BLOCK"]
    risk_score: int
    as_final: Decision                           # ALLOW→ALLOW, WARN→HOLD_15M, BLOCK→BLOCK

class EvaluateResponse(BaseModel):
    tx_id: str
    status: Literal["FINAL","CHALLENGE_JIT"]
    decision: Decision | None                    # None khi CHALLENGE_JIT
    challenge: ChallengeOut | None
    baseline: BaselineView
    reason_codes: list[str]
    matched_rule_id: str | None
    receipt_id: str | None
    message_vi: str | None
    official_channels: list[dict]                # từ registry, khi bị dừng hoặc giữ
    retry_after: datetime | None
    rule_active_for_seconds: int | None          # cho dải "Luật mới có hiệu lực X phút trước"

class SubmitChallengeRequest(BaseModel):
    challenge_id: str
    option_id: str

class SubmitChallengeResponse(BaseModel):
    tx_id: str
    decision: Decision
    reason_codes: list[str]
    receipt_id: str
    tactic_alert_vi: str | None                  # chỉ khi bị dừng hoặc giữ do chọn TACTIC_MATCH
    message_vi: str | None                       # giải thích hành động; dòng chống dặn trước khi ALLOW_WITH_WARNING
    official_channels: list[dict]
    retry_after: datetime | None
```

Mọi tín hiệu trong `DerivedTx` đều **do server tự suy ra** từ sổ và seed, nên client không giả mạo được.

---

## 7. Pipeline chi tiết

### 7.1 Luồng 1: Khoanh vùng (`POST /v1/incidents/analyze`)

1. **Input (chỉ nhận JSON):**
   - `text` (≤ 6.000 ký tự).
   - `image_base64` (có thể có; ảnh gốc ≤ 4MB, JPEG/PNG, frontend resize về ≤ 1600px).
   - `is_proxy` ("Tôi là người thân kích hoạt hộ").
   - `protect_wallet_id?`: yêu cầu tạm giữ bảo vệ ví này, chỉ dùng được trong workspace demo.
   - `consent_handoff` (mặc định `false`): đồng ý chuyển hồ sơ sang FraudOps (§7.1c).
   - `followup_text?` + `incident_id?` khi bổ sung tình tiết.
2. **Preprocess (tất định):**
   - Chuẩn hóa Unicode NFC, bỏ ký tự điều khiển và ký tự vô hình.
   - Che PII **theo đúng thứ tự sau**; mỗi bước bỏ qua phần đã gắn nhãn ở bước trước:
     1. **Bảo vệ số tiền:** dãy số (có hoặc không có `.`/`,`) đứng sát đơn vị tiền (`đ`, `d`, `vnd`, `vnđ`, `đồng`, `dong`, `k`, `tr`, `triệu`, `trieu`), hoặc đứng sau "chuyển/chuyen/nạp/phí/phi", được **giữ nguyên**. Dãy bắt đầu bằng `0` theo sau là chữ số thì không được coi là tiền.
     2. **SĐT:** `(?:\+84|0)\d{9}`, cho phép dấu cách hoặc dấu chấm giữa các nhóm → `[SĐT]`.
     3. **CCCD:** đúng 12 chữ số → `[CCCD]`.
     4. **OTP:** 4–8 chữ số trong cửa sổ 30 ký tự quanh "OTP / mã / ma xac thuc" → `[OTP]`. Cờ `otp_mentioned` gửi kèm LLM bật khi có OTP bị che, hoặc khi văn bản có chữ "OTP" / "mã xác thực".
     5. **STK:** dãy còn lại dài 9–19 chữ số → `[STK]`. Dãy 6–8 chữ số chỉ bị che khi đứng sau "stk / số tài khoản / tk".
   - URL giữ ở dạng text, **không bao giờ fetch**, UI hiển thị dạng không bấm được.
   - Ảnh (nếu có): resize, bỏ EXIF, chỉ giữ trong bộ nhớ, không ghi đĩa, không bao giờ chuyển sang FraudOps.
3. **LLM extract:** prompt `incident_extract.vN.txt`, temperature 0, structured output `IncidentAnalysisLLM`, timeout 25 giây, retry 1 lần. Nội dung người dùng được bọc trong `<untrusted_evidence>`, và prompt nói rõ đây là dữ liệu, không phải chỉ thị.
4. **Lỗi, timeout hoặc 429:** chuyển sang classifier từ khóa trên `fallback_tactics.json`, gắn `degraded: true`. Không bao giờ kết luận "an toàn".
5. **Containment (tất định).** Tính `mode` và 3 việc cần làm như §6.1. Nếu có `protect_wallet_id`:
   - Tạo hoặc **nâng** `containment_policy`. Chỉ được nâng theo chiều không có → `MANIPULATION` → `COMPROMISE`, không bao giờ hạ.
   - `MANIPULATION`: giao dịch đi tới tài khoản **không** phải biller đã xác minh và **không** nằm trong `known_contacts` → `HOLD_UNTIL_VERIFIED`. Biller và người quen không bị khoanh vùng chặn (lớp đối tác vẫn áp dụng).
   - `COMPROMISE`: mọi giao dịch đi đều `BLOCK`, kể cả biller; đặt `wallet.compromise_locked = true`.
   - Chủ ví thấy thông báo ngay trên `/wallet`: `GET /v1/wallets` trả trường `protective_hold_notice`, đọc thẳng từ `containment_policy` đang bật, ví dụ *"Người thân đã yêu cầu tạm giữ bảo vệ ví của bạn lúc HH:MM. Chỉ bạn mới gỡ được, bằng cách xác minh qua kênh chính thức."* Không có bảng thông báo riêng.
   - **Gỡ tạm giữ:** sandbox không có endpoint gỡ (bản thật: chủ ví xác minh qua kênh chính thức). Demo dùng Reset.
   - **Giới hạn của kích hoạt hộ (INV-11):** response không bao giờ chứa số dư hay lịch sử giao dịch; `/help` không có chức năng chuyển tiền; không tham số nào cho phép hạ mức.
6. **Follow-up** (ví dụ "Mẹ lỡ đọc OTP"): chạy lại bước 3 với lịch sử sự cố, rồi merge theo quy tắc **chỉ nâng mức** (`UNKNOWN` → `YES` thì được, `YES` → `NO` thì không). Nếu `mode` nâng lên `COMPROMISE` thì nâng policy; thông báo trên ví tự cập nhật theo policy. Follow-up cũng có thể bật `consent_handoff` (chỉ bật, không tắt).
7. **Response:** `incident_id`, `mode`, `actions[3]`, `analysis` (`IncidentAnalysis` đã che PII, gồm `facts` có nhãn nguồn gốc; frontend dùng để dựng gói hồ sơ), `policy_summary_vi`, `protective_hold` (`{wallet_label, mode}` hoặc `null`), `degraded`.

**7.1b Gói hồ sơ "Kể 1 lần, dùng mọi nơi" (frontend, không có endpoint)**
- Frontend dựng chuỗi Markdown từ response của `analyze` (đã che PII) và registry, tải bằng Blob `.md`. Không chứa ảnh.
- Gồm 3 mục:
  1. Tóm tắt có dẫn chiếu bằng chứng, dành cho CSKH/ngân hàng.
  2. Dòng thời gian để trình báo công an.
  3. Danh mục chứng từ để đối chiếu bảo hiểm, ghi rõ *"chỉ hỗ trợ chuẩn bị hồ sơ, không kết luận quyền bồi thường"*.
- PDF (có thể có): render Markdown rồi gọi `window.print()`.

**7.1c Đồng ý chia sẻ (cờ `consent_handoff` trong `analyze`)**
- Cạnh ô đồng ý, UI ghi rõ 3 điều:
  1. **Chia sẻ những gì:** tóm tắt thủ đoạn và các trường giao dịch đã che định danh.
  2. **Dùng để làm gì:** tạo luật bảo vệ người khác.
  3. **Lưu trong bao lâu:** bản thử nghiệm chỉ lưu trong workspace demo và xóa khi Reset; bản thật xóa theo TTL của luật.
- Sự cố chưa đồng ý thì không hiện ở hàng đợi `/ops`, và `compile` trả `403 CONSENT_REQUIRED`.
- Sandbox không cài xóa tự động theo TTL. Slide và README nói đúng như vậy.

### 7.2 Luồng 2: Tiếp sức

**a) Compile (`POST /v1/fraudops/rules/compile`, body `{incident_id}`)**
1. Yêu cầu đã có đồng ý. Ghi `compile_requested_at`.
2. `rule_ai.compile_rule(analysis)` dùng prompt `rule_compile.vN.txt`, timeout 30 giây.
   - Nếu lỗi hoặc 429: đọc output đã lưu của thủ đoạn tương ứng trong `fallback_tactics.json` (`CACHED_FALLBACK`, `degraded: true`). Thủ đoạn không có trong file (`OTHER_NEW`) thì trả lỗi kèm nút "Biên dịch lại".
3. `validate_llm_output(raw)`:
   - Không đạt: lưu luật ở stage `DRAFT_INVALID` kèm lỗi; UI hiện lỗi và nút "Biên dịch lại".
   - Đạt: assembler dựng `RelayRule` version 1, stage `SHADOW_LOG` (chỉ ghi log, không hỏi), `ttl_hours` mặc định 24.
4. Embed toàn bộ anchor trong **một request** theo lô, có cache.
5. Cộng thời gian xử lý vào `ai_seconds`.
6. **Response:** `rule`, `validation` (lỗi và cảnh báo), `source`, `degraded`. UI tự gọi regression ngay sau đó.

> **Tính trung thực của demo:** cảnh "kiểm thử hồi quy bắt được câu mẫu quá rộng" (ABOUT §7) chỉ được dùng output LLM **thật** (gọi trực tiếp, hoặc đã lưu trong `fallback_tactics.json`). UI ghi rõ nguồn (`LLM` / `kết quả đã lưu`). Nếu không có lượt chạy thật nào sinh ra câu mẫu quá rộng, thì đổi kịch bản: chị Mai tự xóa một câu mẫu chị cho là rộng rồi chạy lại. **Không** tự chèn lỗi vào output rồi gọi đó là lỗi của AI.

**b) DeterministicValidator**

| # | Kiểm tra |
|---|---|
| V1 | Schema strict (`extra="forbid"`), chạy sau khi đã gỡ trường quyền (V8) |
| V2 | `field` và `op` thuộc whitelist, và `op` phải hợp với `field`:<br>• `transfer_note` → `SEMANTIC_MATCH` / `CONTAINS_ANY` / `NOT_CONTAINS_ANY`<br>• trường số (`amount_vnd`, `recipient_account_age_days`, `tx_count_10m`, `partner_risk_score`) → `EQ` / `LTE` / `GTE`<br>• trường bool (`recipient_is_new`, `is_verified_biller`, `account_compromise_flag`) → `EQ`<br>• `tactic_family` khớp `^[A-Z0-9_]{3,60}$` |
| V3 | Có 1–4 điều kiện. **Lớp 1 chỉ gồm điều kiện nội dung trên `transfer_note`**, và phải có ít nhất 1 `SEMANTIC_MATCH` hoặc `CONTAINS_ANY`. Điều kiện hành vi do LLM đề xuất được chuyển sang `behavior_hints`, kèm cảnh báo, và không dùng để lọc. Lý do: một điều kiện rút từ vụ cô Lan (ví dụ "≥ 1,5 triệu", "người nhận mới") sẽ làm lọt giao dịch 1,2 triệu tới tài khoản cũ của chú Hùng. Điều kiện sàn (S4) do server gắn và giống nhau cho mọi luật |
| V3b | `NOT_CONTAINS_ANY` dùng để loại trừ ngữ cảnh sạch dễ nhầm (ví dụ "thue nha", "thue mat bang"): tối đa 10 cụm, mỗi cụm 3–40 ký tự sau chuẩn hóa. `CONTAINS_ANY`: tối đa 12 cụm |
| V4 | `anchor_phrases`: 3–12 câu, các câu phải khác nhau sau chuẩn hóa, mỗi câu 3–80 ký tự. **Cấm chuỗi ≥ 6 chữ số, SĐT, URL, email** (luật không được nhắm vào tài khoản hay cá nhân). Lệnh cấm này áp cho mọi cụm chữ trong luật: `CONTAINS_ANY`, `NOT_CONTAINS_ANY`, biến thể |
| V5 | Có đúng một trường giá trị, và trường đó khớp `op`. `amount_vnd` nằm trong [10.000; 50.000.000]; `partner_risk_score` trong [0; 100]; số đếm không âm |
| V6 | Đúng 3 phương án: 2 `BENIGN` + 1 `TACTIC_MATCH`. Nhãn dài 1–100 ký tự; câu hỏi dài 1–120 ký tự. Câu hỏi và nhãn không chứa từ cấm: bản có dấu "lừa", "lừa đảo", "bị dụ", "kẻ gian", "nghi ngờ"; bản không dấu "lua dao", "bi du", "ke gian", "nghi ngo" (không cấm "lua" đứng riêng vì trùng "lúa", "lựa"). Không chứa SĐT hay URL |
| V6b | **Chỉ cảnh báo, không chặn:** nếu nhãn `TACTIC_MATCH` chứa nguyên văn một anchor (sau chuẩn hóa), báo "phương án đang nêu đúng tên thủ đoạn; nên viết theo nhóm mục đích chung" (chống dò đáp án, ABOUT §3.3) |
| V7 | `tactic_alert_vi` dài 1–240 ký tự, không chứa SĐT, URL hay email. Kênh liên hệ chỉ được lấy từ registry |
| V8 | Gỡ ở mọi cấp, ghi cảnh báo, các trường quyền: `threshold`, `action`, `stage`, `ttl_hours`, `corroboration_count`, `approved_by`, `approvals`, `rule_id`, `version`, `source_incident_id`, `target_scope`, `lifecycle`, `guard_conditions`, `normalize`, `anti_coaching_notice_vi`, `id`, `benign_regression`, `variant_coverage`, `edited_by_human` |
| VAR | Có 5–8 biến thể; `transfer_note` dài 1–60 ký tự; `amount_vnd` trong [10.000; 50.000.000]; `manipulation_intent` ≤ 100 ký tự; cùng lệnh cấm như V4 |

**c) Assembler (tất định).** Từ bản nháp đã qua validator, assembler dựng `RelayRule` (§6.3b):
- Gán `rule_id` và `version`.
- Gán `o1..o3` cho 3 phương án của LLM và thêm `o4` = `{"label_vi": "Mục đích khác", "outcome": "UNCLEAR"}`.
- Gắn điều kiện sàn, `threshold`, `normalize`, dòng chống dặn trước, `stage` và `ttl_hours`.

**d) Chuyên viên sửa bản nháp (`PUT /v1/fraudops/rules/{id}/draft`, body `RelayRuleDraft`)**
- Chỉ sửa được khi stage là `DRAFT_INVALID` hoặc `SHADOW_LOG`.
- Chạy lại `validate_llm_output` (V1–V8 như trên), tăng `version`, đặt `edited_by_human = true`, **hủy kết quả regression cũ**, và chỉ embed lại các anchor mới (phần còn lại đã có cache).
- Ghi `rule_event EDITED` kèm diff (anchor thêm và bớt). Thời gian sửa được tính vào thời gian con người.

**e) Regression (`POST /v1/fraudops/rules/{id}/regression-test`)**
- Chạy `layer1_match` (**đúng hàm mà gateway dùng**: điều kiện nội dung + điều kiện sàn + miễn trừ biller) trên:
  - **Tập sạch** `benign_corpus.json`, gồm:
    - **≥ 200 mẫu sinh bằng template** (`bench/gen_benign.py`): tiền nhà, tiền hàng, học phí, chia tiền ăn, trả nợ bạn, mừng cưới, đặt cọc, tiền điện nước chuyển cho chủ nhà… nhân với nhiều cách viết và số tiền.
    - **≥ 20 ca bẫy viết tay.** Bắt buộc có nhóm "thuê" ("tra tien thue nha thang 12", "thue mat bang", "tien thue xe", "phi gia han hop dong thue"), vì sau khi bỏ dấu, "thuế" và "thuê" cùng thành "thue". Thêm các ca: nộp hộ thuế cho người quen, phí dịch vụ kế toán, hoàn tiền đơn hàng, cập nhật phần mềm bán hàng.
    - Mỗi mẫu có `transfer_note`, `amount_vnd`, `is_verified_biller`.
  - **Biến thể** trong luật (5–8). Chỉ dùng để tham khảo khi vận hành, **không** đưa vào số liệu báo cáo.
- Trả về `RegressionResult` (§6.4), gồm `flags_by_anchor`: mỗi mẫu sạch bị khớp được quy về anchor cho cosine cao nhất. UI tô đậm anchor gây khớp nhầm để chuyên viên xóa.
- Lưu kèm `rule.version` và cộng `seconds` vào `ai_seconds`.
- Embedding của tập sạch được seed sẵn vào cache khi khởi động, nên mỗi lượt regression chỉ tốn phép tính cosine.

**f) Approve (`POST /v1/fraudops/rules/{id}/approve`, body `{stage, ttl_hours, override_reason?}`)**
- `stage` là `ASK_ONLY` hoặc `ENFORCE_HOLD`; `ttl_hours` từ 1 đến 72, mặc định 24.
- Phải có regression cho **đúng version hiện tại**, nếu không thì trả `409 REGRESSION_REQUIRED`.
- **Khóa Approve:** nếu `benign_flagged > 0` mà không có `override_reason` (≥ 15 ký tự) thì trả `409 APPROVE_LOCKED`. Có lý do ghi đè thì cho duyệt và ghi `rule_event OVERRIDE`.
- `ASK_ONLY`: duyệt từ `SHADOW_LOG`.
- `ENFORCE_HOLD`: là **lần duyệt thứ hai**, chỉ duyệt được từ `ASK_ONLY`, và cần `corroboration_count ≥ 2`, nếu không thì trả `409 CORROBORATION_REQUIRED`.
  - `corroboration_count` là số báo cáo độc lập đến từ các tài khoản đã xác minh khác nhau. Trong sandbox, server tính tự động theo §5.2; không có UI gộp sự cố.
  - Bản thật cần người duyệt lần hai khác người duyệt lần một. Sandbox mỗi giám khảo có một workspace riêng, nên chỉ ghi log người duyệt.
- Ghi `approvals += {by, stage, at, override_reason}`, `activated_at` (lần đầu luật có hiệu lực) và `expires_at = now + ttl`.
- **Đồng hồ 2 mốc** (trả trong response, UI hiển thị chữ lớn):
  - `ai_seconds` = tổng thời gian máy chạy compile và mọi lượt regression của luật.
  - `human_seconds` = (`approved_at` − `compile_requested_at`) − `ai_seconds`.
  - `report_to_live_seconds` = `activated_at` − `incident.submitted_at`.

**g) Rollback và hết hạn**
- `POST …/rollback` chuyển luật sang `ROLLED_BACK` ngay lập tức. Challenge đã cấp từ luật đó, khi được trả lời, sẽ nhận quyết định bằng mức sàn (§7.3).
- **Hết hạn kiểu lazy:** mỗi request tới gateway hoặc `/fraudops` chuyển các luật có `expires_at < now` sang `EXPIRED`, không cần cron.

**h) Bảng theo dõi luật (có thể có, chỉ làm nếu 30/11 còn dư giờ)**
- `GET /v1/fraudops/rules/{id}/stats` trả về: `asked`, `answered` (`TACTIC_MATCH` / `BENIGN` / `UNCLEAR`), `shadow_hits`, `fp_reports`, `last_hit_at`.
- `suggest_upgrade = (answered.TACTIC_MATCH ≥ 2 và stage == ASK_ONLY)`. Đây chỉ là gợi ý cho chuyên viên, **không tự nâng giai đoạn**.
- `POST /v1/gateway/feedback` (body `{tx_id, kind: "FALSE_POSITIVE", note?}`) do nút "Báo nhầm" trên màn kết quả gọi, ghi `rule_event FP_REPORTED`.

### 7.3 Luồng 3: Chặn đúng (`POST /v1/gateway/evaluate-transfer`)

```python
SEVERITY = {"ALLOW":0, "ALLOW_WITH_WARNING":1, "HOLD_15M":2,
            "STOP_AND_EXPLAIN":3, "HOLD_UNTIL_VERIFIED":4, "BLOCK":5}
PARTNER_MAP = {"ALLOW":"ALLOW", "WARN":"HOLD_15M", "BLOCK":"BLOCK"}

def evaluate(req, ws):
    expire_rules_lazily(ws)
    tx   = derive_signals(req, ws)                         # §6.4
    base = baseline_score(tx); tx.partner_risk_score = base.risk_score
    floor = Floor(PARTNER_MAP[base.decision], [f"PARTNER_{base.decision}"])   # D9

    # 1) Khoanh vùng ví (ví của cô Lan)
    pol = active_containment(tx.wallet_id)
    if pol and pol.mode == "COMPROMISE":
        return final(tx, floor.raise_to("BLOCK", "CONTAINMENT_COMPROMISE"), base)
    if pol and pol.mode == "MANIPULATION" and not (tx.is_verified_biller or tx.is_known_contact):
        floor.raise_to("HOLD_UNTIL_VERIFIED", "CONTAINMENT_MANIPULATION")

    # 2) Luật tiếp sức; biller đã xác minh không bao giờ bị hỏi (INV-15)
    hits = [] if tx.is_verified_biller else [
        (r, s) for r in active_rules(ws) if (s := layer1_match(r, tx, anchors_of(r))) is not None]
    for r, _ in hits:
        if r.stage == "SHADOW_LOG": log_event(r, "SHADOW_HIT", tx)
    live = [(r, s) for r, s in hits if r.stage in ("ASK_ONLY", "ENFORCE_HOLD")]

    # 3) (có thể có) Dừng mềm còn hiệu lực: trong 30 phút sau STOP_AND_EXPLAIN cùng người nhận hoặc cùng luật
    if stop_cooldown_active(tx, [r for r, _ in live]):
        floor.raise_to("STOP_AND_EXPLAIN", "STOP_COOLDOWN")

    # 4) Chỉ hỏi khi câu trả lời còn có thể thay đổi kết quả
    if live and SEVERITY[floor.decision] < SEVERITY["STOP_AND_EXPLAIN"]:
        r, _ = max(live, key=lambda x: (STAGE_RANK[x[0].stage], x[1]))
        ch = issue_challenge(tx, r, floor)                 # lưu floor; hết hạn sau 5 phút; dùng 1 lần
        return pending(tx, r, ch, base)                    # status = CHALLENGE_JIT, tx PENDING_CHALLENGE
    return final(tx, floor, base, matched=live[0][0] if live else None)
```

**`layer1_match(rule, tx)`** trả `None` nếu không khớp; nếu khớp thì trả điểm dùng để xếp hạng. Luật khớp khi **mọi** `conditions` và `guard_conditions` đều thỏa (`ALL`):
- `SEMANTIC_MATCH`: thỏa khi `len(note_norm) ≥ 4` và `max_cosine(note_norm, anchors) ≥ threshold`. Điểm là cosine đó.
- `CONTAINS_ANY` / `NOT_CONTAINS_ANY`: so cụm đã `norm_match` theo ranh giới từ trên `note_norm`.
- Luật không có `SEMANTIC_MATCH` thì điểm = 1.0.

**`POST /v1/gateway/submit-challenge`** (body `{challenge_id, option_id}`) chạy **toàn bộ trong một transaction DB**, theo thứ tự:
1. **Claim nguyên tử:** `UPDATE challenge SET used = true WHERE id = :id AND used = false AND expires_at > now() RETURNING *`. Không có dòng trả về thì từ chối.
2. `option_id` phải thuộc challenge đó. `outcome` lấy từ `options_json` phía server; client không gửi được outcome.
3. **Kiểm tra lại ví** (`SELECT … FOR UPDATE` trên dòng `wallet`): nếu ví vừa chuyển sang `COMPROMISE` thì trả `BLOCK`; nếu vừa có `MANIPULATION` (và người nhận không phải biller hay người quen) thì nâng mức sàn lên `HOLD_UNTIL_VERIFIED`. Đây là trường hợp mở hai tab.
4. **Đọc lại luật:** nếu luật không còn hiệu lực (`ROLLED_BACK` hoặc `EXPIRED`) thì không áp hành động của luật; quyết định = mức sàn, reason `RULE_NO_LONGER_ACTIVE`.
5. `action = STAGE_POLICY[rule.stage][outcome]` (bảng bên dưới).
6. **Chống dò đáp án (có thể có):** nếu ví đã trả lời câu hỏi của cùng luật trong 24 giờ qua với outcome khác, nâng lên ít nhất `HOLD_15M`, reason `ANSWER_SWITCH`.
7. `final = max_severity(mức sàn, action)`.
8. Kiểm tra số dư (với `ALLOW*`), ghi sổ, tạo receipt, ghi `rule_event ANSWERED` kèm outcome.

SQLite khi dev không hỗ trợ `FOR UPDATE`, nên dùng `BEGIN IMMEDIATE`. Test race chạy trên Postgres trong CI.

**StagePolicy** (ABOUT §4.3):

| Giai đoạn | Lớp 1 khớp | `TACTIC_MATCH` | `BENIGN` | `UNCLEAR` |
|---|---|---|---|---|
| `SHADOW_LOG` | Chỉ ghi log, không hỏi | — | — | — |
| `ASK_ONLY` | Hỏi mục đích | `STOP_AND_EXPLAIN` | `ALLOW_WITH_WARNING` | `HOLD_15M` |
| `ENFORCE_HOLD` | Hỏi mục đích | `HOLD_UNTIL_VERIFIED` | `ALLOW_WITH_WARNING` | `HOLD_15M` |

Vì quyết định cuối luôn lấy `max` với mức sàn, chọn `BENIGN` khi lớp đối tác đang `WARN` sẽ cho `HOLD_15M` chứ không phải `ALLOW_WITH_WARNING`. Đây là cách `partner_risk_score` giảm thiểu trường hợp nạn nhân bị dặn trước (ABOUT §4.4).

**Hành động, ghi sổ và màn hình:**

| Hành động | Ghi sổ | Màn kết quả |
|---|---|---|
| `ALLOW` | Trừ tiền, `COMMITTED` | Thành công |
| `ALLOW_WITH_WARNING` | Trừ tiền, `COMMITTED` | Thành công, kèm dòng chống dặn trước |
| `HOLD_15M` | `HELD`, `release_at = +15 phút`; trừ tiền khi giải phóng (kiểm tra số dư lúc đó) | Đếm ngược và lý do |
| `STOP_AND_EXPLAIN` | `STOPPED`, **0đ rời ví**; `retry_after = +30 phút` | `tactic_alert_vi`, kênh chính thức từ registry, giờ được tạo lại giao dịch |
| `HOLD_UNTIL_VERIFIED` | `HELD`, `release_at = null`; chỉ giải phóng khi chủ ví xác minh qua kênh chính thức (sandbox: chỉ có Reset) | Giải thích và kênh chính thức |
| `BLOCK` | `BLOCKED` (chỉ đến từ khoanh vùng `COMPROMISE`) | Ví đang được khóa bảo vệ |

- `POST /v1/demo/fast-forward-holds` chỉ giải phóng các giao dịch `HOLD_15M`.
- **Không có đường nào commit một giao dịch đang `PENDING_CHALLENGE` mà bỏ qua bước trả lời** (INV-08). Challenge hết hạn thì giao dịch thành `EXPIRED` (không trừ tiền).
- **Receipt** gồm `decision`, `reason_codes`, `policy_refs` (id của containment policy và relay rule, kèm version) và `hash = sha256(JSON chuẩn hóa)`. UI hiển thị mã biên lai rút gọn.

---

## 8. SEMANTIC_MATCH với tiếng Việt

1. **Chuẩn hóa `norm_match(text)`:**
   - Chạy `norm()`: lowercase, NFD rồi bỏ dấu, `đ→d`, bỏ ký tự đặc biệt, gộp khoảng trắng.
   - Sau đó mở rộng viết tắt **theo từ nguyên vẹn**, dùng `data/abbreviations.json`.
   - Áp dụng cho mọi phía: anchor, nội dung chuyển khoản, cụm `CONTAINS_ANY` / `NOT_CONTAINS_ANY`, tập sạch, biến thể.
   - Danh sách khởi điểm, chỉ gồm viết tắt không nhập nhằng: `hkd→ho kinh doanh`, `mst→ma so thue`, `ck→chuyen khoan`, `stk→so tai khoan`, `tk→tai khoan`, `cccd→can cuoc cong dan`, `cmnd→chung minh nhan dan`, `tncn→thu nhap ca nhan`, `gtgt→gia tri gia tang`, `sdt→so dien thoai`, `nh→ngan hang`. Không đưa vào `hd` (hóa đơn / hợp đồng) và `dk` (đăng ký / điều kiện).
   - Hệ quả đã biết: "thuế" và "thuê" cùng thành "thue". Xử lý bằng `NOT_CONTAINS_ANY` (V3b) cùng nhóm bẫy "thuê" trong tập sạch; nếu vẫn nhầm thì regression sẽ khóa Approve.
2. **Embedding:**
   - Model `gemini-embedding-001`, `task_type="SEMANTIC_SIMILARITY"`, `output_dimensionality=768`, chuẩn hóa L2 sau khi nhận vector.
   - Anchor được embed theo lô, một request mỗi lần compile hoặc sửa.
   - Mỗi giao dịch tốn tối đa 1 lần embed. Cache theo `sha256(model|dim|norm_match(text))` và lưu trong DB.
   - Khi khởi động, seed cache cho tập sạch và các câu demo; chỉ tính phần còn thiếu, và **gửi theo lô 50–100 câu/request** (gói miễn phí chỉ có khoảng 1.000 request/ngày).
3. **Ngưỡng `SEMANTIC_THRESHOLD`:**
   - Hiệu chỉnh **chỉ trên tập dev**, bằng `bench/calibrate.py`: quét 0,60–0,95 với bước 0,01, mỗi ngưỡng in ra tỷ lệ biến thể lừa của dev bật câu hỏi và số mẫu sạch bị khớp.
   - Cách chọn (bao chốt 28/11): lấy **ngưỡng cao nhất mà tỷ lệ bật câu hỏi trên biến thể dev vẫn đạt mức tối đa** của bảng quét. Khớp nhầm còn lại trên tập sạch được chấp nhận vì regression bắt được và khóa Approve; chuyên viên xóa anchor gây nhầm rồi chạy lại. Lý do: với quy tắc cũ (`flagged = 0`) ngưỡng là 0,93 và câu demo chỉ khớp 4/9 lần biên dịch luật HKD trên dev; ở 0,90 khớp 9/9.
   - Kết quả 28/11 (dev, `gemini-3.5-flash-lite`): `SEMANTIC_THRESHOLD = 0,90` (8/9 biến thể, ca còn lại là nội dung trống; 15 cặp luật × mẫu sạch khớp nhầm trên 3.191 cặp), `TRIGRAM_THRESHOLD` theo cùng quy tắc. Ghi vào `config.py` kèm ngày giờ.
   - Bảng quét được giữ lại làm hình phụ lục slide (ABOUT §6.4).
4. **Nội dung ngắn** (`note_norm` dưới 4 ký tự) thì không khớp semantic.
5. **Fallback khi API embedding lỗi:** cosine trên vector trigram ký tự viết bằng Python thuần, với ngưỡng riêng `TRIGRAM_THRESHOLD` cũng hiệu chỉnh trên dev; response gắn `degraded: true`.
6. **Kiểm tra câu demo ngay tối 27/11** bằng `bench/check_demo.py`:
   - In cosine giữa "xac thuc ho so cap nhat thue HKD" (trước và sau khi mở rộng viết tắt) với bộ anchor mẫu của thủ đoạn HKD.
   - Làm tương tự với 3 câu sạch dễ nhầm.
   - Câu demo phải vượt ngưỡng placeholder với biên rõ ràng. Nếu không, sửa chuẩn hóa hoặc anchor ngay trong đêm (ABOUT §8.3).

---

## 9. Lớp đối tác (baseline)

Baseline mô phỏng hệ thống chấm điểm sẵn có của ví đối tác và được dùng cho hai việc:
- Làm **đối chứng** trong benchmark.
- Làm **lớp nền** trong gateway (D9).

```
risk_score = clamp(0, 100,
      30 nếu recipient_is_new
    + 25 nếu amount_vnd ≥ 5.000.000
    + 15 nếu recipient_account_age_days < 30
    + 50 nếu tx_count_10m ≥ 3
    + 60 nếu note_norm chứa từ khóa trong static_scam_keywords.json)
decision = BLOCK nếu account_compromise_flag
         = WARN  nếu risk_score ≥ PARTNER_WARN_SCORE (50)
         = ALLOW còn lại
partner_risk_score = risk_score
as_final = PARTNER_MAP[decision]        # WARN → HOLD_15M, mô phỏng "khoảng dừng giao dịch" của ví
```

- `static_scam_keywords.json` chứa từ khóa của các thủ đoạn **đã biết** (đầu tư, nhận thưởng, làm nhiệm vụ, giả danh công an…) và **không** chứa từ khóa của thủ đoạn HKD 2026. Baseline đại diện cho một hệ thống tốt nhưng chưa biết thủ đoạn mới.
- **Kiểm chứng với kịch bản demo:** giao dịch của chú Hùng là 1,2 triệu, tới `ACC-OLD-7731` (420 ngày tuổi), người nhận mới với ví của chú, không có giao dịch nào khác trong 10 phút. Điểm = 30, nên baseline trả `ALLOW`, đúng kịch bản.
- Cả hai hệ thống được đo bằng **cùng một tập quyết định "được dừng"** (§13.4), nên không còn cách tính "WARN được coi là chặn" chỉ ưu ái riêng baseline như ở v1.

---

## 10. An toàn, bảo mật và các bất biến

| Mã | Bất biến | Cách đảm bảo | Test |
|---|---|---|---|
| INV-01 | Không tác động tiền thật | Không có connector thanh toán; `httpx` chỉ được gọi tới host Gemini | `test_outbound_allowlist` |
| INV-02 | Bằng chứng là dữ liệu không tin cậy | LLM không có tool; trường quyền bị gỡ (V8) | `test_injection_cannot_set_stage_threshold_action` |
| INV-03 | Fail-safe | LLM lỗi thì chuyển fallback; không có code path nào trả "an toàn" | `test_llm_timeout_returns_safe_defaults` |
| INV-04 | Không xác nhận khống | Trạng thái của tổ chức bên ngoài tối đa là `PENDING_EXTERNAL_CONFIRMATION` | `test_no_external_locked_status` |
| INV-05 | Riêng tư | Che PII trước khi gọi LLM; ảnh không ghi đĩa; phiên công khai tự xóa sau 24 giờ | `test_pii_masking`, `test_image_not_persisted` |
| INV-06 | Luật không nhắm vào tài khoản hay cá nhân | V4 | `test_rule_rejects_account_numbers` |
| INV-07 | Hành động do server quyết định | Chỉ lấy từ StagePolicy và mức sàn | `test_action_from_stage_policy_only` |
| INV-08 | Không bỏ qua được challenge; câu trả lời cũ không vượt được khóa mới | Claim nguyên tử, có hạn; kiểm tra lại ví trong cùng transaction | `test_challenge_replay_and_skip_rejected`, `test_challenge_after_compromise_lock_blocked` |
| INV-09 | Cô lập workspace | Mọi query đều lọc theo `workspace_id` | `test_workspace_isolation` |
| INV-10 | Khoanh vùng chỉ nâng, không tự hạ | Merge một chiều | `test_containment_monotonic` |
| INV-11 | Kích hoạt hộ chỉ làm an toàn hơn | Không có đường nào cho người thân chuyển tiền, hạ mức hay xem số dư; ví luôn hiện `protective_hold_notice` | `test_proxy_cannot_downgrade_or_read_balance`, `test_proxy_hold_visible_to_owner` |
| INV-12 | Client không thấy nhãn ý nghĩa | `ChallengeOut` không có `outcome`; submit nhận `option_id` | `test_challenge_out_hides_outcome` |
| INV-13 | ScamRelay không yếu hơn lớp đối tác | `final = max(mức sàn, …)` | `test_final_never_below_partner` |
| INV-14 | Cổng Approve | Regression phải đúng version hiện tại; `flagged > 0` thì cần lý do ghi đè; sửa bản nháp làm hủy regression | `test_approve_locked_when_flagged`, `test_approve_requires_current_regression`, `test_edit_invalidates_regression` |
| INV-15 | Biller đã xác minh không bao giờ bị hỏi | Bỏ qua luật khi `is_verified_biller`; có thêm điều kiện sàn | `test_verified_biller_never_challenged` |
| INV-16 | Cổng `ENFORCE_HOLD` | Chỉ duyệt được từ `ASK_ONLY` và khi `corroboration_count ≥ 2` | `test_enforce_requires_corroboration_and_ask_only` |

**Auth và chống lạm dụng**
- `/ops` và mọi endpoint `/v1/fraudops/*` cần JWT. Tài khoản `judge_01..judge_05` với mật khẩu lấy từ biến môi trường, ghi trong hướng dẫn 1 trang A4. Token hết hạn sau 12 giờ.
- Rate limit cho các endpoint gọi LLM: 10 lần/phút/phiên và 200 lần/ngày/IP.
- Gemini trả 429 hoặc hết quota thì chuyển fallback, gắn `degraded: true` và hiện banner. Đặt budget alert $5 trên GCP và giới hạn chi tiêu Gemini cho project deploy, đủ dùng tới 11/12.
- Biến thể chỉ có dạng `StructuredVariant`. Hệ thống không có endpoint nào sinh đoạn chat lừa đảo hoàn chỉnh.
- Security headers: CSP chặt cho SPA, `X-Content-Type-Options`, `Referrer-Policy`.

**Quyền riêng tư khi dùng Gemini**
- Với gói miễn phí, Google được dùng nội dung gửi lên để cải thiện sản phẩm, và có thể có người đọc duyệt. Mà `/help` là luồng cho người dùng thật dán đoạn chat thật.
- Cần chọn một trong hai cách, **bao chốt trước khi deploy public ngày 28/11**:
  - (Khuyến nghị) Bật billing cho project deploy (Tier 1) và đặt budget alert.
  - Hoặc giữ gói miễn phí, và `/help` hiện thông báo rõ trước khi gửi: *"Nội dung sẽ được xử lý bởi Google Gemini; vui lòng che thông tin cá nhân"*. README và slide ghi đúng như vậy.
- Lớp che PII bằng regex luôn chạy, dù chọn cách nào. Chân trang `/help` có dòng: dành cho người dùng từ 18 tuổi.

**Workspace và Reset**
- Giám khảo đăng nhập thì dùng workspace của tài khoản đó; chưa có thì seed từ `seed_workspace.json`.
- `POST /v1/demo/reset` xóa dữ liệu của workspace rồi seed lại. Nút Reset nằm ở `/ops` và `/wallet`.
- `bench_runner` và `smoke` có workspace riêng.
- Người dùng ẩn danh ở `/help` dùng workspace tạm theo cookie: không có ví, không chuyển hồ sơ.

---

## 11. API

**7 endpoint lõi** (ABOUT §5.2 trừ `export-pack`; gói hồ sơ dựng ở frontend):

| Method & path | Auth | Ghi chú |
|---|---|---|
| `POST /v1/incidents/analyze` | phiên | Chỉ nhận JSON; follow-up qua `incident_id`; `protect_wallet_id` chỉ dùng trong workspace demo; `consent_handoff` |
| `POST /v1/fraudops/rules/compile` | JWT | `{incident_id}` → `RelayRule` (`SHADOW_LOG` hoặc `DRAFT_INVALID`) + `validation` + `source` |
| `POST /v1/fraudops/rules/{id}/regression-test` | JWT | → `RegressionResult` |
| `POST /v1/fraudops/rules/{id}/approve` | JWT | `{stage, ttl_hours, override_reason?}` → luật + đồng hồ 2 mốc |
| `POST /v1/fraudops/rules/{id}/rollback` | JWT | |
| `POST /v1/gateway/evaluate-transfer` | phiên / JWT | `TransferRequest` → `EvaluateResponse` |
| `POST /v1/gateway/submit-challenge` | phiên / JWT | `{challenge_id, option_id}` → `SubmitChallengeResponse` |

**Có thể có:** `GET /v1/fraudops/rules/{id}/stats` · `POST /v1/gateway/feedback`

**Phụ trợ:** `POST /v1/auth/login` · `GET /v1/fraudops/incidents` · `GET /v1/fraudops/rules` · `GET /v1/fraudops/rules/{id}` · `PUT /v1/fraudops/rules/{id}/draft` · `GET /v1/wallets` (kèm `protective_hold_notice`) · `GET /v1/wallets/{id}/transactions` · `POST /v1/demo/reset` · `POST /v1/demo/fast-forward-holds` · `GET /healthz`

**Mã lỗi thống nhất:** `{ "error": { "code": "APPROVE_LOCKED", "message_vi": "...", "details": [...] } }`

---

## 12. Frontend

Một SPA gồm 4 route, giao diện tiếng Việt. `/help` và `/wallet` thiết kế ưu tiên mobile (hiển thị trong khung điện thoại khi xem trên desktop).

| Route | Màn hình và thành phần |
|---|---|
| `/` | Landing: 4 nhân vật, 3 thẻ (Khoanh vùng / Tiếp sức / Chặn đúng), link `/docs`, hướng dẫn 5 bước cho giám khảo |
| `/help` | **Bước 1:**<br>• Ô dán chat; nút tải ảnh (có thể có).<br>• Công tắc "Tôi là người thân kích hoạt hộ".<br>• Khi đã đăng nhập workspace: ô "Yêu cầu tạm giữ bảo vệ ví của…", kèm giải thích người thân được làm gì và không được làm gì.<br>• Thông báo quyền riêng tư.<br>**Bước 2:**<br>• Nhãn chế độ (màu, chữ to); **3 thẻ hành động** với nút lớn (`tel:` hoặc link lấy từ registry).<br>• Ô "Thêm tình tiết".<br>• Nút "Kể 1 lần, dùng mọi nơi": dựng Markdown ở frontend, tải `.md`, in PDF nếu kịp.<br>• **Ô đồng ý chia sẻ** kèm 3 điểm giải thích (chia sẻ gì, để làm gì, lưu bao lâu).<br>• Chân trang ghi dành cho người từ 18 tuổi.<br>Không có đồ thị, không có thuật ngữ kỹ thuật |
| `/ops` | Đăng nhập → **Hàng đợi** (chỉ sự cố đã đồng ý) → **Chi tiết** (tóm tắt, sự kiện có nhãn nguồn gốc, thẻ phạm vi: đã mất / đang bị đòi / lộ OTP) → **Biên dịch**:<br>• Nhãn nguồn: LLM / kết quả đã lưu / luật dựng sẵn.<br>• **Danh sách anchor sửa được** (xóa, thêm).<br>• *Xem trước câu hỏi đúng như chú Hùng sẽ thấy*, kèm dòng chống dặn trước.<br>• Bảng biến thể; `behavior_hints`; cảnh báo của validator.<br>→ **Kiểm thử:** `flagged/checked`, ví dụ khớp nhầm, **anchor gây khớp nhầm được tô đậm**, `triggered/checked` của biến thể; **nút Approve bị khóa** kèm ô lý do ghi đè.<br>→ **Approve:** chọn stage; `ENFORCE_HOLD` bị vô hiệu kèm lý do nếu chưa đủ điều kiện.<br>→ **Đồng hồ 2 mốc** chữ lớn: *"AI: X giây · Con người xem xét: Y giây"*.<br>**Danh sách luật:** stage, TTL đếm ngược, thống kê (nếu kịp), nút Rollback |
| `/wallet` | VietWallet Sandbox, màu trung tính, không dùng nhận diện MoMo:<br>• Chuyển qua lại ví cô Lan / chú Hùng; số dư; **dải thông báo** khi có kích hoạt hộ.<br>• Form chuyển tiền: chọn người nhận seed, số tiền, nội dung.<br>• **Modal câu hỏi mục đích:** 4 phương án, dòng chống dặn trước **luôn hiển thị**.<br>• Màn kết quả riêng cho từng hành động (§7.3), có mã biên lai và nút "Báo nhầm" (có thể có).<br>• Công tắc **"So sánh: Bộ chấm hành vi vs ScamRelay"** hiển thị song song 2 quyết định.<br>• Nút **"Chạy lại giao dịch vừa rồi"**; dải "Luật mới có hiệu lực X phút trước" |

**Quy tắc UX bắt buộc:**
- Mỗi màn hình ở `/help` và `/wallet` chỉ có một hành động chính.
- Khi chờ LLM: hiện skeleton kèm dòng "Đang đọc đoạn chat… (tối đa 30 giây)".
- Lỗi hiển thị bằng tiếng Việt, kèm hướng xử lý an toàn.
- Khi `degraded` thì hiện banner.

---

## 13. Benchmark

### 13.1 Định dạng ca (dev và held-out giống nhau)

```json
{
  "case_id": "H-07",
  "category": "VARIANT_NEW_TACTIC",
  "incident_A": { "text": "…đoạn chat giả lập…", "followups": [] },
  "expected_A": { "mode": "MANIPULATION", "tactic_family": "FAKE_HKD_TAX_VERIFICATION" },
  "transactions_B": [
    { "tx_id": "H-07-1", "from_wallet": "W-HUNG", "to_account_id": "ACC-OLD-7731",
      "amount_vnd": 1200000, "transfer_note": "xac thuc ho so cap nhat thue HKD",
      "label": "SCAM", "is_variant": true,
      "victim_belief_vi": "Tôi đang nộp phí xác minh cho cán bộ thuế để tiệm khỏi bị khóa mã số thuế" },
    { "tx_id": "H-07-2", "from_wallet": "W-HUNG", "to_account_id": "ACC-TAX-GOV",
      "amount_vnd": 300000, "transfer_note": "nop thue mon bai quy 4",
      "label": "LEGIT", "is_variant": false,
      "victim_belief_vi": "Tôi nộp thuế môn bài qua kênh chính thức" }
  ]
}
```

- `category` nhận một trong các giá trị: `VARIANT_NEW_TACTIC`, `RECOVERY`, `OTP`, `COACHED`, `EMPTY_NOTE`, `LEGIT_HARD`.
- `victim_belief_vi` là điều người chuyển tiền tin là thật, **viết bằng lời tự do**. Với ca `COACHED`, ghi cả lời kẻ gian dặn, ví dụ *"người ta dặn chọn chuyển cho người quen"*.
- Ca dev có thể thêm `dev_outcome` (`BENIGN` / `TACTIC_MATCH` / `UNCLEAR`) để chạy tự động. **Held-out không được có trường này.**
- Chỉ dùng id trong §5.2.

### 13.2 Held-out

| Loại ca | Số ca |
|---|---|
| Biến thể thủ đoạn mới, nội dung diễn đạt khác hẳn bản gốc | 4 |
| Lừa "dịch vụ thu hồi tiền" | 1 |
| Lộ OTP / chiếm tài khoản | 1 |
| Nạn nhân bị dặn trước (chọn đáp án lành) | 2 |
| Nội dung chuyển khoản trống hoặc vô hại | 1 |
| Giao dịch hợp lệ dễ nhầm (nộp thuế thật, tiền cọc, hoàn tiền) | 3 |

Bảng trên cho 12 ca; nếu chỉ viết 10 ca thì bớt 1 ca biến thể và 1 ca hợp lệ.

**Quy tắc (giữ tối giản):**
1. quynh viết vào tối 30/11, trên máy riêng, không dùng LLM để sinh ca. File **không commit** cho tới lượt chạy chính thức.
2. bao không xem held-out; chỉ tinh chỉnh prompt và ngưỡng trên dev.
3. Sau freeze 18:00 ngày 01/12: quynh đưa file, chạy **đúng 1 lượt** (§13.3), rồi commit file cùng kết quả.

### 13.3 Runner (`bench/run_bench.py`)

- Runner chạy bằng tài khoản `bench_runner` trên workspace riêng, và gọi **đúng các endpoint thật** (không có nhánh `dry_run`).
- Với mỗi ca:
  1. `reset` → `analyze(A)` với `consent_handoff=true` → `compile` → `regression`.
  2. `approve ASK_ONLY`. Nếu `flagged > 0`, runner duyệt với `override_reason = "bench: ghi đè tự động, xem results"` và **ghi việc này vào kết quả**.
  3. Với mỗi giao dịch B, gọi `evaluate`. Nếu nhận `CHALLENGE_JIT`, chọn phương án theo một trong hai chế độ:
     - **Dev (`--auto`):** chọn phương án có outcome = `dev_outcome`.
     - **Held-out (`--interactive`):** terminal hiện `victim_belief_vi` cùng nhãn chữ của 4 phương án (**không hiện outcome**); **linh** (người không viết ca và không tinh chỉnh prompt) chọn phương án khớp nhất. Challenge hạn 5 phút là đủ.
  4. Gọi `submit-challenge`.
- Quyết định của baseline lấy từ `baseline.as_final` trong response của `evaluate`.
- Mọi lựa chọn được ghi vào `bench/results/heldout_mapping.json` và **công bố ở phụ lục slide**.
- Temperature 0; held-out chạy **1 lượt**.
- Thời gian máy (`ai_seconds`) báo dưới dạng P50/P95, không tính thời gian người.

### 13.4 Chỉ số (luôn ghi dạng x/n cạnh phần trăm)

Tập quyết định "được dừng" **S** = {`HOLD_15M`, `STOP_AND_EXPLAIN`, `HOLD_UNTIL_VERIFIED`, `BLOCK`}, dùng chung cho cả hai hệ thống.

| Chỉ số | Định nghĩa |
|---|---|
| **Unsafe Allow Rate** | Số giao dịch `SCAM` có quyết định cuối ∉ S, chia cho tổng số giao dịch `SCAM`. So baseline (`as_final`) với ScamRelay. Kèm bảng phân rã theo từng loại hành động (`HOLD_15M` chỉ là khoảng dừng, phải ghi rõ) |
| **Legitimate Allow Rate** | Số giao dịch `LEGIT` có quyết định ∈ {`ALLOW`, `ALLOW_WITH_WARNING`}, chia cho tổng `LEGIT`. Đo trên ca khó của held-out (x/n) và trên tập sạch (x/≥200, giả định người dùng sạch chọn `BENIGN`) |
| **Friction Rate** | Tỷ lệ giao dịch sạch **bị hỏi**. Đây là chi phí trải nghiệm thật của lưới rộng |
| **Variant Trigger Rate** | Số giao dịch `is_variant` khớp Lớp 1 (`matched_rule_id ≠ null`), chia cho tổng biến thể. Đo trực tiếp năng lực `SEMANTIC_MATCH`, không phụ thuộc câu trả lời |
| **Time-to-Rule-Activation** | Bench: `ai_seconds` P50/P95. Demo live: đồng hồ 2 mốc |

Báo cáo riêng: các ca `COACHED` (x/2) và `EMPTY_NOTE` (x/1), ghi rõ đây là giới hạn đã biết.

### 13.5 Ablation (có thể có, chỉ làm nếu tối 01/12 còn thời gian)

- Với mỗi ca held-out, **trước khi thấy giao dịch B**, linh viết một luật `CONTAINS_ANY` (≤ 8 cụm) chỉ dựa vào đoạn chat của cô Lan.
- Chạy offline `layer1_match` của luật từ khóa đó trên các giao dịch biến thể, rồi so Variant Trigger Rate với `SEMANTIC_MATCH`.
- Kèm **bảng quét ngưỡng** từ `calibrate.py` (dữ liệu dev).

---

## 14. Deploy và vận hành

### 14.1 Lựa chọn

Cloud Run (`asia-southeast1`) + Neon Postgres (Singapore):
- Cloud Run có 2 triệu request miễn phí mỗi tháng và scale về 0. Neon miễn phí, không cần thẻ.
- Đã loại GitHub Pages (chỉ phục vụ file tĩnh), Hugging Face Docker Space (cần gói trả phí) và Render Free (ngủ sau 15 phút, đĩa không bền). Render chỉ giữ làm phương án dự phòng.
- Cloud Run cần liên kết billing: đặt **budget alert $5** ngay khi tạo project.

### 14.2 Cấu hình Cloud Run

| Thiết lập | Giá trị |
|---|---|
| CPU / RAM | 1 vCPU / 512 MiB |
| `min-instances` | `0` khi dev; `1` từ 03/12 đến 11/12 |
| `max-instances` | `2` |
| `concurrency` / `timeout` | `40` / `60s` |
| Cổng | `8080` (đọc từ biến `PORT`) |

Giảm cold start: dùng `python:3.12-slim`, không cài thư viện ML nặng, khởi tạo client Gemini kiểu lazy, và seed cache embedding vào Postgres (không tính lại mỗi lần khởi động). Landing hiện "Đang khởi động máy chủ…" nếu `/healthz` chậm.

### 14.3 Dockerfile và kết nối Neon

```dockerfile
FROM node:20-slim AS fe
WORKDIR /fe
COPY frontend/ .
RUN npm ci && npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=fe /fe/dist ./static
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
```

```python
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,        # Neon ngủ sau 5 phút sẽ cắt kết nối TCP cũ
    pool_recycle=240,
    pool_size=5, max_overflow=5,
    connect_args={"prepare_threshold": None} if is_postgres else {"check_same_thread": False},
)   # prepare_threshold=None: chạy an toàn qua PgBouncer của Neon (host -pooler)
```

### 14.4 CI và deploy

- `.github/workflows/test.yml`: chạy `pytest` khi push lên `main`, kèm service `postgres:16` cho test race (`TEST_DATABASE_URL`). Workflow này không deploy.
- `scripts/deploy.sh` do **linh** chạy tay, chỉ từ `main`:
  ```bash
  gcloud run deploy scamrelay --source . --region asia-southeast1 --allow-unauthenticated \
    --max-instances=2 --memory=512Mi --timeout=60 \
    --set-secrets=GEMINI_API_KEY=gemini-api-key:latest,DATABASE_URL=database-url:latest,JWT_SECRET=jwt-secret:latest,JUDGE_ACCOUNTS=judge-accounts:latest
  ```
- `scripts/smoke.sh` chạy sau mỗi lần deploy: đăng nhập `smoke` → healthz → analyze (có `consent_handoff`) → compile → regression → approve → evaluate → submit → `reset`.

### 14.5 Biến môi trường

| Biến | Giá trị / ghi chú |
|---|---|
| `GEMINI_API_KEY` | Secret Manager |
| `LLM_MODEL` | `gemini-3.5-flash-lite` (§0) |
| `EMBED_MODEL`, `EMBED_DIM` | `gemini-embedding-001`, `768` |
| `DATABASE_URL` | Neon, **dùng host có hậu tố `-pooler`**, `?sslmode=require`; khi dev: `sqlite:///./dev.db` |
| `JWT_SECRET`, `JUDGE_ACCOUNTS` | Secret Manager; `judge_01:pass1,…` |
| `SEMANTIC_THRESHOLD`, `TRIGRAM_THRESHOLD` | Lấy từ `calibrate.py` (chỉ trên dev) |
| `MIN_ASK_AMOUNT_VND` | `200000` |
| `PARTNER_WARN_SCORE` | `50` |
| `HOLD_MINUTES`, `STOP_COOLDOWN_MINUTES`, `CHALLENGE_TTL_MINUTES` | `15`, `30`, `5` |
| `DEFAULT_RULE_TTL_HOURS`, `PUBLIC_SESSION_TTL_HOURS` | `24`, `24` |

### 14.6 Quota Gemini

- Rate limit tính **theo project**, không theo key. Quota ngày reset lúc nửa đêm giờ Thái Bình Dương (khoảng 14:00–15:00 giờ Việt Nam).
- Với gói miễn phí, `gemini-embedding-001` có khoảng 1.000 request/ngày (cần tự kiểm tra lại trong AI Studio). Các biện pháp:
  1. Cache embedding trong DB và seed sẵn.
  2. Gửi anchor theo lô.
  3. Dùng **project riêng** cho bench và calibrate.
  4. Bật billing cho project deploy (§10).

### 14.7 Vận hành tới 11/12

- `/healthz` kiểm tra DB (đồng thời đánh thức Neon), Gemini (có cache 60 giây) và trạng thái registry.
- Log JSON có `request_id`. Không log nội dung bằng chứng, chỉ log độ dài và hash.
- Neon có point-in-time restore; workspace seed tạo lại được bất cứ lúc nào.
- **Chế độ chung kết:** trước 11/12, reset mọi workspace giám khảo, đặt `min-instances=1`, rồi kiểm tra lại bằng trình duyệt ẩn danh.

---

## 15. Kiểm thử

- **Unit:**
  - Validator V1–V8 (bản v2); `norm` / `norm_match` / mở rộng viết tắt; regex che PII.
  - Assembler (thêm `UNCLEAR`, điều kiện sàn, gỡ trường quyền).
  - `layer1_match`; StagePolicy và `max_severity`; baseline (điểm và quyết định); merge containment.
- **Golden end-to-end** (LLM mock bằng JSON cố định): toàn bộ kịch bản demo chạy trong pytest.
  1. Chú Hùng trước khi có luật → `ALLOW`.
  2. Compile → regression có `flagged > 0` → Approve bị khóa → sửa anchor → regression `0/N` → approve `ASK_ONLY`.
  3. Chú Hùng sau khi có luật → `CHALLENGE_JIT` → `TACTIC_MATCH` → `STOP_AND_EXPLAIN`.
  4. (nếu đã làm dừng mềm) Tạo lại ngay → `STOP_COOLDOWN`.
  5. Giao dịch mua hàng sạch → `ALLOW`; hóa đơn điện của ví đang `MANIPULATION` → qua; sau "lỡ đọc OTP" → `BLOCK`.
- **Bất biến:** mỗi INV-01…16 có ít nhất 1 test (§10).
- **Smoke trên bản public:** `scripts/smoke.sh` (§14.4).

---

## 16. Thứ tự build và danh sách cắt giảm

Lịch chi tiết theo ngày nằm trong `PLAN.md`.

**Cắt theo thứ tự (từ trên xuống) nếu trễ:**
1. Mục "Có thể có" (§1) mặc định chưa làm; chỉ làm khi 30/11 còn dư giờ.
2. Biến thể do LLM sinh → thay bằng 5 biến thể cố định.
3. UI `ENFORCE_HOLD` (giữ trong code và test, chỉ ẩn trên giao diện).
4. Kích hoạt hộ rút gọn thành nhãn trên hồ sơ cộng thông báo trên ví.

**Không bao giờ cắt:** vertical slice; validator; regression với khóa Approve; **sửa anchor** (đây là khoảnh khắc Future Workspace trong demo); StagePolicy cùng mức sàn của lớp đối tác; challenge nguyên tử kèm kiểm tra lại ví; held-out do người khác viết và chạy 1 lần; dự phòng LLM; deploy public; nút Reset; `pytest` trước khi merge.

---

## 17. Giới hạn đã biết (nói trung thực trong slide và Q&A)

1. **Nạn nhân bị dặn chọn đáp án lành:**
   - Ở `ASK_ONLY`, giao dịch sẽ lọt với `ALLOW_WITH_WARNING`, trừ khi lớp đối tác đang `WARN`.
   - Giảm thiểu bằng dòng chống dặn trước, chống dò đáp án (nếu kịp), mức sàn từ `partner_risk_score`, và dừng mềm 30 phút.
   - Đo riêng ở ca `COACHED`.
2. **Nội dung chuyển khoản trống hoặc vô hại:** Lớp 1 không có tín hiệu, nên chỉ còn lớp đối tác. ScamRelay vì vậy là lớp bổ sung, không thay hệ thống chấm điểm.
3. **Ngưỡng sàn 200.000đ:** khoản phí lừa nhỏ hơn mức này không bị hỏi. Đây là đánh đổi để không làm phiền giao dịch nhỏ; giá trị nằm trong config.
4. **"thuế" và "thuê" trùng nhau sau khi bỏ dấu:** xử lý bằng `NOT_CONTAINS_ANY` và regression, nhưng không triệt để.
5. **Sandbox và dữ liệu tổng hợp:** số liệu chứng minh cơ chế, không đại diện cho tỷ lệ ngoài thực tế. Held-out chỉ có 12 ca, tập sạch có ≥ 200 mẫu sinh bằng template.
6. **Ngưỡng hiệu chỉnh trên tập dev nhỏ.**
7. **Phụ thuộc Gemini API:** chất lượng, quota và điều khoản dữ liệu. Có dự phòng output đã lưu và trigram, nhưng chất lượng giảm khi chạy dự phòng.
8. **Duyệt hai người cho `ENFORCE_HOLD`** mới chỉ ghi log trong sandbox, chưa bắt buộc hai người khác nhau.
