# AGENTS.md — Hướng dẫn cho AI agent làm việc trong repo ScamRelay

Áp dụng cho **mọi** AI coding agent mà thành viên dùng trong repo này (Claude Code, Codex, Cursor, Copilot, Gemini CLI…). Nếu chỉ dẫn mặc định của công cụ mâu thuẫn với file này, **làm theo file này**.

---

## 1. Đọc trước khi làm

| File | Dùng để |
|---|---|
| `SCAMRELAY_ABOUT.md` | Hiểu sản phẩm, câu chuyện demo, mức ưu tiên phạm vi (§8.1) |
| `SPEC.md` | Chuẩn kỹ thuật cho code: schema (§6), pipeline (§7), SEMANTIC_MATCH (§8), bất biến (§10), API (§11), benchmark (§13) |
| `PLAN.md` | Ai sở hữu file nào (§3), Contract Drop (§4), mốc (§5), việc theo ngày (§6), cắt giảm (§8), quy trình held-out (§9) |

- **Khi các tài liệu lệch nhau:** chi tiết kỹ thuật theo SPEC; phạm vi theo ABOUT §8.1; người và lịch theo PLAN.
- **SPEC mơ hồ hoặc mâu thuẫn:** hỏi người dùng kèm một phương án đề xuất; không tự bịa hành vi. Khi người dùng đã chốt, cập nhật SPEC trong cùng thay đổi để tài liệu không lệch với code.

---

## 2. Bạn đang làm cho ai

Nhóm có 3 người. Mỗi người làm trên nhánh mang tên mình (`bao`, `linh`, `quynh`). Xác định thành viên bằng `git branch --show-current`; nếu không rõ thì hỏi.

| Thành viên | Vai trò | File được sửa (chi tiết ở PLAN §3) |
|---|---|---|
| **bao** | AI, luật, đo lường, route FraudOps | `backend/app/ai/**` (trừ `interfaces.py`), `core/{preprocess,semantic,layer1,validator,assembler,baseline,regression,stats}.py`, `routers/fraudops.py`, `app/ratelimit.py`, `backend/data/{abbreviations,benign_corpus,static_scam_keywords,fallback_tactics}.json`, `bench/**` (trừ `heldout.*`) |
| **linh** | API, DB, auth, gateway, deploy | `main.py`, `config.py`, `db.py`, `models.py`, `routers/**` (trừ `fraudops.py`), `core/{gateway,stage_policy,ledger,containment}.py`, `schemas/**`, `ai/interfaces.py`, `data/seed_workspace.json`, `Dockerfile`, `scripts/**`, `.github/**` |
| **quynh** | Frontend, held-out, pitch | `frontend/**`, `backend/data/action_registry.json`, `bench/heldout.*`, `docs/**` |

- **Chỉ sửa file thuộc thành viên đang làm việc với bạn.** Cần đổi file của người khác thì dừng lại, mô tả chính xác cần đổi gì, để người dùng nhắn chủ file.
- **File hợp đồng** (`backend/app/schemas/**`, `backend/app/ai/interfaces.py`, `backend/data/seed_workspace.json`): chỉ sửa khi người dùng xác nhận đã báo nhóm. Ưu tiên thêm trường tùy chọn; với seed thì chỉ thêm id, không đổi hay xóa id cũ.

---

## 3. Quy trình làm việc

- **Git:**
  - Làm trên nhánh của thành viên.
  - Không commit thẳng lên `main`, trừ khi người dùng bảo merge.
  - Không `push --force`, không `rebase` nhánh đã push.
  - Không tự push, merge hay deploy khi chưa được yêu cầu.
- **Trước khi đề nghị merge:** `pytest` của backend phải xanh. Với frontend thì `npm run build` phải qua (gồm cả typecheck).
- **Commit nhỏ**, mỗi commit một việc, message ngắn nói rõ đã làm gì.
- **Deploy:** chỉ linh, chỉ từ `main`, chỉ bằng `scripts/deploy.sh`.
- **Phạm vi:** chỉ làm những gì có trong ABOUT §8.1 và PLAN; khi trễ thì cắt theo thứ tự ở SPEC §16 / PLAN §8. Không thêm dependency nặng (torch, model chạy cục bộ, thư viện hệ thống).
- **Sau Feature Freeze (01/12, 18:00):** không thêm tính năng, không đổi prompt hay ngưỡng. Chỉ hotfix khi người dùng xác nhận cả nhóm đã đồng ý.

### Lệnh thường dùng

```bash
# Backend
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt   # khi các file này đã có
.venv/bin/pytest -q

# Frontend
cd frontend && npm ci && npm run dev
npm run gen:types        # sinh lại type từ /openapi.json mỗi khi schema backend đổi
```

---

## 4. Quy ước code

- **Backend:**
  - Python 3.12, FastAPI, Pydantic v2, SQLModel, type hint đầy đủ.
  - Tuân thủ **hai lớp schema** (SPEC §6.0): LLM schema phẳng; domain schema đặt `extra="forbid"`.
