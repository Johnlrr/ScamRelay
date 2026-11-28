"""Đo độ trễ LLM thật của analyze và compile trên các ca dev (P50/P95, x/n lỗi).

    backend/.venv/bin/python bench/latency.py [--rounds 1]

Không ghi đè dev_compiled. Kết quả: bench/results/latency_<thời điểm>.{json,md}.
Thời gian đo là thời gian gọi LLM tính cả retry (đúng như người dùng chờ), không gồm thời gian giãn request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone

import _common

from app.ai import incident_ai, llm_client, rule_ai
from app.ai.llm_client import LLMError
from app.core._contract_draft import IncidentAnalysisLLM, RelayRuleDraftLLM
from app.core.preprocess import mask_pii

PAUSE_S = 4


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, round(q * (len(xs) - 1)))], 2)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    args = ap.parse_args()
    _common.load_env()
    llm = llm_client.get_llm()
    if llm is None:
        print("thiếu GEMINI_API_KEY")
        return 2
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((_common.BENCH / "cases" / "dev").glob("*.json"))]
    times: dict[str, list[float]] = {"analyze": [], "compile": []}
    errors: dict[str, list[str]] = {"analyze": [], "compile": []}
    for _ in range(args.rounds):
        for case in cases:
            masked = mask_pii(case["incident_A"]["text"])
            t0 = time.perf_counter()
            try:
                r = await llm.generate_json(incident_ai.build_prompt(masked.text, masked.otp_mentioned, []),
                                            IncidentAnalysisLLM, timeout_s=incident_ai.TIMEOUT_S, retries=1)
                times["analyze"].append(time.perf_counter() - t0)
                analysis = incident_ai.to_domain(r.data)
            except (LLMError, ValueError) as e:
                errors["analyze"].append(f"{case['case_id']}: {type(e).__name__}")
                continue
            await asyncio.sleep(PAUSE_S)
            t0 = time.perf_counter()
            try:
                await llm.generate_json(rule_ai.build_prompt(analysis), RelayRuleDraftLLM,
                                        timeout_s=rule_ai.TIMEOUT_S, retries=1)
                times["compile"].append(time.perf_counter() - t0)
            except LLMError as e:
                errors["compile"].append(f"{case['case_id']}: {type(e).__name__}")
            await asyncio.sleep(PAUSE_S)
            print(f"{case['case_id']} ok", flush=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    summary = {}
    for k in times:
        n_ok, n_err = len(times[k]), len(errors[k])
        summary[k] = {"ok": f"{n_ok}/{n_ok + n_err}", "p50": pct(times[k], 0.5), "p95": pct(times[k], 0.95),
                      "max": round(max(times[k]), 2) if times[k] else None,
                      "mean": round(statistics.mean(times[k]), 2) if times[k] else None, "errors": errors[k]}
    payload = {"generated_at": stamp, "model": llm.model,
               "prompts": [incident_ai.PROMPT_VERSION, rule_ai.PROMPT_VERSION], "summary": summary,
               "raw_seconds": {k: [round(x, 3) for x in v] for k, v in times.items()}}
    out = _common.BENCH / "results" / f"latency_{stamp}"
    out.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = [f"# Độ trễ LLM — {stamp} ({llm.model})", "", "| Bước | Thành công | P50 (s) | P95 (s) | Max (s) |", "|---|---|---|---|---|"]
    md += [f"| {k} | {s['ok']} | {s['p50']} | {s['p95']} | {s['max']} |" for k, s in summary.items()]
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
