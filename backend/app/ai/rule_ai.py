"""Luồng 2 — biên dịch bản nháp RelayRule bằng LLM (SPEC §7.2a, D7).

`compile_rule(analysis) -> CompileResult`
- Trả JSON THÔ (`raw`); router đưa vào `validate_llm_output` rồi assembler. Ở đây không kiểm nghiệp vụ.
- LLM lỗi / 429 / timeout → đọc output LLM THẬT đã lưu cho thủ đoạn tương ứng trong
  `fallback_tactics.json` (`source="CACHED_FALLBACK"`, `degraded=True`). Không có thì ném
  `CompileUnavailable` để UI hiện nút "Biên dịch lại". Không bao giờ dựng luật giả làm output LLM.
"""

from __future__ import annotations

import copy
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from string import Template

from app.ai.incident_ai import load_fallback_tactics
from app.ai.llm_client import LLMError, get_llm
from app.schemas.incident import IncidentAnalysis
from app.schemas.llm_rule import RelayRuleDraftLLM
from app.schemas.rule import CompileResult

PROMPT_VERSION = "rule_compile.v3"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
TIMEOUT_S = 30


class CompileUnavailable(RuntimeError):
    """LLM lỗi và không có output đã lưu cho thủ đoạn này."""


@lru_cache(maxsize=2)
def _template(name: str) -> Template:
    return Template((PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8"))


def target_family(analysis: IncidentAnalysis) -> str:
    if analysis.tactic_family == "OTHER_NEW" and analysis.tactic_slug:
        return analysis.tactic_slug
    return analysis.tactic_family


def build_prompt(analysis: IncidentAnalysis) -> str:
    payload = json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False, indent=1)
    payload = re.sub(r"<\s*/?\s*incident_analysis", "‹incident_analysis", payload, flags=re.IGNORECASE)
    return _template(PROMPT_VERSION).substitute(tactic_family=target_family(analysis), analysis_json=payload)


def cached_compile_output(tactic_family: str) -> dict | None:
    entry = load_fallback_tactics().get(tactic_family) or {}
    out = entry.get("compile_output")
    return copy.deepcopy(out) if out else None


async def compile_rule(analysis: IncidentAnalysis) -> CompileResult:
    start = time.perf_counter()
    llm = get_llm()
    if llm is not None:
        try:
            resp = await llm.generate_json(build_prompt(analysis), RelayRuleDraftLLM, timeout_s=TIMEOUT_S, retries=1)
            return CompileResult(raw=resp.data, source="LLM", degraded=False, llm_seconds=resp.seconds)
        except LLMError:
            pass
    cached = cached_compile_output(analysis.tactic_family)
    if cached is None:
        raise CompileUnavailable(f"LLM không phản hồi và chưa có kết quả đã lưu cho {analysis.tactic_family}")
    return CompileResult(raw=cached, source="CACHED_FALLBACK", degraded=True,
                         llm_seconds=time.perf_counter() - start)