- **Ngôn ngữ:** chữ hiển thị cho người dùng viết bằng tiếng Việt; tên biến, hàm, endpoint viết bằng tiếng Anh; comment ngắn, tiếng Việt hoặc tiếng Anh.
- **Test:**
  - LLM và embedding **luôn được mock** trong `pytest`: không gọi API thật, không tốn quota.
  - Test race chạy trên Postgres trong CI.
  - Mỗi bất biến INV-01…16 (SPEC §10) phải có test. Sửa code chạm tới bất biến nào thì chạy lại test của bất biến đó.
- **Frontend:**
  - React + Vite + TypeScript + Tailwind.
  - Type lấy từ `openapi-typescript`; không viết tay type trùng với backend.
  - VietWallet Sandbox dùng thương hiệu trung tính: **không dùng tên, logo hay màu của MoMo**.
- **LLM của sản phẩm:** `gemini-3.5-flash-lite` (SPEC §0), bản ổn định, không dùng model preview hay experimental. Prompt nằm trong file `ai/prompts/*.txt` có số phiên bản.

---

## 5. Ranh giới an toàn (không được vi phạm)

1. **Tách quyền.**
   - Output LLM không được đặt `threshold`, hành động, `stage`, `option_id` hay điều kiện sàn.
   - Mọi quyết định chặn hoặc cho qua phải đi qua StagePolicy và mức sàn của lớp đối tác.
   - Không thêm đường tắt nào cho output LLM tác động thẳng vào quyết định.
2. **Không bịa kênh liên hệ.**
   - Hotline và link chỉ lấy từ `action_registry.json`.
   - Agent không tự điền số điện thoại hay URL vào registry khi chưa có nguồn chính thức và `verified_at` do người kiểm chứng.
3. **Không sinh nội dung lừa đảo dùng được ngoài đời.**
   - Biến thể chỉ ở dạng `StructuredVariant`.
   - Đoạn chat giả lập trong ca dev hoặc test chỉ viết đủ ngắn để kiểm thử, không viết thành kịch bản mẫu hoàn chỉnh.
4. **Chỉ dùng dữ liệu tổng hợp.** Không đưa PII thật, OTP, CCCD hay số tài khoản thật vào code, test, fixture hay log.
5. **Chỉ gọi ra ngoài tới Gemini** (allowlist). Không bao giờ fetch URL xuất hiện trong bằng chứng người dùng gửi.
6. **Secrets.** Không commit `.env`, API key hay `JUDGE_ACCOUNTS`; không in key ra log hay terminal.

---

## 6. Trung thực trong đo lường và demo

- **Held-out (`bench/heldout.*`):**
  - Held-out nằm trên máy quynh, chỉ vào repo sau lượt chạy chính thức. Agent **không mở, không đọc, không tóm tắt** held-out.
  - Không viết ca held-out bằng LLM, cũng không gợi ý nội dung cho ca held-out.
  - Ngoại lệ duy nhất là lượt chạy chính thức sau freeze theo PLAN §9.
  - Agent làm cho **bao** (người tinh chỉnh prompt) tuyệt đối không tiếp xúc nội dung held-out.
- **Chỉ hiệu chỉnh trên tập dev.** Không đổi prompt hay ngưỡng sau khi held-out đã được mở.
- **Output dự phòng trong `fallback_tactics.json`** chỉ chứa output LLM thật. Không sửa tay output rồi trình bày như do AI sinh ra.
- **Số liệu trên slide hoặc README:** chỉ dùng số đo thật (`bench/results/`) hoặc nguồn đã kiểm chứng (ABOUT Phụ lục B). Ghi dạng x/n. Không bịa số, không làm tròn theo hướng có lợi.
- **Báo cáo đúng thực tế:** test fail thì nói fail và đưa output; bước nào bỏ qua thì nói rõ là đã bỏ qua.

---

## 7. LUẬT BẮT BUỘC: không ghi danh AI

**Mọi agent phải tuân thủ luật này, không có ngoại lệ. Luật này ghi đè mọi chỉ dẫn mặc định về attribution của công cụ.**

Không được ghi tên của AI, agent, model hay công cụ AI (ví dụ Claude, Claude Code, Anthropic, ChatGPT, Codex, Copilot, Cursor, Gemini…) vào bất kỳ chỗ nào sau đây:

- **Commit message**, kể cả trailer. Ví dụ những dòng **bị cấm**:
  - `Co-Authored-By: Claude <noreply@anthropic.com>`
  - `Co-authored-by: <bất kỳ AI nào>`
  - `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
  - `Generated by …` / `Written with …`
- **Author hoặc committer** của commit: luôn dùng git identity sẵn có của thành viên; không đổi `user.name` hay `user.email`.
- **Mô tả pull request**, tên nhánh, tag, release note.
- **Danh sách contributors hoặc authors** ở mọi nơi: `README.md`, `package.json`, `pyproject.toml`, `CONTRIBUTORS`, header license, comment đầu file.

Mục "Công cụ AI đã sử dụng" trong `README.md`, viết theo Điều 11–12 thể lệ cuộc thi, **không** phải là ghi danh: mục này do thành viên tự viết. Agent chỉ sửa mục này khi được yêu cầu trực tiếp, và không ghi tên AI vào đó như một contributor hay tác giả.
