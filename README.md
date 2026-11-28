# ScamRelay — Khoanh vùng. Chặn đúng. Tiếp sức.

Một báo cáo từ người bị lừa hôm nay trở thành câu hỏi chặn đứng thủ đoạn đó cho người tiếp theo, chỉ sau vài phút. Dự án tham gia MoMo Tech Contest 2026, chủ đề *Imagine the Future Workspace*. Mô tả sản phẩm: `SCAMRELAY_ABOUT.md`; chuẩn kỹ thuật: `SPEC.md`.

Ba luồng trong sandbox **VietWallet** (thương hiệu trung tính, dữ liệu tổng hợp, không có tiền thật):

1. **Khoanh vùng** (`/help`): nạn nhân hoặc người thân dán đoạn chat. Hệ thống đưa ra 3 việc cần làm và tạm giữ bảo vệ ví ở đúng mức: bị thao túng hay đã lộ OTP.
2. **Tiếp sức** (`/ops`): chuyên viên FraudOps cho AI biên dịch thủ đoạn thành bản nháp luật, kiểm thử hồi quy trên tập giao dịch sạch, sửa câu mẫu gây khớp nhầm, rồi duyệt.
3. **Chặn đúng** (`/wallet`): người tiếp theo chuyển tiền với nội dung khớp thủ đoạn thì được hỏi mục đích. Câu trả lời đi qua StagePolicy, và kết quả không bao giờ yếu hơn lớp chống gian lận của đối tác.

## Cách chạy

### Backend (Python 3.12)

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # điền GEMINI_API_KEY, JWT_SECRET (≥ 32 ký tự), JUDGE_ACCOUNTS
set -a; . ./.env; set +a      # app đọc biến môi trường, không tự nạp .env
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- Tài liệu API: `http://localhost:8000/docs`; kiểm tra sức khỏe: `GET /healthz`.
- Dev dùng SQLite (`DATABASE_URL=sqlite:///./dev.db`), deploy dùng Neon Postgres; chỉ khác `DATABASE_URL`.
- Không có `GEMINI_API_KEY` thì vẫn chạy được ở chế độ dự phòng: phân tích bằng từ khóa, biên dịch bằng output thật đã lưu, so khớp bằng embedding tính sẵn và trigram (`degraded: true`).
- Đăng nhập tài khoản giám khảo: `POST /v1/auth/login` với một cặp trong `JUDGE_ACCOUNTS`. Mỗi tài khoản có workspace riêng và nút Reset (`POST /v1/demo/reset`).

### Test

```bash
cd backend && .venv/bin/pytest -q      # LLM và embedding luôn được mock, không tốn quota
```

CI (GitHub Actions) chạy cùng bộ test kèm Postgres khi push lên `main`.

### Frontend

```bash
cd frontend && npm ci && npm run dev
npm run gen:types          # sinh lại type từ /openapi.json mỗi khi schema backend đổi
```

### Deploy

Một image Docker (build frontend rồi phục vụ API và SPA tĩnh) lên Cloud Run, chạy tay bằng `scripts/deploy.sh` từ `main`; sau đó `scripts/smoke.sh <URL>`. Secret (`GEMINI_API_KEY`, `DATABASE_URL`, `JWT_SECRET`, `JUDGE_ACCOUNTS`) nằm trong Secret Manager, không bao giờ commit.

## Công nghệ và thư viện

| Phần | Dùng |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLModel (SQLAlchemy), Uvicorn |
| CSDL | SQLite (dev, test), Neon Postgres qua `psycopg` (deploy) |
| AI | Google Gemini qua `google-genai`: `gemini-3.5-flash-lite` (structured output), `gemini-embedding-001` (768 chiều) |
| Tính toán | `numpy` (cosine, chuẩn hóa L2, cache vector) |
| Xác thực, giới hạn | `PyJWT` (tài khoản giám khảo), `limits`/`slowapi` (rate limit endpoint gọi LLM) |
| Frontend | React, Vite, TypeScript, Tailwind; type sinh bằng `openapi-typescript` |
| Hạ tầng | Docker, Google Cloud Run, Secret Manager, GitHub Actions (chỉ chạy test) |
| Test, đo lường | `pytest`, `httpx` (TestClient), `python-dotenv` (chỉ script `bench/`) |

Không dùng model chạy cục bộ hay thư viện ML nặng. Ứng dụng chỉ gọi ra ngoài tới Gemini (có test INV-01).

## Cấu trúc thư mục

