"""一鍵重現：把報告裡的每個數字從 checked-in 的資料重新算一遍（不需要 API 金鑰）。

    python -m research.mt.demo            # 快速版：約 1–2 分鐘（突變測試只跑前 200 個突變體）
    python -m research.mt.demo --full     # 完整版：全部 927 個突變體，約 6–10 分鐘
    python -m research.mt.demo --list     # 只列出會跑哪些步驟

資料：research/mt/data/ 是 2026-09-14 那次實驗的快照（生成的測試句、LLM 的 API 快取、人工標記、
各版本結果）。第一次跑會複製到 research/mt/out/（out/ 不進 git）。有快取，所以 `--gen llm`
不會真的打 Gemini；想重新生成才需要 GEMINI_API_KEY 和 --no-cache。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"
OUT = HERE / "out"

LLM = ["gemini-3.5-flash-lite_T0", "gemini-3.5-flash-lite_T0.3", "gemini-3.5-flash-lite_T0.7", "gemini-3.5-flash-lite_T1"]
ORIG = '^(?!sv_)'   # 只用原始 41 條種子（跟報告的 E2 表一致）


def restore() -> None:
    """data/ → out/：只補 out/ 裡沒有的檔，不覆蓋你自己跑出來的結果。"""
    if not DATA.is_dir():
        sys.exit(f"沒有 {DATA}：請用 git 拉完整的 repo")
    n = 0
    for src in DATA.rglob("*"):
        if src.is_dir():
            continue
        dst = OUT / src.relative_to(DATA)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    print(f"[data] 從快照補了 {n} 個檔到 {OUT.relative_to(ROOT)}")


def steps(full: bool) -> list[tuple[str, list[str]]]:
    m = [sys.executable, "-m"]
    mut_extra = [] if full else ["--limit", "200"]
    tags = ["rules", *LLM]
    return [
        ("RQ1 規則式生成 → 違反（1 秒）",
         [*m, "research.mt.run", "--gen", "rules"]),
        ("RQ1/RQ2 四個溫度（讀快取，不打 API）",
         [*m, "research.mt.run", "--gen", "llm", "--temperature", "0", "0.3", "0.7", "1.0", "--seed-filter", ORIG]),
        ("RQ2 T=0 重跑第 1 次（讀快取）",
         [*m, "research.mt.run", "--gen", "llm", "--temperature", "0", "--rep", "1", "--seed-filter", ORIG]),
        ("RQ2 T=0 重跑第 2 次（讀快取）",
         [*m, "research.mt.run", "--gen", "llm", "--temperature", "0", "--rep", "2", "--seed-filter", ORIG]),
        ("RQ2 批次比較：句子 / 錯集合 Jaccard",
         [*m, "research.mt.compare", *LLM, "gemini-3.5-flash-lite_T0_rep1", "gemini-3.5-flash-lite_T0_rep2"]),
        ("RQ1 E1 人工標記 → 各生成器 precision",
         [*m, "research.mt.sample", "--score", str(OUT / "e1_label_claude.csv")]),
        ("RQ3 突變測試：測試 × 突變體矩陣" + ("（全部 927）" if full else "（前 200 個，--full 跑全部）"),
         [*m, "research.mt.mutation", "--tags", *tags, *mut_extra]),
        ("RQ3 每批次殺傷（不受去重順序影響）",
         [*m, "research.mt.mutation", "--by-batch", str(OUT / f"matrix_{'+'.join(tags)}.csv"), "--tags", *tags]),
        ("RQ3/RQ4 縮減與排序（greedy / HGS / irreplaceable / 隨機；APFD）",
         [*m, "research.mt.reduce", str(OUT / f"matrix_{'+'.join(tags)}.csv"), "--drop-trivial"]),
        ("E3 存活突變體的人工分類：每個 killer 真的跑一次",
         [*m, "research.mt.survivors"]),
        ("RQ5 五個歷史版本的違反數（需要 git）",
         [*m, "research.mt.versions", "--no-mutation"]),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="突變測試跑全部 927 個突變體")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", type=int, nargs="*", help="只跑第幾步（1 起算）")
    a = ap.parse_args()
    plan = steps(a.full)
    if a.list:
        for i, (name, cmd) in enumerate(plan, 1):
            print(f"{i:2d}. {name}\n    {' '.join(cmd[2:])}")
        return 0
    restore()
    t_all = time.time()
    failed: list[str] = []
    for i, (name, cmd) in enumerate(plan, 1):
        if a.only and i not in a.only:
            continue
        print(f"\n{'=' * 72}\n[{i}/{len(plan)}] {name}\n$ python -m {' '.join(cmd[2:])}\n{'=' * 72}", flush=True)
        t0 = time.time()
        r = subprocess.run(cmd, cwd=ROOT)
        print(f"--- {time.time() - t0:.0f} 秒，exit {r.returncode}")
        if r.returncode != 0:
            failed.append(name)
    print(f"\n全部 {time.time() - t_all:.0f} 秒；失敗 {len(failed)} 步" + (f"：{failed}" if failed else ""))
    print("對照：research/mt/README.md 的表，以及報告「肆、結果與討論」。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
