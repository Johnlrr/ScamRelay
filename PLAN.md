# ScamRelay — PLAN.md (v3, theo ABOUT v2)

**Thời gian:** 27/11, 22:30 → nộp 03/12 (trước 18:00) → duy trì đến 11/12
**Thành viên:** `bao` (AI, luật, đo lường) · `linh` (API, DB, gateway, deploy) · `quynh` (frontend, held-out, pitch)
**Tài liệu:** `SCAMRELAY_ABOUT.md` (ABOUT), `SPEC.md` v2. Nếu lệch nhau: chi tiết kỹ thuật theo SPEC; phạm vi theo ABOUT §8.1; ai làm gì, khi nào theo PLAN này.

---

## 0. Thay đổi so với PLAN v2

| # | Thay đổi | Ảnh hưởng |
|---|---|---|
| P1 | **Contract Drop dời sang 23:30** và theo schema v2 (`outcome`, StagePolicy, `ChallengeOut` không có outcome, `RelayRule` do server dựng) | linh |
| P2 | Held-out 10–12 ca, quynh viết tối 30/11 trên máy riêng; không mã hóa, không hash | quynh |
| P3 | Việc mới cho linh: StagePolicy + mức sàn của lớp đối tác, sửa bản nháp, khóa Approve, đồng hồ 2 mốc, cờ `consent_handoff`, `protective_hold_notice` trên ví, ánh xạ câu trả lời held-out | linh |
| P4 | Việc mới cho bao: chuẩn hóa viết tắt, **kiểm tra câu demo ngay đêm nay**, `layer1_match` dùng chung, assembler, tập sạch ≥ 200 mẫu, quy khớp nhầm về anchor, lưu output thật của 3 thủ đoạn mẫu làm dự phòng | bao |
| P5 | Gói hồ sơ vẫn dựng ở frontend (Markdown + Blob), không có endpoint | quynh |
| P6 | **Giữ nguyên phân vai của PLAN v2** (validator, baseline, regression thuộc bao) dù ABOUT §8.2 giao các việc này cho Member 2. Lý do: validator đã viết xong tối 27/11; regression và baseline gắn chặt với semantic và benchmark; Member 2 trong ABOUT đang quá tải | ABOUT §8.2 cần sửa cho khớp trước khi làm slide |
| P7 | `preprocess.py` và `validator.py` viết tối 27/11 theo SPEC v1 **cần cập nhật lên v2** (bao, tối nay) | bao |
| P8 | **Cắt cho hackathon (27/11, 23:20):** bỏ mã hóa và hash held-out; bỏ bảng `notification`, endpoint `consent` + xóa theo TTL, endpoint export-pack; dự phòng còn 2 tầng; dừng mềm 30 phút, bảng theo dõi, "Báo nhầm", chống dò đáp án, ablation chỉ làm nếu 30/11 dư giờ; Contract Drop nới tới 00:30 | cả nhóm |

---

## 1. Bốn nguyên tắc

1. **Chốt hợp đồng trước 00:30 đêm nay (muộn nhất sáng sớm 28/11), rồi ai làm việc nấy.** Sau mốc đó không ai phải chờ ai.
2. **Xong việc nào, merge việc đó.** Không có giờ gộp cố định, không chờ review.
3. **`main` luôn chạy được:** `pytest` phải xanh trước khi merge. Đó là luật duy nhất về chất lượng.
4. **Cắt mọi thứ không xuất hiện trong demo 3 phút hay phần hỏi đáp** (§8).

---

## 2. Git (tối giản)

```
main ──┬── bao
       ├── linh
       └── quynh        (mỗi người một nhánh, đều tách từ main)
```

```bash
# Ít nhất 2 lần/ngày, và luôn làm trước khi merge vào main
git checkout <ten-minh> && git fetch origin && git merge origin/main

# Khi một việc nhỏ đã chạy ổn
cd backend && pytest -q                    # phải xanh
git checkout main && git pull && git merge <ten-minh> && git push
git checkout <ten-minh>
# nhắn nhóm: "đã merge: <việc gì>"
```