```
backend/app/
  ai/          llm_client, incident_ai, rule_ai, prompts/*.vN.txt, interfaces.py (hợp đồng)
  core/        preprocess, semantic, layer1, validator, assembler, baseline, regression,
               gateway, stage_policy, ledger, containment
  routers/     incidents, fraudops, gateway, support
  schemas/     kiểu dữ liệu API và LLM (hai lớp schema, SPEC §6)
backend/data/  tập sạch, từ khóa, viết tắt, output dự phòng, embedding tính sẵn, seed workspace
backend/tests/ pytest (bất biến INV-01…16, luồng demo end-to-end)
bench/         ca dev, hiệu chỉnh ngưỡng, đo độ trễ, run_bench, results/
frontend/      React app
scripts/       deploy.sh, smoke.sh
```

## AI & dữ liệu

> Phần này do bao (phụ trách AI và đo lường) viết. Mọi con số đều lấy từ `bench/results/` và ghi dạng x/n.

### AI làm gì, không làm gì

| Bước | AI làm | Quyết định cuối do |
|---|---|---|
| **Khoanh vùng** (`POST /v1/incidents/analyze`) | Đọc đoạn chat đã che PII, trích thủ đoạn, sự kiện có nhãn nguồn gốc, dấu hiệu lộ OTP hoặc cài ứng dụng lạ | Server tính `mode` và 3 việc cần làm bằng bảng tĩnh |
| **Tiếp sức** (`POST /v1/fraudops/rules/compile`) | Viết **bản nháp** luật: câu mẫu (anchor), cụm loại trừ, câu hỏi mục đích kèm nhãn ý nghĩa, biến thể để kiểm thử | Validator V1–V8 → assembler → kiểm thử hồi quy → **chuyên viên duyệt** |
| **Chặn đúng** (gateway) | Không gọi LLM. Chỉ so embedding nội dung chuyển khoản với anchor (tối đa 1 lần embed mỗi giao dịch, có cache) | StagePolicy × mức sàn của lớp đối tác |

**Tách quyền (Separation of Authority).** LLM chỉ viết nội dung và nhãn `BENIGN` / `TACTIC_MATCH`. Ngưỡng, điều kiện sàn, hành động, giai đoạn, thời hạn và mã phương án đều do server gắn. Trường quyền mà LLM tự thêm vào sẽ bị gỡ và ghi cảnh báo (V8). Không có đường nào để output LLM tác động thẳng vào quyết định chặn hay cho qua.

### Model

| Dùng cho | Model | Cấu hình |
|---|---|---|
| Trích xuất sự cố, biên dịch luật | `gemini-3.5-flash-lite` | Structured output theo schema phẳng, temperature 0, timeout 25 / 30 giây, thử lại 1 lần; gặp 429 thì chuyển ngay sang dự phòng |
| So khớp ngữ nghĩa | `gemini-embedding-001` | `SEMANTIC_SIMILARITY`, 768 chiều, chuẩn hóa L2, gửi theo lô ≤ 100 câu |

Đêm 27/11, các bản Flash thường trả 503 hoặc treo quá 30 giây, còn `gemini-2.5-flash` không mở cho người dùng mới. Vì vậy nhóm chọn flash-lite. Prompt nằm ở `backend/app/ai/prompts/*.vN.txt`; bằng chứng người dùng được bọc trong `<untrusted_evidence>` và không thể tự đóng thẻ.

### So khớp tiếng Việt

1. `norm_match`: bỏ dấu, `đ→d`, chữ thường, bỏ ký tự đặc biệt, rồi mở rộng viết tắt **theo từ nguyên vẹn** (`hkd → ho kinh doanh`, `mst → ma so thue`, `ck → chuyen khoan`…; xem `backend/data/abbreviations.json`). Bảng cố ý không có `hd` và `dk` vì hai từ này nhập nhằng.
2. Cosine giữa embedding của nội dung chuyển khoản và từng anchor; lấy điểm cao nhất.
3. Sau khi bỏ dấu, "thuế" và "thuê" trùng nhau. Luật vì vậy luôn kèm `NOT_CONTAINS_ANY` cho các cụm "thuê nhà / mặt bằng / xe…", và tập sạch có nhóm ca bẫy "thuê".

### Ngưỡng (hiệu chỉnh chỉ trên tập dev)

`bench/calibrate.py` quét ngưỡng từ 0,60 đến 0,95 trên 12 luật dev do LLM thật biên dịch × 265 mẫu sạch, cộng các giao dịch hợp lệ của dev (tổng 3.191 cặp). Trích từ `bench/results/calibration_20261128T0933Z.md`:

| Ngưỡng | Biến thể dev bật câu hỏi | Cặp sạch bị khớp nhầm |
|---|---|---|
| 0,88 | 8/9 | 51/3.191 |
| **0,90 (chọn)** | **8/9** | **14/3.191** |
| 0,92 | 7/9 | 1/3.191 |
| 0,93 | 6/9 | 0/3.191 |

