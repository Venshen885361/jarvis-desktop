"""E7 跨版本可轉移性：在版本 A 上縮減 / 排序的測試集，拿到版本 B 還有多少用？

回歸測試的真正問題不是「在這一版縮減後保留多少殺傷力」（那是在同一份矩陣上自己對自己），
而是「縮減是在舊版決定的，程式改了之後那份子集還殺不殺得到新版的錯」。
做法：
    1. 分別載入 router 的版本 A、B（git show），各自產突變體、各自算 測試 × 突變體 矩陣（同一批測試）。
    2. 在 A 的矩陣上縮減（greedy / HGS / irreplaceable）與排序（total / additional）。
    3. 把 A 選出來的子集 / 順序套到 B 的矩陣上：殺傷保留率（相對於全集在 B 上殺的）、APFD、
       同大小隨機子集在 B 上的保留率當對照。
    4. 反過來（B → A）也算一次，看是不是對稱。

    python -m research.mt.transfer --from v4=a7630d9 --to v5=3f5e658
    python -m research.mt.transfer --from v3=3fae9e2 --to v5=3f5e658 --tags rules gemini-3.5-flash-lite_T0.7
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import time

from . import mutation, reduce, versions

OUT = mutation.OUT
DEFAULT_TAGS = ["rules", "gemini-3.5-flash-lite_T0", "gemini-3.5-flash-lite_T0.3", "gemini-3.5-flash-lite_T0.7", "gemini-3.5-flash-lite_T1"]


def matrix_for(name: str, sha: str, tests: list[dict]) -> tuple[list[list[int]], list[str]]:
    """版本 sha 的 測試 × 突變體 矩陣（存成 out/matrix_<name>.csv，下次直接讀）。"""
    path = OUT / f"matrix_{name}.csv"
    if path.is_file():
        rows = list(csv.reader(path.open(encoding="utf-8")))
        if [r[1] for r in rows[1:]] == [t["text"] for t in tests]:
            print(f"[{name}] 讀 {path.name}")
            return [[int(x) for x in r[4:]] for r in rows[1:]], rows[0][4:]
    src = versions._source_at(sha)
    mod, old = mutation._load_router(src, f"ver_{name}")
    try:
        import jarvis.router  # noqa: F401

        t0 = time.time()
        muts = mutation.generate(src)
        matrix, broken = mutation.run_matrix(tests, muts, src)
        keep = [j for j, m in enumerate(muts) if m.id not in broken]
        matrix = [[row[j] for j in keep] for row in matrix]
        ids = [muts[j].id for j in keep]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "text", "relation", "src"] + ids)
            for t, row in zip(tests, matrix, strict=True):
                w.writerow([t["id"], t["text"], t["relation"], t["src"]] + row)
        print(f"[{name}] {len(tests)} 測試 × {len(ids)} 突變體，{time.time() - t0:.0f} 秒 → {path.name}")
        return matrix, ids
    finally:
        mutation._restore(old)


def cov_of(matrix: list[list[int]], drop_trivial: bool = True) -> tuple[list[set[int]], int]:
    """每條測試殺哪些突變體；丟掉「每條測試都殺」的，回 (cov, 可殺突變體數)。"""
    n_tests = len(matrix)
    counts = [sum(row[j] for row in matrix) for j in range(len(matrix[0]))]
    keep = [j for j, c in enumerate(counts) if c and (not drop_trivial or c < n_tests)]
    idx = {j: k for k, j in enumerate(keep)}
    cov = [{idx[j] for j in keep if row[j]} for row in matrix]
    return cov, len(keep)


def transfer(a_name: str, cov_a: list[set[int]], b_name: str, cov_b: list[set[int]], n_b: int,
             tests: list[dict], runs: int, rng: random.Random) -> list[dict]:
    full_b = reduce.kill_set(list(range(len(cov_b))), cov_b)
    out = []
    for strategy, fn in (("greedy", reduce.greedy), ("hgs", reduce.hgs), ("irreplaceable", reduce.irreplaceable_first)):
        chosen = fn(cov_a)
        kept_a = len(reduce.kill_set(chosen, cov_a)) / len(reduce.kill_set(list(range(len(cov_a))), cov_a))
        kept_b = len(reduce.kill_set(chosen, cov_b) & full_b) / len(full_b)
        rand = [len(reduce.kill_set(rng.sample(range(len(cov_b)), len(chosen)), cov_b) & full_b) / len(full_b) for _ in range(runs)]
        out.append({"kind": "reduction", "strategy": strategy, "size": len(chosen),
                    f"kept_on_{a_name}": round(kept_a, 3), f"kept_on_{b_name}": round(kept_b, 3),
                    f"random_on_{b_name}": round(statistics.mean(rand), 3), "random_sd": round(statistics.pstdev(rand), 3)})
    for strategy, order in (("total", reduce.order_total(cov_a)), ("additional", reduce.order_additional(cov_a)),
                            ("relation-first", reduce.order_relation(tests, cov_a))):
        out.append({"kind": "prioritization", "strategy": strategy,
                    f"apfd_on_{a_name}": round(reduce.apfd(order, cov_a, len(set().union(*cov_a))), 3),
                    f"apfd_on_{b_name}": round(reduce.apfd(order, cov_b, n_b), 3)})
    rand_apfd = [reduce.apfd(rng.sample(range(len(cov_b)), len(cov_b)), cov_b, n_b) for _ in range(runs)]
    out.append({"kind": "prioritization", "strategy": "random", f"apfd_on_{b_name}": round(statistics.mean(rand_apfd), 3),
                "random_sd": round(statistics.pstdev(rand_apfd), 3)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="name=sha，縮減 / 排序在這版決定")
    ap.add_argument("--to", dest="dst", required=True, help="name=sha，套到這版評估")
    ap.add_argument("--tags", nargs="*", default=DEFAULT_TAGS)
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    a_name, a_sha = a.src.split("=")
    b_name, b_sha = a.dst.split("=")
    rng = random.Random(a.seed)

    tests = mutation.load_tests(a.tags)
    # 測試的「期望」在不同版本不同，矩陣各自以該版原版結果為基準（run_matrix 會重算），這裡只要句子一樣
    m_a, _ = matrix_for(a_name, a_sha, tests)
    m_b, _ = matrix_for(b_name, b_sha, tests)
    cov_a, n_a = cov_of(m_a)
    cov_b, n_b = cov_of(m_b)
    print(f"\n{a_name}：{n_a} 個可殺突變體；{b_name}：{n_b} 個可殺突變體；測試 {len(tests)} 條")

    res = {"from": a.src, "to": a.dst, "tests": len(tests), "forward": transfer(a_name, cov_a, b_name, cov_b, n_b, tests, a.runs, rng),
           "backward": transfer(b_name, cov_b, a_name, cov_a, n_a, tests, a.runs, rng)}
    (OUT / f"transfer_{a_name}_to_{b_name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    for direction, rows in (("forward", res["forward"]), ("backward", res["backward"])):
        src_n, dst_n = (a_name, b_name) if direction == "forward" else (b_name, a_name)
        print(f"\n== 在 {src_n} 決定 → 套到 {dst_n} ==")
        print(f"{'策略':16} {'大小':>5} {'在' + src_n + '保留':>10} {'在' + dst_n + '保留':>10} {'同大小隨機':>10}")
        for r in rows:
            if r["kind"] == "reduction":
                print(f"{r['strategy']:16} {r['size']:5d} {r[f'kept_on_{src_n}']:10.1%} {r[f'kept_on_{dst_n}']:10.1%} "
                      f"{r[f'random_on_{dst_n}']:9.1%}±{r['random_sd']:.3f}")
        print(f"{'排序':16} {'':>5} {'APFD@' + src_n:>10} {'APFD@' + dst_n:>10}")
        for r in rows:
            if r["kind"] == "prioritization":
                print(f"{r['strategy']:16} {'':>5} {r.get(f'apfd_on_{src_n}', float('nan')):10.3f} {r[f'apfd_on_{dst_n}']:10.3f}"
                      + (f" ±{r['random_sd']:.3f}" if "random_sd" in r else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