- **Không `push --force`, không `rebase`** nhánh đã push.
- **File hợp đồng** (`backend/app/schemas/**`, `backend/app/ai/interfaces.py`, `backend/data/seed_workspace.json`): muốn sửa thì **nhắn nhóm trước khi merge**. Ưu tiên chỉ thêm trường tùy chọn; với seed thì chỉ thêm id, không đổi hay xóa id cũ.
- **CI duy nhất:** GitHub Actions chạy `pytest` (kèm Postgres service) khi push lên `main`. Ai merge làm đỏ `main` thì người đó sửa ngay.
- **Deploy:** chỉ **linh**, chỉ từ `main`, bằng `scripts/deploy.sh`.

---

## 3. Phân vai và sở hữu file

| Người | Sở hữu | Tóm tắt |
|---|---|---|
| **bao** | `backend/app/ai/**` (trừ `interfaces.py`), `core/{preprocess,semantic,layer1,validator,assembler,baseline,regression}.py`, `backend/data/{abbreviations,benign_corpus,static_scam_keywords,fallback_tactics}.json`, `bench/**` (trừ `heldout.*`) | *AI, luật, đo lường:* prompt, chuẩn hóa, embedding, validator, Lớp 1, tập sạch, baseline, ngưỡng, benchmark, ablation |
| **linh** | `main.py`, `config.py`, `db.py`, `models.py`, `routers/**`, `core/{gateway,stage_policy,ledger,containment,stats}.py`, `schemas/**`, `ai/interfaces.py`, `data/seed_workspace.json`, `Dockerfile`, `scripts/**`, `.github/**` | *API, DB, auth, gateway, deploy, vận hành.* Ngày chạy held-out: **ánh xạ câu trả lời** |
| **quynh** | `frontend/**`, `backend/data/action_registry.json`, `bench/heldout.*`, `docs/**` | *Giao diện, held-out, slide, hướng dẫn A4.* Quay video cùng bao |

`README.md`: linh giữ khung; bao viết mục AI và dữ liệu; quynh viết mục hướng dẫn dùng.

---

## 4. Contract Drop v2 — linh, xong trước **00:30 đêm nay** (muộn nhất sáng sớm 28/11)

Commit lên `main` đúng 4 thứ:

1. **`backend/app/schemas/`** theo SPEC §6:
   - `incident.py`.
   - `rule.py`: `Condition`, `RelayRuleDraft`, `RuleOption`, `RelayRule`, `ValidationResult` (**có `warnings`**), `RegressionResult`.
   - `gateway.py`: `Decision`, `TransferRequest`, `ChallengeOut` **không có `outcome`**, `EvaluateResponse`, `SubmitChallengeRequest/Response`.
   - `llm_*.py`.
2. **`backend/app/ai/interfaces.py`**: chữ ký hàm bên dưới, thân hàm trả fixture.
3. **`backend/data/seed_workspace.json`** đúng danh sách id ở SPEC §5.2.
4. **FastAPI chạy được với 4 route lõi trả JSON cứng theo hình dạng v2**: `analyze`, `compile`, `evaluate-transfer`, `submit-challenge`. Kèm `core/stage_policy.py` (bảng `STAGE_POLICY`, `SEVERITY`, `max_severity`), vì cả frontend lẫn test đều cần.

```python
# interfaces.py (hợp đồng). Kiểu dữ liệu: SPEC §6.4
async def analyze_incident(masked_text: str, image_b64: str | None,
                           otp_mentioned: bool, history: list[IncidentAnalysis]) -> AnalyzeResult
async def compile_rule(analysis: IncidentAnalysis) -> CompileResult      # raw dict + source
class SemanticMatcher(Protocol):
    async def prepare_anchors(self, anchors: list[str]) -> AnchorSet
    async def score(self, note_norm: str, anchors: AnchorSet) -> float | None
class EmbeddingCache(Protocol):                                          # linh cài trên DB
    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]
    def put_many(self, items: dict[str, np.ndarray]) -> None
# bao cài (core/), linh gọi:
def validate_llm_output(raw: dict) -> ValidationResult
def assemble_rule(draft: RelayRuleDraft, *, rule_id: str, version: int,
                  source_incident_id: str, ttl_hours: int) -> RelayRule
def baseline_score(tx: DerivedTx) -> BaselineResult
def layer1_match(rule: RelayRule, tx: DerivedTx, anchors: AnchorSet) -> float | None
async def run_regression(rule: RelayRule, anchors: AnchorSet) -> RegressionResult
```

