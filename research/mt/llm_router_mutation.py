"""E11 的突變測試：對 LLM 路由器的 **prompt** 做突變，算 測試 × 突變體 矩陣。

regex 路由的突變體是「刪一個分支 / 少一個關鍵字」；prompt 路由的對應物是：
    INTENT_DEL  刪掉一個意圖那一行（模型不知道有這個意圖）
    EX_DEL      刪掉一個意圖的例句
    DEF_DEL     刪掉一個意圖的定義（只剩名稱、格式、例句）
    RULE_DEL    刪掉一條全域規則（填充詞 / 禮貌語 / 語序 / 否定問句 / 不確定回 model）

殺 = 同一句在原 prompt 和突變 prompt 下的標籤不同（same_route 判）。
省 API：改意圖 X 那一行只重跑「原版路由到 X」的句子（其他句子假設不變——跟 hass_mutation 一樣的近似）；
RULE_DEL 全部重跑。預設測試 = 87 條種子 + 每條關係抽 N 句規則式改寫（--per-relation）。

    python -m research.mt.llm_router_mutation --tags rules_llmr --per-relation 20       # out/matrix_llmr.csv、mutants_llmr.json
    python -m research.mt.reduce out/matrix_llmr.csv --drop-trivial
    python -m research.mt.subsume out/matrix_llmr.csv --mutants out/mutants_llmr.json
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import llm_router

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


@dataclass
class Mutant:
    id: str
    op: str
    where: str
    before: str
    after: str
    prompt: str


def generate() -> list[Mutant]:
    muts: list[Mutant] = []
    ints, R = llm_router.INTENTS, llm_router.RULES

    def add(op, where, before, after, intents=None, rules=None):
        muts.append(Mutant(f"p{len(muts):03d}", op, where, before, after, llm_router.build_prompt(intents, rules)))

    for i, (name, desc, fmt, ex) in enumerate(ints):
        add("INTENT_DEL", name, f"- {name}：{desc}", "", [x for j, x in enumerate(ints) if j != i])
        add("EX_DEL", name, ex, "", [x if j != i else (name, desc, fmt, "") for j, x in enumerate(ints)])
        add("DEF_DEL", name, desc, "", [x if j != i else (name, "", fmt, ex) for j, x in enumerate(ints)])
    for j, r in enumerate(R):
        add("RULE_DEL", f"rule:{j}", r, "", None, [x for k, x in enumerate(R) if k != j])
    return muts


def load_tests(tags: list[str], per_relation: int, seed: int) -> list[dict]:
    seeds = json.loads((HERE / "seeds.json").read_text(encoding="utf-8"))["seeds"]
    tests = [{"id": f"seed:{s['id']}", "text": s["text"], "src": "seed_sv" if s["id"].startswith("sv_") else "seed", "relation": "seed"} for s in seeds]
    seen = {t["text"] for t in tests}
    rng = random.Random(seed)
    for tag in tags:
        p = OUT / f"tests_{tag}.jsonl"
        if not p.is_file():
            print(f"[skip] {p.name} 不存在（先跑 run.py --subject llm --tag-suffix _llmr）")
            continue
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        by_rel: dict[str, list[dict]] = {}
        for r in rows:
            if r["valid"] and r["text"] not in seen:
                by_rel.setdefault(r["relation"], []).append(r)
        for rel, rs in sorted(by_rel.items()):
            for r in rng.sample(rs, min(per_relation, len(rs))):
                seen.add(r["text"])
                tests.append({"id": f"{tag}:{r['seed_id']}:{rel}:{len(tests)}", "text": r["text"], "src": tag, "relation": rel})
    return tests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="*", default=["rules_llmr"])
    ap.add_argument("--per-relation", type=int, default=20, help="每個批次 × 關係抽幾句（控制 API 量）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ops", nargs="*", default=None, help="只跑這些運算子")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out-tag", default="llmr")
    ap.add_argument("--workers", type=int, default=llm_router.WORKERS)
    ap.add_argument("--model", default=None, help="換模型")
    ap.add_argument("--style", default=None, choices=llm_router.STYLES, help="prompt 寫法；跟原 prompt 一樣的突變體（例：noex 下的 EX_DEL）會被略過")
    a = ap.parse_args()
    llm_router.configure(a.model, a.style)
    muts = [m for m in generate() if m.prompt != llm_router.default_prompt()]
    if a.ops:
        muts = [m for m in muts if m.op in a.ops]
    print(f"prompt 突變體 {len(muts)}：{dict(Counter(m.op for m in muts))}")
    OUT.mkdir(exist_ok=True)
    (OUT / f"mutants_{a.out_tag}.json").write_text(json.dumps(
        [{"id": m.id, "op": m.op, "line": 0, "where": m.where, "before": m.before, "after": m.after} for m in muts],
        ensure_ascii=False, indent=1), encoding="utf-8")
    if a.list:
        for m in muts:
            print(f"{m.id} {m.op:10} {m.where:22} {m.before[:50]!r}")
        return 0
    tests = load_tests(a.tags, a.per_relation, a.seed)
    texts = [t["text"] for t in tests]
    base = llm_router.batch_labels(texts, workers=a.workers)
    for t, lab in zip(tests, base, strict=True):
        t["expect"] = str(lab)
    by_kind: dict[str, list[int]] = {}
    for i, lab in enumerate(base):
        by_kind.setdefault(lab.kind, []).append(i)
    print(f"測試 {len(tests)} 條（{dict(Counter(t['src'] for t in tests))}）；原版標籤分佈 {dict(Counter(lb.kind for lb in base))}")

    matrix = [[0] * len(muts) for _ in tests]
    t0 = time.time()
    calls = 0
    for j, m in enumerate(muts):
        idx = by_kind.get(m.where, []) if m.op != "RULE_DEL" else list(range(len(tests)))
        if not idx:
            continue
        labs = llm_router.batch_labels([texts[i] for i in idx], prompt=m.prompt, workers=a.workers)
        calls += len(idx)
        for i, lab in zip(idx, labs, strict=True):
            if not llm_router.same_route(lab, base[i]):
                matrix[i][j] = 1
        print(f"  {j + 1}/{len(muts)} {m.op} {m.where}：重跑 {len(idx)} 句，殺 {sum(matrix[i][j] for i in idx)}，累計 {calls} 次呼叫，{time.time() - t0:.0f}s", flush=True)
    with (OUT / f"matrix_{a.out_tag}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "text", "relation", "src"] + [m.id for m in muts])
        for t, row in zip(tests, matrix, strict=True):
            w.writerow([t["id"], t["text"], t["relation"], t["src"]] + row)
    killed = {j for row in matrix for j, v in enumerate(row) if v}
    per_src: dict[str, set[int]] = {}
    for t, row in zip(tests, matrix, strict=True):
        per_src.setdefault(t["src"], set()).update(j for j, v in enumerate(row) if v)
    summary = {"tests": len(tests), "mutants": len(muts), "killed": len(killed), "score": round(len(killed) / len(muts), 3),
               "calls": calls, "killed_by_source": {k: len(v) for k, v in per_src.items()},
               "killed_by_op": {op: sum(1 for j, m in enumerate(muts) if m.op == op and j in killed) for op in sorted({m.op for m in muts})},
               "survivors": [{"id": m.id, "op": m.op, "where": m.where, "before": m.before} for j, m in enumerate(muts) if j not in killed]}
    (OUT / f"mutation_summary_{a.out_tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"殺掉 {len(killed)} / {len(muts)}，突變分數 {summary['score']}；各運算子 {summary['killed_by_op']}；各來源 {summary['killed_by_source']}；API {calls} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