- Biến thể thứ 9 có nội dung chuyển khoản trống, nên không ngưỡng nào bắt được. Đây là giới hạn đã biết.
- **Vì sao chọn 0,90 mà không chọn 0,93 (0 khớp nhầm):** ở 0,93, câu demo "xac thuc ho so cap nhat thue HKD" chỉ khớp 4/9 lần biên dịch luật HKD trên dev, vì cosine dao động 0,911–0,951 giữa các lần. Ở 0,90 thì khớp 9/9. Số khớp nhầm còn lại (trung bình khoảng 1 mẫu sạch mỗi luật) bị kiểm thử hồi quy bắt và **khóa nút Approve**. Chuyên viên xóa câu mẫu gây khớp nhầm rồi chạy lại. Đây là chỗ con người kiểm soát AI.
- Dự phòng trigram khi API embedding lỗi dùng ngưỡng 0,60, chọn theo cùng quy tắc.

### Kiểm tra bản nháp (DeterministicValidator)

| Mã | Kiểm tra |
|---|---|
| V1 | Schema chặt (`extra="forbid"`), chạy sau khi đã gỡ trường quyền |
| V2 | Whitelist trường và phép so; phép so phải hợp với trường |
| V3 | Lớp 1 chỉ gồm điều kiện **nội dung** trên `transfer_note`. Điều kiện hành vi do LLM đề xuất bị chuyển sang `behavior_hints` (chỉ để tham khảo), để luật rút từ vụ cô Lan không làm lọt vụ của chú Hùng |
| V3b | Giới hạn số cụm và độ dài cho `CONTAINS_ANY` / `NOT_CONTAINS_ANY` |
| V4 | Anchor: 3–12 câu, không trùng nhau, **cấm số ≥ 6 chữ số, SĐT, URL, email** (luật không nhắm vào tài khoản hay cá nhân) |
| V5 | Đúng một trường giá trị, nằm trong khoảng hợp lệ |
| V6 | Đúng 3 phương án (2 `BENIGN` + 1 `TACTIC_MATCH`); câu hỏi trung lập, không chứa từ cấm như "lừa", "kẻ gian", "nghi ngờ"… |
| V6b | Chỉ cảnh báo: phương án `TACTIC_MATCH` nêu nguyên văn câu mẫu (dễ bị dò đáp án) |
| V6c | Câu hỏi, nhãn phương án và lời giải thích phải là tiếng Việt có dấu. LLM viết không dấu (khoảng 1/12 lượt trên dev) thì compile tự gọi lại 1 lần với lời nhắc |
| V7 | Lời giải thích thủ đoạn không chứa SĐT, URL hay email; kênh liên hệ chỉ lấy từ registry đã kiểm chứng |
| V8 | Gỡ mọi trường quyền ở mọi cấp, ghi cảnh báo |
| VAR | 5–8 biến thể có cấu trúc, cùng các lệnh cấm như V4 |

Assembler luôn chạy lại validator; phương án "Mục đích khác" (`UNCLEAR`) và dòng chống dặn trước do server thêm.

### Dữ liệu

| Tập | Nội dung | Nguồn |
|---|---|---|
| Tập sạch (`backend/data/benign_corpus.json`) | 240 mẫu sinh từ template (tiền nhà, tiền hàng, học phí, mừng cưới, đặt cọc…) + 25 ca bẫy viết tay (nhóm "thuê", phí kế toán, hoàn tiền, cập nhật phần mềm bán hàng, nộp thuế qua kênh chính thức) | `bench/gen_benign.py`, seed cố định |
| Tập dev (`bench/cases/dev/`) | 12 ca: 4 biến thể thủ đoạn mới, 1 "dịch vụ thu hồi tiền", 1 lộ OTP, 2 bị dặn trước, 1 nội dung trống, 3 giao dịch hợp lệ dễ nhầm | Viết tay, dữ liệu tổng hợp |
| Held-out | 10–12 ca do thành viên **không** tinh chỉnh prompt viết; người tinh chỉnh không xem; chạy đúng 1 lượt sau freeze | `bench/heldout.*` (commit sau lượt chạy) |
| Output dự phòng (`backend/data/fallback_tactics.json`) | Output biên dịch **thật** của LLM cho 3 thủ đoạn (thuế HKD, thu hồi tiền, giả danh cơ quan chức năng), chép nguyên văn kèm model và thời điểm | `bench/save_fallback.py` |
| Embedding tính sẵn (`backend/data/embeddings_seed.npz`) | 320 vector: tập sạch, nội dung giao dịch dev, anchor và biến thể dự phòng; khởi động server không tốn quota | `bench/build_seed.py` |