Các màn `/ops` còn lại (danh sách, sửa bản nháp, regression, approve, rollback) thì **quynh dùng mock JSON** cho đến khi linh có route thật.

---

## 5. Mốc

| Mốc | Khi nào | Đạt khi |
|---|---|---|
| **Contract Drop v2** | 28/11, 00:30 (muộn nhất sáng sớm) | §4 đã lên `main` |
| **Kiểm tra câu demo** | 27/11, trước khi ngủ | `check_demo.py` cho thấy "xac thuc ho so cap nhat thue HKD" vượt ngưỡng placeholder với biên rõ (SPEC §8.6) |
| **M1 – Vertical slice public** | 28/11, 21:00 | URL Cloud Run chạy được: chat cô Lan → compile → validator → regression → approve `ASK_ONLY` → chú Hùng bị hỏi → `TACTIC_MATCH` → `STOP_AND_EXPLAIN`; chọn `BENIGN` → `ALLOW_WITH_WARNING`. UI ví tối thiểu |
| **M2 – Đủ 3 luồng** | 29/11, 21:00 | `/help`, `/ops` (sửa anchor, khóa Approve, đồng hồ 2 mốc, rollback), `/wallet` (so sánh, chạy lại) nối API thật; semantic thật; tập sạch ≥ 200; ngưỡng đã hiệu chỉnh |
| **M3 – Đủ tính năng** | 30/11, 22:00 | Kích hoạt hộ đủ giới hạn, nâng khóa khi lộ OTP, gói hồ sơ `.md`, ô đồng ý chia sẻ, rate limit, test INV, output dự phòng đã lưu; đã deploy; quynh viết xong held-out |
| **Freeze** | 01/12, 18:00 | Chỉ còn sửa lỗi; 18:30 chạy held-out (§9) |
| **Nộp** | 03/12, trước 18:00 | Đủ 4 thành phần |

---

## 6. Việc theo ngày

### 27/11 (từ 22:30)

| bao | linh | quynh |
|---|---|---|
| Tạo **2 project Gemini** (deploy và bench), lấy key, chọn model Flash ổn định. **Chốt chuyện bật billing** cho project deploy (SPEC §10) | **Contract Drop v2 trước 00:30** (§4) | Khởi tạo Vite + React + TS + Tailwind, router 4 trang, nhận diện VietWallet trung tính |
| Cập nhật `preprocess.py` lên v2: `norm_match` + `abbreviations.json`, kèm test | Sau Contract Drop: `models.py`, `db.py` (SQLite trước; Neon để mai) | `/wallet` bằng mock: form chuyển tiền, **modal 4 phương án có dòng chống dặn trước**, màn kết quả cho 6 loại hành động |
| Cập nhật `validator.py` lên v2: `outcome`, 3 phương án, nhãn ≤ 100 ký tự, `tactic_alert_vi`, V6b, trường mới, `validate_llm_output(dict)`, kèm test | Seed workspace, `reset` | |
| **`bench/check_demo.py`**: embed câu demo và 3 câu sạch dễ nhầm với anchor HKD mẫu, in cosine. Không đạt thì sửa chuẩn hóa ngay | | `npm run gen:types` sau Contract Drop |

### 28/11

