"""E8 突變體包含關係（mutant subsumption）：927 個突變體裡有幾個是「真的不一樣」？

兩個突變體如果被同一群測試殺掉，對測試集來說是同一個錯（indistinguishable）。
若殺 m 的測試都殺 n（kill(m) ⊆ kill(n)），m 包含 n：只要殺得掉 m 就一定殺得掉 n，n 是多餘的。
沒被任何其他突變體嚴格包含的叫 dominator；dominator 的集合是「最小突變體集」，
用它算的分數（minimal mutation score）比一般突變分數嚴格——一般分數會被一堆同一個錯的突變體灌水。

    python -m research.mt.subsume out/matrix_merged.csv
    python -m research.mt.subsume out/matrix_merged.csv --subset out/reduce_merged.json   # 評估縮減子集的最小分數

輸出：各運算子有多少突變體是多餘的、dominator 的數量與運算子分佈、
      縮減子集 / 排序前 k% 在「一般分數」與「最小分數」下的差距。
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import mutation, reduce


def kill_vectors(matrix: list[list[int]]) -> dict[int, frozenset[int]]:
    """突變體 j → 殺它的測試集合（只留被殺過的）。"""
    out: dict[int, set[int]] = defaultdict(set)
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            if v:
                out[j].add(i)
    return {j: frozenset(s) for j, s in out.items()}


def analyze(kv: dict[int, frozenset[int]]) -> dict:
    # 1) 同一群測試殺的 → 一類（indistinguishable）
    classes: dict[frozenset[int], list[int]] = defaultdict(list)
    for j, s in kv.items():
        classes[s].append(j)
    reps = list(classes.keys())
    # 2) 類之間的嚴格包含：A ⊂ B 表示 A 更難殺（殺 A 的測試都殺 B）→ A 包含 B，B 多餘
    dominated: set[frozenset[int]] = set()
    for a in reps:
        for b in reps:
            if a is not b and a < b:
                dominated.add(b)
    dominators = [s for s in reps if s not in dominated]
    return {"killed": len(kv), "classes": len(reps), "dominator_classes": len(dominators),
            "dominators": dominators, "classes_map": classes}


def minimal_score(test_idx: set[int], dominators: list[frozenset[int]]) -> float:
    """一個測試子集的最小突變分數：殺掉幾成的 dominator 類。"""
    return sum(1 for s in dominators if s & test_idx) / len(dominators) if dominators else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("matrix")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ops", nargs="*", help="只用這些運算子的突變體（例：ALT_DEL KW_DEL CMP），看縮減 / 排序的結論變不變")
    a = ap.parse_args()
    tests, mutants, matrix = reduce.load_matrix(Path(a.matrix))
    meta = {m["id"]: m for m in json.loads((mutation.OUT / "mutants.json").read_text(encoding="utf-8"))} \
        if (mutation.OUT / "mutants.json").is_file() else {}
    if a.ops:
        keep = [j for j, mid in enumerate(mutants) if meta.get(mid, {}).get("op") in set(a.ops)]
        mutants = [mutants[j] for j in keep]
        matrix = [[row[j] for j in keep] for row in matrix]
        print(f"只用運算子 {a.ops}：{len(mutants)} 個突變體")
    n_tests = len(tests)
    # 丟掉「每條測試都殺」的（沒鑑別力，reduce 也這樣做）
    kv = {j: s for j, s in kill_vectors(matrix).items() if len(s) < n_tests}
    res = analyze(kv)
    print(f"測試 {n_tests}，突變體 {len(mutants)}，可殺 {res['killed']}")
    print(f"真的不一樣（kill vector 不同）：{res['classes']} 類 → {res['killed'] / res['classes']:.1f} 個突變體共用一類")
    print(f"dominator（沒被更難殺的包含）：{res['dominator_classes']} 類 = 一般分數的分母 {res['killed']} 裡只有 "
          f"{res['dominator_classes'] / res['killed']:.0%} 是獨立的錯")

    # 運算子分佈：每個運算子的突變體有幾成是多餘的（被同類或被包含）
    dom_set = set(res["dominators"])
    op_total, op_dom = Counter(), Counter()
    for s, js in res["classes_map"].items():
        rep = js[0]
        for j in js:
            op = meta.get(mutants[j], {}).get("op", "?")
            op_total[op] += 1
            if s in dom_set and j == rep:
                op_dom[op] += 1
    print(f"\n{'運算子':10} {'可殺':>5} {'dominator 代表':>14} {'多餘比例':>8}")
    for op, n in op_total.most_common():
        print(f"{op:10} {n:5d} {op_dom[op]:14d} {1 - op_dom[op] / n:8.0%}")

    # 最難殺的 dominator：只被 1–2 條測試殺的（它們就是「不可取代的測試」在守的錯）
    hard = sorted(res["dominators"], key=len)[:10]
    print("\n最難殺的 10 個 dominator 類（殺它的測試數 → 代表突變體）：")
    for s in hard:
        j = res["classes_map"][s][0]
        m = meta.get(mutants[j], {})
        print(f"  {len(s):3d} 條測試殺  {mutants[j]} {m.get('op', '')} L{m.get('line', '?')}  {m.get('before', '')[:50]!r} → {m.get('after', '')[:40]!r}")

    # 一般分數 vs 最小分數：縮減子集與排序前 k%
    cov = [{j for j in kv if i in kv[j]} for i in range(n_tests)]
    idx = {j: k for k, j in enumerate(sorted(kv))}
    cov_k = [{idx[j] for j in s} for s in cov]
    dom_list = res["dominators"]
    rng = random.Random(a.seed)
    print(f"\n{'測試子集':28} {'大小':>5} {'一般分數':>8} {'最小分數':>8}")
    for name, chosen in (("greedy（突變體）", reduce.greedy(cov_k)), ("HGS", reduce.hgs(cov_k)),
                         ("irreplaceable", reduce.irreplaceable_first(cov_k))):
        sub = set(chosen)
        normal = len(reduce.kill_set(chosen, cov_k)) / len(kv)
        print(f"{name:28} {len(chosen):5d} {normal:8.1%} {minimal_score(sub, dom_list):8.1%}")
        rand_n, rand_m = [], []
        for _ in range(a.runs):
            r = set(rng.sample(range(n_tests), len(chosen)))
            rand_n.append(len(reduce.kill_set(list(r), cov_k)) / len(kv))
            rand_m.append(minimal_score(r, dom_list))
        print(f"{'  同大小隨機':28} {len(chosen):5d} {statistics.mean(rand_n):8.1%} {statistics.mean(rand_m):8.1%}")
    order = reduce.order_additional(cov_k)
    # 以 dominator 類當「錯」算 APFD：每類被第一次殺到的位置
    dom_idx = [{idx[j] for j in res["classes_map"][s]} for s in dom_list]   # 每個 dominator 類 → 它的突變體（新編號）
    def apfd_dom(ordr):
        pos = {}
        for p_, i in enumerate(ordr, 1):
            for d, muts in enumerate(dom_idx):
                if d not in pos and cov_k[i] & muts:
                    pos[d] = p_
        n, m = len(ordr), len(dom_idx)
        return 1 - sum(pos.get(d, n + 1) for d in range(m)) / (n * m) + 1 / (2 * n)
    print(f"\n{'排序':20} {'APFD（全部突變體）':>14} {'APFD（dominator）':>14}")
    for name, ordr in (("additional", order), ("total", reduce.order_total(cov_k)), ("relation-first", reduce.order_relation(tests, cov_k))):
        print(f"{name:20} {reduce.apfd(ordr, cov_k, len(kv)):14.3f} {apfd_dom(ordr):14.3f}")
    rnd = [rng.sample(range(n_tests), n_tests) for _ in range(5)]
    print(f"{'random(5)':20} {statistics.mean(reduce.apfd(o, cov_k, len(kv)) for o in rnd):14.3f} {statistics.mean(apfd_dom(o) for o in rnd):14.3f}")
    for frac in (0.02, 0.05, 0.1):
        k = max(1, int(n_tests * frac))
        sub = set(order[:k])
        print(f"{'additional 前 ' + f'{frac:.0%}':28} {k:5d} {len(reduce.kill_set(order[:k], cov_k)) / len(kv):8.1%} {minimal_score(sub, dom_list):8.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
