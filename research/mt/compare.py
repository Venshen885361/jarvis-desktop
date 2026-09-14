"""比較多批結果：溫度之間句子重疊多少、LLM 找到哪些規則式沒找到的錯（反之亦然）。

    python -m research.mt.compare                      # 比 out/ 裡所有 tests_*.jsonl
    python -m research.mt.compare rules gemini-3.5-flash-lite_T0.7

「錯」以 (seed_id, relation, got.kind) 當單位：同一個種子、同一條關係、被送到同一個錯的目的地算同一個錯，
不然「打開記事本好嗎」「打開記事本啦」會算兩個錯，比較沒意義。
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"


def load(tag: str) -> list[dict]:
    p = OUT / f"tests_{tag}.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def fault_keys(rows: list[dict]) -> set[tuple]:
    return {(r["seed_id"], r["relation"], r["got"].split(":")[0]) for r in rows if r["violation"]}


def main() -> int:
    tags = sys.argv[1:] or sorted(p.stem[len("tests_"):] for p in OUT.glob("tests_*.jsonl"))
    data = {t: load(t) for t in tags}

    print("== 每批：句子數 / 不重複句 / 違反 / 錯（去重後）==")
    for t, rows in data.items():
        sents = {r["text"] for r in rows}
        print(f"{t:32} {len(rows):5d} {len(sents):5d} {sum(r['violation'] for r in rows):5d} {len(fault_keys(rows)):5d}")

    print("\n== 兩批之間：句子 Jaccard 重疊（1 = 完全一樣）/ 只有左邊找到的錯 / 只有右邊找到的錯 ==")
    for a, b in combinations(tags, 2):
        sa, sb = {r["text"] for r in data[a]}, {r["text"] for r in data[b]}
        fa, fb = fault_keys(data[a]), fault_keys(data[b])
        j = len(sa & sb) / len(sa | sb) if sa | sb else 0
        print(f"{a:28} vs {b:28}  J={j:.2f}  {a}只有:{len(fa - fb):3d}  {b}只有:{len(fb - fa):3d}  共同:{len(fa & fb):3d}")

    print("\n== 錯的目的地分佈（去重後的錯，依「本來該去 → 實際去」）==")
    for t, rows in data.items():
        c: Counter = Counter()
        for r in rows:
            if r["violation"]:
                c[(r["seed_label"].split(":")[0], r["got"].split(":")[0])] += 1
        top = ", ".join(f"{a}→{b}:{n}" for (a, b), n in c.most_common(6))
        print(f"{t:32} {top}")

    print("\n== 哪些種子最脆（各批違反率平均）==")
    per_seed: dict[str, list[float]] = defaultdict(list)
    for rows in data.values():
        by: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            if r["valid"]:
                by[r["seed_id"]].append(r)
        for sid, rs in by.items():
            per_seed[sid].append(sum(r["violation"] for r in rs) / len(rs))
    for sid, v in sorted(per_seed.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))[:12]:
        print(f"{sid:16} {100 * sum(v) / len(v):5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
