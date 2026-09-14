"""E3 第 2 步：存活突變體的人工分類，附可執行的證據。

分類只有三種：
    uncovered   測試沒覆蓋——人可以寫出一句殺得掉的話（killer），這句就是缺的種子
    equivalent  等價——改了但行為不變（分支被同一群組的短詞蓋掉、或 _normalize 早就剝掉那個詞）
    harness     harness 看不到——改的是 try_local 外層或 _dev 的 kwargs，_route 的 Label 不會變

人工判斷寫在 survivors_manual.json；這支把每個 killer 真的丟進原版與突變體跑一次，
證明「uncovered 的 killer 真的殺得掉、equivalent 的 killer 真的殺不掉」。判斷錯了會直接印出來。

    python -m research.mt.survivors --sample 60 --seed 7     # 抽樣印出來給人看
    python -m research.mt.survivors                           # 驗證 survivors_manual.json
    python -m research.mt.survivors --seeds                   # 印出可以直接補進 seeds.json 的句子
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from . import harness, mutation

HERE = Path(__file__).resolve().parent
MANUAL = HERE / "survivors_manual.json"
VERDICTS = ("uncovered", "equivalent", "harness")


def _survivors() -> list[dict]:
    p = mutation.OUT / "mutation_summary.json"
    return json.loads(p.read_text(encoding="utf-8"))["survivors"]


def _mutants_by_id() -> dict[str, mutation.Mutant]:
    src = mutation.ROUTER.read_text(encoding="utf-8")
    return {m.id: m for m in mutation.generate(src)}


def _label(text: str) -> str:
    return str(harness.batch_labels([text])[0])


def _label_under(m: mutation.Mutant, text: str) -> str:
    mod, old = mutation._load_router(m.source, f"chk_{m.id}")
    try:
        return _label(text)
    finally:
        mutation._restore(old)


def cmd_sample(n: int, seed: int) -> int:
    sv = _survivors()
    random.seed(seed)
    src = mutation.ROUTER.read_text(encoding="utf-8").splitlines()
    for m in random.sample(sv, min(n, len(sv))):
        print(f"\n## {m['id']} {m['op']} L{m['line']}\n  before: {m['before'][:160]}\n  after:  {m['after'][:160]}")
        print(f"  ctx:    {src[m['line'] - 1].strip()[:200]}")
    return 0


def verify(quiet: bool = False) -> tuple[int, int, list[tuple]]:
    """回 (判斷與執行不一致的數, router 改過而對不上的數, 每列結果)。"""
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    entries: dict[str, dict] = manual["mutants"]
    mutants = _mutants_by_id()
    bad = stale = 0
    rows = []
    for mid, e in entries.items():
        m = mutants.get(mid)
        if m is None or e["before"] != m.before:
            # router.py 改過：id 位移或那條 regex 變了。這筆先跳過，不算判斷錯（要重跑突變測試再重分類）
            stale += 1
            if not quiet:
                print(f"[{mid}] router.py 改過，對不上：{e['before'][:40]!r}")
            continue
        killer = e.get("killer")
        if e["verdict"] == "harness":
            rows.append((mid, e["verdict"], "-", "", "", ""))
            continue
        orig = _label(killer)
        mut = _label_under(m, killer)
        killed = orig != mut
        ok = killed if e["verdict"] == "uncovered" else not killed
        if not ok:
            bad += 1
        rows.append((mid, e["verdict"], "殺" if killed else "沒殺", killer, orig, mut if killed else ""))
    return bad, stale, rows


def cmd_check(print_seeds: bool) -> int:
    bad, stale, rows = verify()
    entries = json.loads(MANUAL.read_text(encoding="utf-8"))["mutants"]
    w = max(len(r[3]) for r in rows) + 2
    print(f"{'id':6} {'verdict':10} {'結果':4} {'killer':{w}} {'原版':28} 突變體")
    for r in rows:
        flag = "" if r[1] != "uncovered" or r[2] == "殺" else "  ← 判斷錯"
        if r[1] == "equivalent" and r[2] == "殺":
            flag = "  ← 其實殺得掉"
        print(f"{r[0]:6} {r[1]:10} {r[2]:4} {r[3]:{w}} {r[4]:28} {r[5]}{flag}")
    c = Counter(e["verdict"] for e in entries.values())
    print(f"\n{len(entries)} 個：{dict(c)}；判斷與執行結果不一致 {bad} 個；router 改過對不上 {stale} 個")
    if print_seeds:
        print("\n可補進 seeds.json 的句子（uncovered 的 killer，expect = 原版路由）：")
        for r in rows:
            if r[1] == "uncovered" and r[2] == "殺":
                print(json.dumps({"id": f"sv_{r[0]}", "text": r[3], "expect": r[4]}, ensure_ascii=False))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--seeds", action="store_true", help="印出可補進 seeds.json 的句子")
    a = ap.parse_args()
    if a.sample:
        return cmd_sample(a.sample, a.seed)
    return cmd_check(a.seeds)


if __name__ == "__main__":
    sys.exit(main())
