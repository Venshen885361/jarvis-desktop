"""一鍵重現：把報告裡的每個數字從 checked-in 的資料重新算一遍（不需要 API 金鑰）。

    python -m research.mt.demo            # 快速版：約 1–2 分鐘（突變測試只跑前 200 個突變體）
    python -m research.mt.demo --full     # 完整版：全部 927 個突變體 + E7 + E10（裝了 hassil 才跑），約 20 分鐘
    python -m research.mt.demo --list     # 只列出會跑哪些步驟

資料：research/mt/data/ 是實驗的快照（生成的測試句、LLM 的 API 快取 2,364 筆含 n=20 六批、模型路由快取 3,962 筆、人工標記、
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
        ("RQ2 放大 n=20：四個溫度（讀快取，六批 23,000 句）",
         [*m, "research.mt.run", "--gen", "llm", "--temperature", "0", "0.3", "0.7", "1.0", "--n", "20", "--seed-filter", ORIG]),
        ("RQ2 放大 n=20：T=0 重跑第 1 次（讀快取）",
         [*m, "research.mt.run", "--gen", "llm", "--temperature", "0", "--n", "20", "--rep", "1", "--seed-filter", ORIG]),
        ("RQ2 放大 n=20：T=0 重跑第 2 次（讀快取）",
         [*m, "research.mt.run", "--gen", "llm", "--temperature", "0", "--n", "20", "--rep", "2", "--seed-filter", ORIG]),
        ("RQ2 放大 n=20：批次比較",
         [*m, "research.mt.compare", *[t + "_n20" for t in LLM], "gemini-3.5-flash-lite_T0_rep1_n20", "gemini-3.5-flash-lite_T0_rep2_n20"]),
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
        ("RQ8 真實使用紀錄當種子（24 條，4 條現行路由就錯）",
         [*m, "research.mt.run", "--gen", "rules", "--seeds", str(HERE / "seeds_usage.json"), "--tag-suffix", "_usage", "--show-violations"]),
        ("RQ5 五個歷史版本的違反數（需要 git）",
         [*m, "research.mt.versions", "--no-mutation"]),
        ("RQ7 突變體包含關係：dominator、最小突變分數（用突變測試那一步的矩陣）",
         [*m, "research.mt.subsume", str(OUT / f"matrix_{'+'.join(tags)}.csv")]),
        ("RQ10 第三受測對象：Gemini 當路由器——87 條種子答對幾條、同句兩次一致率（讀快取）",
         [*m, "research.mt.llm_router", "--seeds", str(HERE / "seeds.json")]),
        ("RQ10 規則式批次 × 模型路由，基準 = 模型自己對種子的路由（讀快取）",
         [*m, "research.mt.run", "--subject", "llm", "--gen", "rules", "--seeds", str(HERE / "seeds.json"), "--tag-suffix", "_llmr", "--baseline", "own"]),
        ("RQ10 模型批次 T0 × 模型路由（讀快取）",
         [*m, "research.mt.run", "--subject", "llm", "--gen", "llm", "--temperature", "0", "--seed-filter", ORIG, "--tag-suffix", "_llmr", "--baseline", "own"]),
        ("RQ10 prompt 突變矩陣 80 × 187（讀快取）",
         [*m, "research.mt.llm_router_mutation", "--tags", "rules_llmr", "--per-relation", "20"]),
        ("RQ10 縮減 / 排序", [*m, "research.mt.reduce", str(OUT / "matrix_llmr.csv"), "--drop-trivial"]),
        ("RQ10 包含關係", [*m, "research.mt.subsume", str(OUT / "matrix_llmr.csv"), "--mutants", str(OUT / "mutants_llmr.json")]),
        *_e12_steps(m),
    ] + ([("RQ6 跨版本可轉移性：v4 決定 → v5 評估（需要 git，兩個版本各算一次矩陣，約 4 分鐘）",
           [*m, "research.mt.transfer", "--from", "v4=7040c54", "--to", "v5=3f5e658"])] if full else []) + (_hass_steps(m) if full else [])


def _e12_steps(m: list[str]) -> list[tuple[str, list[str]]]:
    """E12 RQ10 通則檢驗：換 prompt 寫法（noex / names）、換模型（flash）。全部讀快取。"""
    out: list[tuple[str, list[str]]] = []
    for style in ("noex", "names"):
        out += [
            (f"E12 寫法 {style}：87 條種子（讀快取）",
             [*m, "research.mt.llm_router", "--seeds", str(HERE / "seeds.json"), "--style", style]),
            (f"E12 寫法 {style}：規則式批次一致性（讀快取）",
             [*m, "research.mt.run", "--subject", "llm", "--router-style", style, "--gen", "rules", "--seeds", str(HERE / "seeds.json"), "--tag-suffix", f"_llmr_{style}", "--baseline", "own"]),
            (f"E12 寫法 {style}：模型批次 T0 一致性（讀快取）",
             [*m, "research.mt.run", "--subject", "llm", "--router-style", style, "--gen", "llm", "--temperature", "0", "--seed-filter", ORIG, "--tag-suffix", f"_llmr_{style}", "--baseline", "own"]),
        ]
    fl = ["--router-model", "gemini-3.5-flash"]
    out += [
        ("E12 換模型 flash：87 條種子（讀快取）",
         [*m, "research.mt.llm_router", "--seeds", str(HERE / "seeds.json"), "--model", "gemini-3.5-flash"]),
        ("E12 換模型 flash：規則式批次 n=20 一致性（讀快取）",
         [*m, "research.mt.run", "--subject", "llm", *fl, "--gen", "rules", "--n", "20", "--tag-suffix", "_llmr_flash", "--baseline", "own"]),
        ("E12 換模型 flash：模型批次 T0 一致性（讀快取）",
         [*m, "research.mt.run", "--subject", "llm", *fl, "--gen", "llm", "--temperature", "0", "--seed-filter", ORIG, "--tag-suffix", "_llmr_flash", "--baseline", "own"]),
        ("E12 換模型 flash：prompt 突變矩陣 80 × 187（讀快取）",
         [*m, "research.mt.llm_router_mutation", "--model", "gemini-3.5-flash", "--tags", "rules_llmr_flash_own", "--per-relation", "20", "--out-tag", "llmr_flash"]),
        ("E12 換模型 flash：包含關係 + 縮減 / 排序",
         [*m, "research.mt.subsume", str(OUT / "matrix_llmr_flash.csv"), "--mutants", str(OUT / "mutants_llmr_flash.json")]),
    ]
    return out


def _hass_steps(m: list[str]) -> list[tuple[str, list[str]]]:
    """RQ9 第二受測對象（Home Assistant zh-TW）：要 `pip install hassil home-assistant-intents`，沒裝就跳過。"""
    try:
        import hassil  # noqa: F401
        import home_assistant_intents  # noqa: F401
    except ImportError:
        print("[skip] RQ9 需要 hassil + home-assistant-intents（pip install hassil home-assistant-intents）")
        return []
    hm = OUT / "matrix_hass_sampled.csv"
    return [
        ("RQ9 第二受測對象：規則式生成器 × Home Assistant zh-TW（985 句）",
         [*m, "research.mt.run", "--subject", "hass", "--gen", "rules", "--seeds", str(HERE / "seeds_hass.json"), "--tag-suffix", "_hass"]),
        ("RQ9 模板突變體 × 1 454 條測試（約 8 分鐘）",
         [*m, "research.mt.hass_mutation", "--seed-files", "seeds_hass.json", "seeds_hass_sampled.json", "--out-tag", "hass_sampled"]),
        ("RQ9 縮減與排序", [*m, "research.mt.reduce", str(hm), "--drop-trivial"]),
        ("RQ9 包含關係", [*m, "research.mt.subsume", str(hm), "--mutants", str(OUT / "mutants_hass.json")]),
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
