"""E13 生到飽和：模型生成器不固定 n，而是一輪一輪生（每輪 n 句、換 rep 當快取鍵），
直到「這一輪新出現的不重複句子」少於總數的某個比例為止，看錯數是不是在 n=20 之後就飽和。

Guglielmi 等人（EMSE 2026）對 Alexa skill 是「生到沒有新句為止」；這裡量的是每多一輪，
多幾句、多幾個違反、多幾個去重後的錯（種子 × 關係 × 路到哪）。T=0 n=20 的 rep 0 / 1 / 2 已經在快取裡（E2），所以前三輪免費。

    python -m research.mt.saturate --max-rounds 8                       # 41 條原始種子、T=0、每輪 20 句、router.py
    python -m research.mt.saturate --max-rounds 8 --subject llm         # 受測對象換成模型路由（每句一次 API）
輸出 out/saturate_<tag>.json 與 out/tests_saturate_<tag>.jsonl。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from . import llm
from .relations import RELATIONS
from .run import _NO_NEAR_MISS_KINDS, _distinct2, _parse_label, _subject, _valid

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--n", type=int, default=20, help="每輪每個 種子×關係 生幾句")
    ap.add_argument("--max-rounds", type=int, default=8)
    ap.add_argument("--stop-new-frac", type=float, default=0.05, help="這一輪新句子 / 累計句子 低於這個值就停")
    ap.add_argument("--seeds", default=str(HERE / "seeds.json"))
    ap.add_argument("--seed-filter", default="^(?!sv_)", help="預設只用 41 條原始種子（跟 E2 一致）")
    ap.add_argument("--subject", choices=["jarvis", "llm"], default="jarvis")
    ap.add_argument("--router-model", default=None)
    ap.add_argument("--tag", default=None)
    a = ap.parse_args()
    batch_labels, same_route = _subject(a.subject, a.router_model, None)
    tag = a.tag or f"{a.model}_T{a.temperature:g}_n{a.n}" + ("" if a.subject == "jarvis" else "_llmr")

    seeds = json.loads(Path(a.seeds).read_text(encoding="utf-8"))["seeds"]
    if a.seed_filter:
        seeds = [s for s in seeds if re.search(a.seed_filter, s["id"])]
    pairs = []
    for s in seeds:
        lab = _parse_label(s["expect"])
        for rel in RELATIONS:
            if rel.expect == "different" and lab.kind in _NO_NEAR_MISS_KINDS:
                continue
            pairs.append((s, lab, rel))

    rows: list[dict] = []          # 累計的不重複句子
    seen: set[tuple[str, str, str]] = set()
    rounds: list[dict] = []
    t0 = time.time()
    for r in range(a.max_rounds):
        new = 0
        fails = 0
        for s, lab, rel in pairs:
            g = llm.generate(s["text"], rel, a.n, model=a.model, temperature=a.temperature, rep=r)
            fails += 0 if g["ok"] else 1
            for text in g["items"]:
                text = re.sub(r"\s+", " ", text).strip()
                key = (s["id"], rel.id, text)
                if not text or text == s["text"] or key in seen:
                    continue
                seen.add(key)
                ok, why = _valid(text, lab, rel.expect)
                rows.append({"seed_id": s["id"], "seed": s["text"], "relation": rel.id, "expect": rel.expect, "text": text,
                             "seed_label": str(lab), "valid": ok, "invalid_reason": why, "round": r, "got": "", "violation": False})
                new += 1
        frac = new / len(rows) if rows else 1.0
        rounds.append({"round": r, "new": new, "total": len(rows), "new_frac": round(frac, 3), "gen_failures": fails,
                       "elapsed_s": round(time.time() - t0)})
        print(f"第 {r} 輪：新句 {new}，累計 {len(rows)}（新 {100 * frac:.1f}%），生成失敗 {fails}，{time.time() - t0:.0f}s", flush=True)
        if r >= 2 and frac < a.stop_new_frac:
            break

    # 路由全部累計句子（一次做完：regex 幾秒、模型靠快取 + 多線）
    labels = batch_labels([x["text"] for x in rows])
    for x, got in zip(rows, labels, strict=True):
        same = same_route(got, _parse_label(x["seed_label"]))
        x["got"] = str(got)
        x["violation"] = bool(x["valid"] and ((not same) if x["expect"] == "same" else same))

    # 每多一輪，累計的句子 / 違反 / 去重錯（種子 × 關係 × 路到的 kind）
    def fault_key(x: dict) -> tuple[str, str, str]:
        return (x["seed_id"], x["relation"], _parse_label(x["got"]).kind)

    print(f"\n{'輪':>3} {'累計句':>7} {'有效':>6} {'違反':>6} {'去重錯':>6} {'新錯':>5} {'dist2':>6}")
    faults_so_far: set = set()
    for rd in rounds:
        cum = [x for x in rows if x["round"] <= rd["round"]]
        valid = [x for x in cum if x["valid"]]
        viol = [x for x in valid if x["violation"]]
        faults = {fault_key(x) for x in viol}
        rd.update({"valid": len(valid), "violations": len(viol), "faults": len(faults), "new_faults": len(faults - faults_so_far),
                   "distinct2": _distinct2([x["text"] for x in valid])})
        faults_so_far |= faults
        print(f"{rd['round']:3d} {rd['total']:7d} {len(valid):6d} {len(viol):6d} {len(faults):6d} {rd['new_faults']:5d} {rd['distinct2']:6.3f}")

    by_rel: dict[str, dict] = {}
    for rel in RELATIONS:
        rs = [x for x in rows if x["relation"] == rel.id and x["valid"]]
        by_rel[rel.id] = {"valid": len(rs), "violations": sum(1 for x in rs if x["violation"]),
                          "faults": len({fault_key(x) for x in rs if x["violation"]})}
    OUT.mkdir(exist_ok=True)
    with (OUT / f"tests_saturate_{tag}.jsonl").open("w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    (OUT / f"saturate_{tag}.json").write_text(json.dumps(
        {"tag": tag, "model": a.model, "temperature": a.temperature, "n": a.n, "subject": a.subject, "seeds": len(seeds),
         "pairs": len(pairs), "rounds": rounds, "by_relation": by_rel}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ out/saturate_{tag}.json、out/tests_saturate_{tag}.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