| bao | linh | quynh |
|---|---|---|
| **Sáng:** `llm_client.py` (structured output, timeout, **429 → fallback**), `semantic.py` (embedding 768 chiều, L2, cache, trigram), `layer1.py`, `assembler.py`, `baseline.py` + `static_scam_keywords.json` | Auth JWT + workspace (`judge_01..05`, `bench_runner`, `smoke`) | **Sáng:** hoàn thiện `/wallet` bằng mock (6 màn kết quả, công tắc so sánh); landing tối thiểu |
| **Chiều:** prompt `analyze_incident` và `compile_rule` (`<untrusted_evidence>`), `fallback_tactics.json` (3 thủ đoạn: từ khóa cho analyze + output compile thật đã lưu), **12 ca dev** (có `dev_outcome`) | Gateway: `evaluate` (lớp đối tác → khoanh vùng → layer1 → challenge), `submit` (**claim nguyên tử + kiểm tra lại ví**, StagePolicy, `max_severity`), ledger, receipt | **Chiều:** `/help` bước 1 và 2 bằng mock (nhãn chế độ, 3 thẻ, công tắc người thân, ô tạm giữ bảo vệ, **ô đồng ý chia sẻ**) |
| | Containment (`MANIPULATION` → `HOLD_UNTIL_VERIFIED`, `COMPROMISE` → `BLOCK`, chỉ nâng); `protective_hold_notice` trong `GET /v1/wallets`; cờ `consent_handoff` | **Điền `action_registry.json`** (≤ 45 phút): 4–5 hotline và link chính thức, có `source_url` và `verified_at` |
| | **Chiều:** GCP + Neon + Secret Manager + budget alert, `scripts/deploy.sh`, deploy lần đầu | |
| **18:00–21:00:** ghép M1 cùng nhóm | **18:00–21:00:** ghép M1, deploy | **18:00–21:00:** nối `/wallet` vào API thật |

### 29/11

| bao | linh | quynh |
|---|---|---|
| `regression.py` (flagged/checked, `flags_by_anchor`, biến thể) | Route `/ops`: danh sách sự cố, `GET rule`, **`PUT draft`** (validator, version, hủy regression), `regression-test`, **`approve`** (khóa khi flagged, override, cổng `ENFORCE_HOLD`, **đồng hồ 2 mốc**), `rollback`, hết hạn lazy | `/ops` đầy đủ: đăng nhập, hàng đợi, chi tiết, biên dịch (**sửa anchor**, xem trước câu hỏi như chú Hùng thấy, nhãn nguồn), thẻ kiểm thử (**tô anchor gây khớp nhầm**, Approve bị khóa, ô lý do ghi đè), Approve, **đồng hồ 2 mốc**, danh sách luật + Rollback |
| `bench/gen_benign.py` → **≥ 200 mẫu + ≥ 20 ca bẫy** (bắt buộc nhóm "thuê"); seed cache embedding (theo lô 50–100 câu/request) | Hỗ trợ quynh nối `/ops`; sửa lỗi M1 | `/wallet`: công tắc so sánh baseline vs ScamRelay, nút "Chạy lại giao dịch", dải "Luật có hiệu lực X phút trước", dải thông báo kích hoạt hộ |
| `bench/calibrate.py` (quét ngưỡng trên dev) → `SEMANTIC_THRESHOLD`; tinh chỉnh prompt trên dev | Rate limit (`slowapi`); CI `pytest` + Postgres service | Landing `/` (4 nhân vật, hướng dẫn 5 bước) |
| `bench/run_bench.py` (`--auto` cho dev, `--interactive` cho held-out); lưu **output thật** của 3 thủ đoạn mẫu vào `fallback_tactics.json` | | |

### 30/11

