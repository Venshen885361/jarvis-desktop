"""E6 版本回歸：同一批測試、同一套突變器，跑在 router.py 的每個歷史版本上。

回答 RQ5「找到的錯修回去，路由變好多少？會不會修出新的錯？」——每個版本一列：
各批次的違反數 / 去重的錯數、種子答對幾條、突變分數（用**該版本自己的**突變體）。

    python -m research.mt.versions                     # 預設 5 個版本、全部批次、含突變分數（慢：每版幾分鐘）
    python -m research.mt.versions --no-mutation       # 只算違反（幾秒）
    python -m research.mt.versions --versions v0=5065037 v4=a7630d9

版本的原始碼直接從 git 取（git show <sha>:jarvis/router.py），不用 checkout；
測試用 out/ 裡現在的 tests_*.jsonl（句子不變、期望不變，只有「路由到哪」重算）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import harness, mutation
from .harness import Label, same_route

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ROOT = HERE.parents[1]

# 版本 = 每一輪回饋後的 router（README 的「第 N 輪」）
DEFAULT_VERSIONS = [
    ("v0", "5065037", "第一次跑蛻變測試時的 router"),
    ("v1", "e4a452a", "第一輪：正規化、否定 / 問句守門、URL 只認 ASCII"),
    ("v2", "86e82d0", "第二輪：意願句、受詞在前、平台片語；媒體鍵 / 時間只認整句"),
    ("v3", "3fae9e2", "第三輪：鎖定 / 切換 / 家電 / 媒體鍵統一 regex、剝問法外圍詞、搜尋+問資訊走純問答"),
    ("v4", "a7630d9", "近似句種子後：否定守門前移、_ACTION_START lookahead"),
]
DEFAULT_TAGS = ["rules", "gemini-3.5-flash-lite_T0", "gemini-3.5-flash-lite_T0.3",
                "gemini-3.5-flash-lite_T0.7", "gemini-3.5-flash-lite_T1"]


def _source_at(sha: str) -> str:
    return subprocess.run(["git", "show", f"{sha}:jarvis/router.py"], cwd=ROOT, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def _parse_label(s: str) -> Label:
    kind, _, target = s.partition(":")
    return Label(kind, target)


def _load_rows(tag: str) -> list[dict]:
    p = OUT / f"tests_{tag}.jsonl"
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(name: str, sha: str, tags: list[str], seeds: list[dict], with_mutation: bool) -> dict:
    src = _source_at(sha)
    mod, old = mutation._load_router(src, f"ver_{name}")
    try:
        res: dict = {"version": name, "sha": sha, "batches": {}}
        # 種子：現在的 seeds.json 在該版本答對幾條（41 條原始 / 46 條 killer 分開算）
        labs = harness.batch_labels([s["text"] for s in seeds])
        ok_orig = sum(1 for s, lab in zip(seeds, labs, strict=True) if not s["id"].startswith("sv_") and str(lab) == s["expect"])
        ok_sv = sum(1 for s, lab in zip(seeds, labs, strict=True) if s["id"].startswith("sv_") and str(lab) == s["expect"])
        n_orig = sum(1 for s in seeds if not s["id"].startswith("sv_"))
        res["seeds_ok"] = {"original": f"{ok_orig}/{n_orig}", "sv": f"{ok_sv}/{len(seeds) - n_orig}"}
        # 各批次：句子不變，重算路由與違反
        for tag in tags:
            rows = _load_rows(tag)
            if not rows:
                continue
            got = harness.batch_labels([r["text"] for r in rows])
            viol = 0
            faults: set[tuple] = set()
            for r, g in zip(rows, got, strict=True):
                if not r["valid"]:
                    continue
                same = same_route(g, _parse_label(r["seed_label"]))
                v = (not same) if r["expect"] == "same" else same
                if v:
                    viol += 1
                    faults.add((r["seed_id"], r["relation"], g.kind))
            res["batches"][tag] = {"tests": len(rows), "violations": viol, "faults": len(faults)}
        if with_mutation:
            t0 = time.time()
            muts = mutation.generate(src)
            tests = mutation.load_tests(tags)
            matrix, broken = mutation.run_matrix(tests, muts, src)
            alive = [j for j, m in enumerate(muts) if m.id not in broken]
            killed = sum(1 for j in alive if any(row[j] for row in matrix))
            res["mutation"] = {"mutants": len(alive), "killed": killed,
                               "score": round(killed / len(alive), 3) if alive else 0, "seconds": int(time.time() - t0)}
        return res
    finally:
        mutation._restore(old)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", nargs="*", default=None, help="name=sha …")
    ap.add_argument("--tags", nargs="*", default=DEFAULT_TAGS)
    ap.add_argument("--no-mutation", action="store_true")
    a = ap.parse_args()
    versions = [(v.split("=")[0], v.split("=")[1], "") for v in a.versions] if a.versions else DEFAULT_VERSIONS
    seeds = json.loads((HERE / "seeds.json").read_text(encoding="utf-8"))["seeds"]
    import jarvis.router  # noqa: F401  先載入現行版本，之後每個歷史版本輪流替換

    results = []
    for name, sha, note in versions:
        print(f"== {name} {sha} {note}", flush=True)
        r = evaluate(name, sha, a.tags, seeds, not a.no_mutation)
        r["note"] = note
        results.append(r)
        print("  ", json.dumps({k: v for k, v in r.items() if k not in ("note",)}, ensure_ascii=False), flush=True)
    (OUT / "versions.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    # markdown 表
    short = {"rules": "rules", "gemini-3.5-flash-lite_T0": "T0", "gemini-3.5-flash-lite_T0.3": "T0.3",
             "gemini-3.5-flash-lite_T0.7": "T0.7", "gemini-3.5-flash-lite_T1": "T1"}
    cols = [t for t in a.tags if any(t in r["batches"] for r in results)]
    head = "| 版本 | 種子答對（原始 / killer） | " + " | ".join(f"{short.get(t, t)} 違反 / 錯" for t in cols)
    if not a.no_mutation:
        head += " | 突變分數"
    print("\n" + head + " |")
    print("|" + "---|" * (head.count("|") + 1))
    for r in results:
        cells = [f"{r['version']} `{r['sha']}`", f"{r['seeds_ok']['original']} / {r['seeds_ok']['sv']}"]
        for t in cols:
            b = r["batches"].get(t)
            cells.append(f"{b['violations']} / {b['faults']}" if b else "-")
        if not a.no_mutation:
            m = r["mutation"]
            cells.append(f"{m['score']}（{m['killed']} / {m['mutants']}）")
        print("| " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
