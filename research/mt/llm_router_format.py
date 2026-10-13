"""E13 第六條關係「格式」（只對模型路由有意義）：改寫句送進模型之後，回答還是不是合法的 JSON、kind 還在不在 25 個意圖裡。

兩個資料來源：
    快取 out/cache_llmrouter/*.json   每一句的 kind（離線就能算「kind 不在清單內」的比例）
    out/llmrouter_format.jsonl         每一次真的打 API 的回應（含解析失敗；失敗不進快取，所以只有這裡量得到失敗率）

把句子接回 tests_*llmr*.jsonl 就能分關係看。Liu 與 Meng（2026）說小模型遇到等價改寫有 78% 離開答案格式；
這裡強制 response_mime_type=application/json，所以要看的是另外兩種崩潰：JSON 截斷、kind 編出清單外的名字。

    python -m research.mt.llm_router_format                 # 全部模型 × 寫法
    python -m research.mt.llm_router_format --by-relation   # 分關係
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import llm_router

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# prompt sha → 寫法名稱（llm_router.build_prompt 固定標題列，這三個 sha 對應 E11 / E12 跑過的 prompt）
STYLE_OF = {"ff2032978755": "full", "97fe544d8759": "noex", "f836553a62a0": "names"}


def _relation_index() -> dict[str, str]:
    """句子 → 關係（seed 的句子標 seed）。同一句出現在多個批次時取第一個。"""
    idx: dict[str, str] = {}
    seeds = json.loads((HERE / "seeds.json").read_text(encoding="utf-8"))["seeds"]
    for s in seeds:
        idx[s["text"]] = "seed"
    for p in sorted(OUT.glob("tests_*llmr*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                idx.setdefault(r["text"], r["relation"])
    return idx


def from_cache() -> list[dict]:
    rows = []
    for p in (OUT / "cache_llmrouter").glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        m = d["meta"]
        rows.append({"model": m["model"], "prompt_sha": m["prompt_sha"], "text": d["text"], "kind": d["kind"],
                     "json_ok": d["kind"] != "error", "in_vocab": d["kind"] in llm_router.KNOWN_KINDS, "src": "cache"})
    return rows


def from_log() -> list[dict]:
    p = llm_router.FORMAT_LOG
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            r["src"] = "log"
            rows.append(r)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-relation", action="store_true")
    ap.add_argument("--only-styles", nargs="*", default=None, help="只看這些 prompt 寫法（full / noex / names）")
    a = ap.parse_args()
    rel_of = _relation_index()
    cache = from_cache()
    log = from_log()
    out: dict = {"cache": {}, "log": {}}

    print("== 快取（每句一筆；解析失敗不在裡面，所以 json_ok 只有舊的錯誤項）==")
    print(f"{'模型 × 寫法':34} {'句數':>7} {'kind 不在清單':>12} {'比例':>7}  清單外的 kind")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in cache:
        style = STYLE_OF.get(r["prompt_sha"], "mutant")   # 其餘 sha 是 prompt 突變體
        if a.only_styles and style not in a.only_styles:
            continue
        groups[(r["model"], style)].append(r)
    for (model, style), rs in sorted(groups.items()):
        oov = [r for r in rs if r["json_ok"] and not r["in_vocab"]]
        kinds = Counter(r["kind"] for r in oov)
        out["cache"][f"{model}|{style}"] = {"n": len(rs), "oov": len(oov), "oov_kinds": dict(kinds.most_common(10))}
        print(f"{model + ' × ' + style:34} {len(rs):7d} {len(oov):12d} {100 * len(oov) / len(rs):6.1f}%  {dict(kinds.most_common(5))}")
        if a.by_relation:
            by_rel: dict[str, list[dict]] = defaultdict(list)
            for r in rs:
                by_rel[rel_of.get(r["text"], "?")].append(r)
            for rel, rr in sorted(by_rel.items()):
                o = sum(1 for r in rr if r["json_ok"] and not r["in_vocab"])
                print(f"    {rel:16} {len(rr):6d} {o:5d} {100 * o / len(rr):6.1f}%")

    if log:
        print("\n== 真的打 API 的回應（out/llmrouter_format.jsonl，含解析失敗）==")
        print(f"{'模型 × 寫法':34} {'次數':>7} {'API 錯':>7} {'JSON 壞':>8} {'kind 清單外':>11}")
        lg: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in log:
            lg[(r["model"], STYLE_OF.get(r["prompt_sha"], "mutant"))].append(r)
        for (model, style), rs in sorted(lg.items()):
            api = sum(1 for r in rs if not r["api_ok"])
            bad = sum(1 for r in rs if r["api_ok"] and not r["json_ok"])
            oov = sum(1 for r in rs if r["json_ok"] and not r["in_vocab"])
            out["log"][f"{model}|{style}"] = {"n": len(rs), "api_error": api, "json_bad": bad, "oov": oov}
            print(f"{model + ' × ' + style:34} {len(rs):7d} {api:7d} {bad:8d} {oov:11d}")
    else:
        print("\n（還沒有 out/llmrouter_format.jsonl：解析失敗率要等下一次真的打 API 才有）")
    (OUT / "format_llmr.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