| bao | linh | quynh |
|---|---|---|
| Test prompt injection; kiểm tra các nhánh degraded (LLM lỗi, embedding lỗi, 429) | Nếu dư giờ: dừng mềm 30 phút, thống kê luật + `feedback`, chống dò đáp án | `/help`: người thân, "Thêm tình tiết", gói hồ sơ `.md` (dựng ở frontend), ô đồng ý chia sẻ, thông báo quyền riêng tư, dòng 18+ |
| Chạy bench dev để thử toàn bộ pipeline đo | Test INV 02, 04, 06, 07, 08, 10–16; `/healthz` | Trạng thái chờ và lỗi, banner degraded, responsive mobile |
| Chạy thử mọi câu trong kịch bản demo trên bản deploy; prompt ảnh (có thể có) | Deploy bản đủ tính năng; giới hạn chi tiêu Gemini đủ dùng tới 11/12 | **Tối: viết 10–12 ca held-out** (SPEC §13.2) trên máy riêng, không commit |

### 01/12 — Freeze

| Giờ | Việc |
|---|---|
| 09:00–12:00 | **Bug bash chéo** trên URL public: bao thử `/ops`, linh thử `/help`, quynh thử `/docs` và các ca biên |
| 12:00–18:00 | Sửa lỗi phần mình |
| **18:00** | **FREEZE**. Từ đây chỉ hotfix khi cả 3 đồng ý |
| 18:30 | Chạy held-out theo §9 |
| Tối | bao viết slide AI và số liệu; linh viết slide kiến trúc và an toàn; quynh dựng bản nháp 10 slide |

### 02/12

| bao | linh | quynh |
|---|---|---|
| Kiểm chứng mọi số liệu theo **ABOUT Phụ lục B** (mở bản gốc; chưa xác minh được thì xóa) | README (cách chạy, công nghệ, thư viện, tài sản có sẵn); thử bằng trình duyệt ẩn danh; `min-instances=1` | **Slide PDF ≤ 10 trang** (không sửa được sau khi nộp) |
| README mục AI và dữ liệu (có danh sách công cụ AI đã dùng); **quay video cùng quynh** | Hỗ trợ quay video; sửa ABOUT §8.2 cho khớp phân vai | **Video ≤ 3 phút** trên bản live; **hướng dẫn 1 trang A4** (URL, tài khoản giám khảo, 5 bước) |

### 03/12
- Sáng: rà chéo (bao xem slide, linh xem video, quynh xem zip và hướng dẫn).
- linh đóng gói `.zip` (không có `.env`, không có key).
- **quynh nộp trước 18:00**; bao và linh xác nhận.

### 04/12 → 11/12: trực vận hành
Không thêm tính năng. Xoay vòng **bao (04, 07, 10) · linh (05, 08, 11) · quynh (06, 09)**: mở URL bằng trình duyệt ẩn danh, chạy thử luồng demo, đăng nhập một tài khoản giám khảo, xem log, quota Gemini và chi phí GCP. Tối 10/12 cả nhóm diễn tập demo chung kết, reset workspace và đặt `min-instances=1`.

---

## 7. Phụ thuộc còn lại

```
Contract Drop v2 + seed ids (linh, 00:30 28/11) ─► cả 3 làm song song
check_demo (bao, đêm 27/11) ─► nếu không đạt thì sửa chuẩn hóa trước khi viết prompt compile
layer1_match / assembler / baseline (bao, 28/11) ─► gateway của linh; trước khi bao merge thì linh dùng stub
regression.py (bao, 29/11) ─► route regression-test + khóa Approve (linh)
calibrate (bao, 29/11) ─► SEMANTIC_THRESHOLD vào config
output dự phòng đã lưu (bao, 29/11) ─► demo không chết khi LLM lỗi; kịch bản video (02/12)
```
**Nếu linh trễ M1:** bao nhận phần route `/ops`, vì phía sau là `regression.py` và `assembler.py` của bao.

---

## 8. Phạm vi và cắt giảm

**Ưu tiên** (theo ABOUT §8.1, kèm người làm):