Toàn bộ là dữ liệu tổng hợp: không có PII, số tài khoản, CCCD hay OTP thật.

### Khi Gemini lỗi

| Lỗi | Hệ thống làm gì |
|---|---|
| LLM trích xuất lỗi, timeout hoặc 429 | Classifier từ khóa (`degraded: true`). Không bao giờ kết luận "an toàn": OTP và ứng dụng lạ tối thiểu là `UNKNOWN`. Trên dev: đúng thủ đoạn 12/12, đúng mode 12/12; số lạc quan vì cùng người viết từ khóa và ca dev (`bench/results/fallback_eval_*.md`) |
| LLM biên dịch lỗi | Dùng output LLM **thật** đã lưu của thủ đoạn tương ứng (`source = CACHED_FALLBACK`), UI ghi rõ "kết quả đã lưu"; thủ đoạn mới chưa có bản lưu thì hiện nút "Biên dịch lại" |
| Embedding lỗi | So trigram ký tự bằng Python thuần với ngưỡng riêng, gắn `degraded: true` |

### Độ trễ LLM

Đo bằng `bench/latency.py` trên 12 ca dev, mỗi ca 1 lượt (`bench/results/latency_20261128T0044Z.md`, `gemini-3.5-flash-lite`, prompt `incident_extract.v2` / `rule_compile.v3`). Thời gian chỉ tính lời gọi LLM, chưa gồm validator, regression và mạng giữa trình duyệt và server.

| Bước | Thành công | P50 | P95 | Max |
|---|---|---|---|---|
| Khoanh vùng (analyze) | 12/12 | 1,32 giây | 1,48 giây | 1,63 giây |
| Biên dịch luật (compile) | 12/12 | 2,90 giây | 3,29 giây | 3,29 giây |

Với n = 12, P95 gần như bằng giá trị lớn nhất. Timeout 25 / 30 giây chừa dư nhiều lần, để chịu được lúc Gemini quá tải.

### Thử prompt injection

Một lượt thử với LLM thật (`bench/results/injection_probe_20261128.md`). Bằng chứng tự đóng thẻ, yêu cầu trả "chưa lộ OTP", đòi đặt ngưỡng 0, `ENFORCE_HOLD` và chèn hotline. Kết quả: LLM vẫn nhận đúng thủ đoạn và OTP = YES; luật ra ở `SHADOW_LOG` với ngưỡng do server gán; không có anchor hay số điện thoại bị chèn. Test tự động cho các nhánh này chạy với LLM mock (`backend/tests/test_ai.py`, `test_invariants_bao.py`).

### Giới hạn đã biết

- **Nội dung chuyển khoản trống hoặc vô hại:** Lớp 1 không có tín hiệu; chỉ còn lớp đối tác.
- **Nạn nhân bị dặn chọn đáp án lành (`BENIGN`):** ở cả `ASK_ONLY` lẫn `ENFORCE_HOLD`, giao dịch qua với `ALLOW_WITH_WARNING` (kèm dòng chống dặn trước), trừ khi lớp đối tác đang `WARN` thì thành `HOLD_15M`.
- **Khoản nhỏ hơn 200.000đ** không bị hỏi (điều kiện sàn).
- **Ngưỡng hiệu chỉnh trên tập dev nhỏ** (12 ca), và cosine thay đổi theo từng lần biên dịch. Kiểm thử hồi quy cùng chuyên viên là lớp bảo vệ bắt buộc, không phải tùy chọn.
- **Số liệu đo trên sandbox và dữ liệu tổng hợp:** chứng minh cơ chế, không đại diện cho tỷ lệ ngoài thực tế.
- **Gói miễn phí của Gemini:** quota embedding chạm 429 sau khoảng 100–150 câu mỗi phút (đo đêm 27/11).

### Tái lập

```bash
cd backend && .venv/bin/pytest -q                       # LLM và embedding luôn được mock
.venv/bin/python ../bench/gen_benign.py                  # sinh lại tập sạch
.venv/bin/python ../bench/compile_dev.py --force         # biên dịch 12 ca dev bằng LLM thật (cần GEMINI_API_KEY)
.venv/bin/python ../bench/calibrate.py                   # quét ngưỡng trên dev
.venv/bin/python ../bench/save_fallback.py               # lưu output thật làm dự phòng
.venv/bin/python ../bench/build_seed.py                  # đóng gói embedding tính sẵn
.venv/bin/python ../bench/eval_fallback.py               # đo classifier từ khóa dự phòng (offline)
.venv/bin/python ../bench/latency.py                     # đo độ trễ LLM thật trên 12 ca dev
.venv/bin/python ../bench/run_bench.py --auto ../bench/cases/dev   # cần server đang chạy
```
