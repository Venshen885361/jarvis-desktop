"""測試集縮減（E4）與排序（E5），在 mutation.py 產出的矩陣上跑。

    python -m research.mt.reduce out/matrix_rules.csv
    python -m research.mt.reduce out/matrix_rules.csv --runs 30 --drop-trivial

縮減：從 N 條測試挑一個子集，要求「涵蓋」某個需求集合：
  - 需求 = 突變體（ground truth；能殺同一批突變體 → 找錯能力不變）
  - 需求 = 關係×種子（便宜替代品：不用跑突變測試，每條測試天生就帶這個標籤）
  用便宜需求縮減、再拿突變體衡量損失，就是「便宜的覆蓋準則到底可不可靠」。

策略：
  greedy         每次挑「新增涵蓋最多需求」的測試（set cover 貪婪）
  hgs            Harrold–Gupta–Soffa：先挑只被單一測試涵蓋的需求對應的測試，再依基數往上
  irreplaceable  先保留不可取代的測試（唯一能涵蓋某需求者），剩下用貪婪補
  random         同大小隨機子集（對照，跑 --runs 次取平均）

排序：total（依涵蓋數）、additional（每次挑新增最多）、relation（R5 → R1 → R2 → R4 → R3，同關係內依 total）、random。
指標 APFD（Average Percentage of Faults Detected），錯 = 突變體。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path


def load_matrix(path: Path) -> tuple[list[dict], list[str], list[list[int]]]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    meta_cols = 4
    mutants = header[meta_cols:]
    tests, matrix = [], []
    for r in rows[1:]:
        tests.append({"id": r[0], "text": r[1], "relation": r[2], "src": r[3]})
        matrix.append([int(x) for x in r[meta_cols:]])
    return tests, mutants, matrix


def requirements(tests: list[dict], matrix: list[list[int]], criterion: str) -> list[set[int]]:
    """每條測試涵蓋哪些需求（用整數 id）。"""
    if criterion == "mutants":
        return [{j for j, v in enumerate(row) if v} for row in matrix]
    if criterion == "relseed":
        ids: dict[str, int] = {}
        out = []
        for t in tests:
            key = t["id"].split(":")[1] + "|" + t["relation"] if ":" in t["id"] else t["id"]
            out.append({ids.setdefault(key, len(ids))})
        return out
    raise ValueError(criterion)


# ---------------------------------------------------------------------------
def greedy(cov: list[set[int]]) -> list[int]:
    universe = set().union(*cov)
    left, chosen = set(universe), []
    while left:
        best = max(range(len(cov)), key=lambda i: len(cov[i] & left))
        if not cov[best] & left:
            break
        chosen.append(best)
        left -= cov[best]
    return chosen


def hgs(cov: list[set[int]]) -> list[int]:
    universe = set().union(*cov)
    by_req: dict[int, set[int]] = defaultdict(set)
    for i, s in enumerate(cov):
        for r in s:
            by_req[r].add(i)
    chosen: list[int] = []
    covered: set[int] = set()
    # 依「涵蓋這個需求的測試數」由少到多處理
    for card in sorted({len(v) for v in by_req.values()}):
        for r in [r for r, v in by_req.items() if len(v) == card]:
            if r in covered:
                continue
            cands = by_req[r]
            # 挑對「尚未涵蓋的需求」貢獻最大的候選
            best = max(cands, key=lambda i: len(cov[i] - covered))
            chosen.append(best)
            covered |= cov[best]
            if covered == universe:
                return chosen
    return chosen


def irreplaceable_first(cov: list[set[int]]) -> list[int]:
    by_req: dict[int, set[int]] = defaultdict(set)
    for i, s in enumerate(cov):
        for r in s:
            by_req[r].add(i)
    chosen = sorted({next(iter(v)) for v in by_req.values() if len(v) == 1})
    covered: set[int] = set().union(*(cov[i] for i in chosen)) if chosen else set()
    universe = set().union(*cov)
    left = universe - covered
    while left:
        best = max(range(len(cov)), key=lambda i: len(cov[i] & left))
        if not cov[best] & left:
            break
        chosen.append(best)
        left -= cov[best]
    return chosen


def kill_set(idx: list[int], mut_cov: list[set[int]]) -> set[int]:
    return set().union(*(mut_cov[i] for i in idx)) if idx else set()


# ---------------------------------------------------------------------------
def apfd(order: list[int], mut_cov: list[set[int]], n_faults: int) -> float:
    """APFD = 1 - (sum of TF_i)/(n*m) + 1/(2n)；TF_i = 第 i 個錯第一次被找到時的測試序號（1-based）。"""
    n = len(order)
    first: dict[int, int] = {}
    for pos, i in enumerate(order, 1):
        for f in mut_cov[i]:
            first.setdefault(f, pos)
    if not first:
        return 0.0
    m = n_faults
    # 沒被找到的錯依慣例算 n+1
    total = sum(first.get(f, n + 1) for f in range(m))
    return 1 - total / (n * m) + 1 / (2 * n)


def order_total(cov: list[set[int]]) -> list[int]:
    return sorted(range(len(cov)), key=lambda i: -len(cov[i]))


def order_additional(cov: list[set[int]]) -> list[int]:
    left = set().union(*cov)
    order, remaining = [], set(range(len(cov)))
    while remaining:
        best = max(remaining, key=lambda i: (len(cov[i] & left), len(cov[i])))
        order.append(best)
        remaining.discard(best)
        left -= cov[best]
        if not left:  # 全涵蓋後重置（Additional 的標準作法）
            left = set().union(*(cov[i] for i in remaining)) if remaining else set()
    return order


def order_relation(tests: list[dict], cov: list[set[int]]) -> list[int]:
    rank = {"R5_near_miss": 0, "R1_synonym": 1, "R2_politeness": 2, "R4_filler": 3, "R3_reorder": 4, "seed": 5}
    return sorted(range(len(tests)), key=lambda i: (rank.get(tests[i]["relation"], 9), -len(cov[i])))


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("matrix")
    ap.add_argument("--runs", type=int, default=30, help="隨機策略重複次數")
    ap.add_argument("--drop-trivial", action="store_true", help="丟掉「每條測試都殺得掉」的突變體（等於沒鑑別力）")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    random.seed(args.seed)

    tests, mutants, matrix = load_matrix(Path(args.matrix))
    n_tests = len(tests)
    # 只留被至少一條測試殺掉的突變體（存活的對縮減沒意義）
    killed_cols = [j for j in range(len(mutants)) if any(row[j] for row in matrix)]
    if args.drop_trivial:
        killed_cols = [j for j in killed_cols if not all(row[j] for row in matrix)]
    col_index = {j: k for k, j in enumerate(killed_cols)}
    mut_cov = [{col_index[j] for j, v in enumerate(row) if v and j in col_index} for row in matrix]
    n_faults = len(killed_cols)
    print(f"測試 {n_tests}，可殺突變體 {n_faults}（原 {len(mutants)}）")

    # ---------------- 縮減 ----------------
    print("\n== 縮減：策略 × 需求準則 → 子集大小、保留的殺傷率 ==")
    print(f"{'criterion':10} {'strategy':14} {'size':>6} {'size%':>7} {'kill%':>7}")
    results: dict = {"reduction": [], "prioritization": []}
    for criterion in ("mutants", "relseed"):
        cov = requirements(tests, matrix, criterion) if criterion == "relseed" else mut_cov
        for name, fn in (("greedy", greedy), ("hgs", hgs), ("irreplaceable", irreplaceable_first)):
            chosen = fn(cov)
            k = len(kill_set(chosen, mut_cov)) / n_faults
            results["reduction"].append({"criterion": criterion, "strategy": name, "size": len(chosen),
                                         "size_ratio": len(chosen) / n_tests, "kill_retained": k})
            print(f"{criterion:10} {name:14} {len(chosen):6d} {100 * len(chosen) / n_tests:6.1f}% {100 * k:6.1f}%")
            # 同大小的隨機子集（對照）
            ks = [len(kill_set(random.sample(range(n_tests), len(chosen)), mut_cov)) / n_faults for _ in range(args.runs)]
            results["reduction"].append({"criterion": criterion, "strategy": f"random(size={len(chosen)})", "size": len(chosen),
                                         "size_ratio": len(chosen) / n_tests, "kill_retained": statistics.mean(ks),
                                         "kill_retained_sd": statistics.pstdev(ks)})
            print(f"{'':10} {'  random同大小':14} {len(chosen):6d} {'':7} {100 * statistics.mean(ks):6.1f}% ±{100 * statistics.pstdev(ks):.1f}")

    # ---------------- 排序 ----------------
    print("\n== 排序：APFD（錯 = 突變體）==")
    orders = {
        "total(mutants)": order_total(mut_cov),
        "additional(mutants)": order_additional(mut_cov),
        "total(relseed)": order_total(requirements(tests, matrix, "relseed")),
        "additional(relseed)": order_additional(requirements(tests, matrix, "relseed")),
        "relation-first": order_relation(tests, mut_cov),
    }
    for name, order in orders.items():
        a = apfd(order, mut_cov, n_faults)
        results["prioritization"].append({"strategy": name, "apfd": a})
        print(f"{name:22} APFD={a:.3f}")
    rs = []
    for _ in range(args.runs):
        o = list(range(n_tests))
        random.shuffle(o)
        rs.append(apfd(o, mut_cov, n_faults))
    results["prioritization"].append({"strategy": "random", "apfd": statistics.mean(rs), "apfd_sd": statistics.pstdev(rs)})
    print(f"{'random':22} APFD={statistics.mean(rs):.3f} ±{statistics.pstdev(rs):.3f}")

    # 前 k% 找到幾 % 的錯（畫曲線用）
    curve = {}
    for name, order in orders.items():
        found, pts = set(), []
        for pos, i in enumerate(order, 1):
            found |= mut_cov[i]
            if pos in (max(1, n_tests // 20), n_tests // 10, n_tests // 4, n_tests // 2, n_tests):
                pts.append((round(pos / n_tests, 2), round(len(found) / n_faults, 3)))
        curve[name] = pts
    results["curve"] = curve
    print("\n== 跑前 5% / 10% / 25% / 50% / 100% 測試找到幾 % 的錯 ==")
    for name, pts in curve.items():
        print(f"{name:22} " + "  ".join(f"{int(p * 100):3d}%→{int(f * 100):3d}%" for p, f in pts))

    out = Path(args.matrix).with_name(Path(args.matrix).stem.replace("matrix_", "reduce_") + ".json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入 {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
