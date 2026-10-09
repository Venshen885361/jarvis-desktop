"""第二受測對象的突變測試：對 Home Assistant zh-TW 意圖模板做突變，算 測試 × 突變體 矩陣。

模板語法跟我的突變運算子一一對應：
    ALT_DEL   `(打開|開|開啟)` → 少一個分支（少收一個同義詞）
    OPT_DEL   `[把|將]` → `(把|將)`、`[的]` → `的`（可選變必要）
    SKIP_DEL  skip_words 少一個（請 / 幫我 / 謝謝 不再被忽略）
    RULE_ALT  expansion_rules（<open>、<set_to>…）裡的 `(a|b)` 少一個分支——一條 rule 被很多模板共用

殺的定義跟 mutation.py 一樣：某條測試在原版辨識到 X、在突變體辨識到 ≠ X。
加速：改某個意圖的模板只可能讓「原本就辨識到那個意圖」的句子變結果（模板只會少收，不會多收；
少收之後可能掉到別的意圖或 none），所以每個模板突變體只重跑那些句子；rule / skip 突變體全部重跑。

    python -m research.mt.hass_mutation                       # out/matrix_hass.csv、mutants_hass.json、mutation_summary_hass.json
    python -m research.mt.reduce out/matrix_hass.csv --drop-trivial
    python -m research.mt.subsume out/matrix_hass.csv --mutants out/mutants_hass.json
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import hass

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

_ALT_GROUP = re.compile(r"\(([^()]*\|[^()]*)\)")   # 最內層、含 | 的括號
_OPT_GROUP = re.compile(r"\[([^\[\]]*)\]")        # 最內層的可選


@dataclass
class Mutant:
    id: str
    op: str
    where: str      # 意圖名 / "rule:<name>" / "skip"
    before: str
    after: str
    data: dict      # 突變後的整份 intents dict（不寫進 json）


def _string_mutants(s: str) -> list[tuple[str, str, str]]:
    outs: list[tuple[str, str, str]] = []
    for g in _ALT_GROUP.finditer(s):
        parts = g.group(1).split("|")
        if len(parts) < 2:
            continue
        for k in range(len(parts)):
            rest = [p for i, p in enumerate(parts) if i != k]
            new = "(" + "|".join(rest) + ")" if len(rest) > 1 else rest[0]
            outs.append(("ALT_DEL", s, s[:g.start()] + new + s[g.end():]))
    for g in _OPT_GROUP.finditer(s):
        body = g.group(1)
        new = f"({body})" if "|" in body else body
        outs.append(("OPT_DEL", s, s[:g.start()] + new + s[g.end():]))
    return outs


def generate(data: dict) -> list[Mutant]:
    muts: list[Mutant] = []
    seen: set[tuple] = set()

    def add(op, where, before, after, mutate):
        key = (op, where, before, after)
        if key in seen:
            return
        seen.add(key)
        d = copy.deepcopy(data)
        mutate(d)
        muts.append(Mutant(f"h{len(muts):04d}", op, where, before, after, d))

    for name, intent in data["intents"].items():
        for di, dblock in enumerate(intent["data"]):
            for si, s in enumerate(dblock.get("sentences", [])):
                for op, before, after in _string_mutants(s):
                    add(op, name, before, after,
                        lambda d, name=name, di=di, si=si, after=after: d["intents"][name]["data"][di]["sentences"].__setitem__(si, after))
    for rname, rule in data["expansion_rules"].items():
        for op, before, after in _string_mutants(rule):
            add("RULE_" + op, f"rule:{rname}", before, after,
                lambda d, rname=rname, after=after: d["expansion_rules"].__setitem__(rname, after))
    for w in data.get("skip_words", []):
        add("SKIP_DEL", "skip", w, "", lambda d, w=w: d["skip_words"].remove(w))
    return muts


def load_tests(tags: list[str], seed_files: list[str] | None = None) -> list[dict]:
    tests, seen = [], set()
    for sf in seed_files or ["seeds_hass.json"]:
        src = "seed" if sf == "seeds_hass.json" else Path(sf).stem.replace("seeds_", "seed_")
        for s in json.loads((HERE / sf).read_text(encoding="utf-8"))["seeds"]:
            if s["text"] not in seen:
                seen.add(s["text"])
                tests.append({"id": f"{src}:{s['id']}", "text": s["text"], "src": src, "relation": "seed"})
    for tag in tags:
        p = OUT / f"tests_{tag}.jsonl"
        if not p.is_file():
            print(f"[skip] {p.name} 不存在")
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if not r["valid"] or r["violation"] or r["text"] in seen:
                continue
            seen.add(r["text"])
            tests.append({"id": f"{tag}:{r['seed_id']}:{r['relation']}:{len(tests)}", "text": r["text"], "src": tag, "relation": r["relation"]})
    return tests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="*", default=["rules_hass"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--seed-files", nargs="*", default=["seeds_hass.json"], help="research/mt/ 下的種子檔（seeds_hass.json、seeds_hass_sampled.json）")
    ap.add_argument("--out-tag", default="hass", help="輸出檔名：matrix_<tag>.csv")
    a = ap.parse_args()
    data = hass.raw()
    muts = generate(data)
    if a.limit:
        muts = muts[:a.limit]
    print(f"突變體 {len(muts)}：{dict(Counter(m.op for m in muts))}")
    OUT.mkdir(exist_ok=True)
    (OUT / "mutants_hass.json").write_text(json.dumps(
        [{"id": m.id, "op": m.op, "line": 0, "where": m.where, "before": m.before, "after": m.after} for m in muts],
        ensure_ascii=False, indent=1), encoding="utf-8")
    if a.list:
        return 0
    tests = load_tests(a.tags, a.seed_files)
    texts = [t["text"] for t in tests]
    base = hass.batch_labels(texts)
    for t, lab in zip(tests, base, strict=True):
        t["expect"] = str(lab)
    by_intent: dict[str, list[int]] = {}
    for i, lab in enumerate(base):
        by_intent.setdefault(lab.kind, []).append(i)
    print(f"測試 {len(tests)} 條（來源：{', '.join(a.tags)}）；原版辨識到意圖的 {sum(1 for lb in base if lb.kind != 'none')} 條")

    matrix = [[0] * len(muts) for _ in tests]
    t0 = time.time()
    for j, m in enumerate(muts):
        idx = by_intent.get(m.where, []) if m.where in data["intents"] else list(range(len(tests)))
        if not idx:
            continue
        try:
            intents = hass.build(m.data)
            labs = hass.batch_labels([texts[i] for i in idx], intents)
        except Exception:
            labs = [hass.Label("error", "build")] * len(idx)
        for i, lab in zip(idx, labs, strict=True):
            if str(lab) != tests[i]["expect"]:
                matrix[i][j] = 1
        if (j + 1) % 100 == 0:
            print(f"  {j + 1}/{len(muts)}，{time.time() - t0:.0f}s", flush=True)
    with (OUT / f"matrix_{a.out_tag}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "text", "relation", "src"] + [m.id for m in muts])
        for t, row in zip(tests, matrix, strict=True):
            w.writerow([t["id"], t["text"], t["relation"], t["src"]] + row)
    killed = {j for row in matrix for j, v in enumerate(row) if v}
    per_src: dict[str, set[int]] = {}
    for t, row in zip(tests, matrix, strict=True):
        per_src.setdefault(t["src"], set()).update(j for j, v in enumerate(row) if v)
    ops_alive = Counter(m.op for j, m in enumerate(muts) if j not in killed)
    summary = {"tests": len(tests), "mutants": len(muts), "killed": len(killed), "score": round(len(killed) / len(muts), 3),
               "killed_by_source": {k: len(v) for k, v in per_src.items()}, "survived_by_op": dict(ops_alive),
               "survivors": [{"id": m.id, "op": m.op, "where": m.where, "before": m.before, "after": m.after} for j, m in enumerate(muts) if j not in killed]}
    (OUT / f"mutation_summary_{a.out_tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"殺掉 {len(killed)} / {len(muts)}，突變分數 {summary['score']}；各來源 {summary['killed_by_source']}；存活依運算子 {dict(ops_alive)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