| Mức | Hạng mục |
|---|---|
| **Bắt buộc có** | Vòng lặp xuyên suốt: chat cô Lan → biên dịch → regression → **sửa** → Approve → câu hỏi cho chú Hùng → StagePolicy → quyết định (cả 3 người). FraudOps có Approve và Rollback (linh, quynh). VietWallet trước/sau (quynh). `/docs` (linh). `run_bench.py` (bao). Deploy ổn định kèm dự phòng không phụ thuộc LLM (linh, bao) |
| **Nên có** | Kích hoạt hộ đủ giới hạn, nâng khóa khi lộ OTP (linh, quynh). Gói hồ sơ `.md` ở frontend (quynh). `ALLOW_WITH_WARNING` |
| **Có thể có** (chỉ làm nếu 30/11 dư giờ) | Dừng mềm 30 phút. Bảng theo dõi luật + "Báo nhầm". Ablation từ khóa. Chống dò đáp án. PDF. Đọc ảnh. Biến thể do LLM sinh (5 biến thể cố định là đủ) |

**Nếu trễ, cắt theo thứ tự:** biến thể LLM → UI `ENFORCE_HOLD` → kích hoạt hộ rút gọn thành một nhãn kèm thông báo trên ví.

**Không bao giờ cắt:** M1 public; validator; regression với khóa Approve; **sửa anchor**; StagePolicy cùng mức sàn của lớp đối tác; challenge nguyên tử kèm kiểm tra lại ví; held-out do người khác viết và chạy 1 lần; dự phòng LLM; nút Reset; `pytest` trước khi merge.

**Vẫn giữ nguyên quyết định cắt từ trước:**

| Đã cắt | Thay bằng |
|---|---|
| `usage_counter`, `DAILY_*_CAP` | Bắt lỗi 429 → fallback + banner; budget alert và giới hạn chi tiêu |
| Endpoint `unlock` | Nút Reset (bản thật: chủ ví xác minh qua kênh chính thức) |
| Endpoint và UI `merge-incident` | `corroboration_count` tính tự động từ các sự cố cùng thủ đoạn (SPEC §5.2) |
| `REGISTRY_STRICT` | Điền đủ registry ngày 28/11; mục chưa kiểm chứng bị ẩn số gọi và link |
| CI/CD deploy tự động, WIF, nightly smoke | `scripts/deploy.sh` chạy tay; CI chỉ chạy `pytest`; trực tay mỗi ngày |
| Jinja2, render PDF ở server | Prompt dạng `.txt` + `string.Template`; export Markdown; PDF do trình duyệt in |
| Chế độ semantic B, chạy bench 3 lượt | Chế độ A cố định + mở rộng viết tắt; held-out chạy 1 lượt, temperature 0 |
| Mã hóa GPG + hash held-out, khóa held-out sáng 28/11 | quynh giữ file trên máy riêng tới lượt chạy; bao không xem |
| Bảng `notification` | `protective_hold_notice` đọc từ `containment_policy`, trả trong `GET /v1/wallets` |
| Endpoint `consent` + xóa theo TTL | Cờ `consent_handoff` trong `analyze`; dữ liệu demo xóa khi Reset |
| Endpoint export-pack | Frontend dựng Markdown, tải bằng Blob |
| Dự phòng 3 tầng | 2 tầng: LLM → output thật đã lưu của 3 thủ đoạn mẫu |

---

## 9. Quy trình chạy held-out (01/12, 18:30, cả nhóm cùng ngồi)

1. Bản deploy đang chạy đúng code đã freeze.
2. quynh chép `heldout.json` vào `bench/`.
3. bao chạy `python bench/run_bench.py --split heldout --interactive` trên URL public, bằng tài khoản `bench_runner`.
4. **linh ngồi trước terminal:** mỗi khi câu hỏi bật lên, đọc `victim_belief_vi` và chọn phương án khớp nhất (terminal không hiện nhãn ý nghĩa). Lựa chọn tự lưu vào `heldout_mapping.json`.
5. Commit `bench/heldout.json` (dùng `git add -f`, vì `.gitignore` chặn file này để tránh lỡ commit sớm), `bench/results/heldout_*.json`, `heldout_mapping.json` và bảng Markdown cho slide. **Không sửa prompt hay ngưỡng sau bước này**; kết quả xấu thì báo cáo trung thực dạng x/n kèm phân tích ca bỏ lọt.
