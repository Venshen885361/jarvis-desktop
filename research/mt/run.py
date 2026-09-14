"""跑一整批蛻變測試：生成 → 過濾 → 路由 → 判定 → 報表。

    # 規則式（對照組，免費、確定性）
    python -m research.mt.run --gen rules

    # LLM，掃溫度（每個溫度一批；同參數第二次跑走快取）
    python -m research.mt.run --gen llm --model gemini-3.5-flash-lite --temperature 0 0.3 0.7 1.0 --n 5

    # 只看違反的案例
    python -m research.mt.run --gen rules --show-violations

輸出（research/mt/out/）：
    tests_<tag>.jsonl    每一條生成的測試（含路由結果與判定），可以直接進 pandas
    summary_<tag>.json   各關係的統計
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from . import llm, rules
from .harness import Label, route_label, same_route
from .relations import RELATIONS

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def _parse_label(s: str) -> Label:
    kind, _, target = s.partition(":")
    return Label(kind, target)


_NO_NEAR_MISS_KINDS = {"info", "model", "greeting"}
_FREE_TEXT_KINDS = {"open_application", "open_folder", "open_url", "youtube_play", "install_app",
                    "install_steam_game", "download_file", "focus_window", "home_control", "write_clipboard"}


def _target_tokens(label: Label) -> list[str]:
    """種子的「目標」拆成必須出現在改寫句裡的詞：Label('open_application','記事本') → ['記事本']；
    home_control 的 '客廳燈=off' → ['客廳燈']；google:台北天氣 → ['台北天氣']。沒有目標的關係（時間、招呼）回 []。"""
    t = label.target
    # 目標是使用者說出來的自由文字（程式名、歌名、網址、裝置名）才檢查；set_volume:up 這種列舉值不在句子裡
    if not t or label.kind not in _FREE_TEXT_KINDS:
        return []
    t = t.split("=", 1)[0]
    t = t.split(":", 1)[1] if t.startswith("google:") else t
    return [t.strip()] if t.strip() and t.strip() != "?" else []


def _valid(text: str, seed_label: Label, expect: str) -> tuple[bool, str]:
    """便宜的有效性過濾（不是 LLM 裁判）：長度、有沒有把目標弄丟。近似句不檢查目標。"""
    if not (1 <= len(text) <= 40):
        return False, "length"
    if expect == "same":
        for tok in _target_tokens(seed_label):
            if tok.lower() not in text.lower():
                return False, "target_lost"
    return True, ""


def _distinct2(texts: list[str]) -> float:
    """字元 bigram 的 distinct-2：多樣性的粗量法（1 = 全不重複）。"""
    grams, total = set(), 0
    for t in texts:
        t = re.sub(r"\s+", "", t)
        for i in range(len(t) - 1):
            grams.add(t[i:i + 2])
            total += 1
    return round(len(grams) / total, 3) if total else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", choices=["rules", "llm"], required=True)
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--temperature", type=float, nargs="*", default=[0.7])
    ap.add_argument("--n", type=int, default=5, help="每個 種子×關係 生幾句")
    ap.add_argument("--relations", nargs="*", default=[r.id for r in RELATIONS])
    ap.add_argument("--seeds", default=str(HERE / "seeds.json"))
    ap.add_argument("--show-violations", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    seeds = json.loads(Path(args.seeds).read_text(encoding="utf-8"))["seeds"]
    rels = [r for r in RELATIONS if r.id in args.relations]
    temps = args.temperature if args.gen == "llm" else [None]
    OUT.mkdir(parents=True, exist_ok=True)

    for temp in temps:
        tag = "rules" if temp is None else f"{args.model}_T{temp:g}"
        rows: list[dict] = []
        gen_fail = 0
        for seed in seeds:
            seed_label = _parse_label(seed["expect"])
            for rel in rels:
                # 近似句關係只對「動作」有意義：純問答 / 交給模型的種子改寫後本來就還是問答，不算錯
                if rel.expect == "different" and seed_label.kind in _NO_NEAR_MISS_KINDS:
                    continue
                # 模板生成器對非動作句做同義 / 換語序會拆出無意義的句子（「開心一點」→「打開心一點」）；LLM 不受此限
                if args.gen == "rules" and rel.id in ("R1_synonym", "R3_reorder") and seed_label.kind in _NO_NEAR_MISS_KINDS:
                    continue
                if args.gen == "rules":
                    items = rules.generate(seed["text"], rel, args.n)
                else:
                    r = llm.generate(seed["text"], rel, args.n, model=args.model, temperature=temp,
                                     use_cache=not args.no_cache)
                    items = r["items"]
                    gen_fail += 0 if r["ok"] else 1
                seen = set()
                for text in items:
                    text = re.sub(r"\s+", " ", text).strip()
                    if text in seen or text == seed["text"]:
                        continue
                    seen.add(text)
                    ok, why = _valid(text, seed_label, rel.expect)
                    got = route_label(text)
                    same = same_route(got, seed_label)
                    violation = (not same) if rel.expect == "same" else same
                    rows.append({
                        "seed_id": seed["id"], "seed": seed["text"], "relation": rel.id, "expect": rel.expect,
                        "text": text, "seed_label": str(seed_label), "got": str(got),
                        "valid": ok, "invalid_reason": why, "violation": bool(ok and violation),
                    })

        # ---- 寫檔 ----
        with (OUT / f"tests_{tag}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        # ---- 統計 ----
        summary: dict = {"tag": tag, "gen": args.gen, "model": None if temp is None else args.model,
                         "temperature": temp, "n_per_pair": args.n, "gen_failures": gen_fail, "relations": {}}
        by_rel: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_rel[r["relation"]].append(r)
        print(f"\n== {tag} ==")
        print(f"{'relation':16} {'gen':>5} {'valid':>6} {'valid%':>7} {'viol':>5} {'viol%':>7} {'dist2':>6}")
        for rel in rels:
            rs = by_rel[rel.id]
            valid = [r for r in rs if r["valid"]]
            viol = [r for r in valid if r["violation"]]
            d2 = _distinct2([r["text"] for r in valid])
            summary["relations"][rel.id] = {
                "generated": len(rs), "valid": len(valid), "violations": len(viol),
                "valid_rate": round(len(valid) / len(rs), 3) if rs else 0,
                "violation_rate": round(len(viol) / len(valid), 3) if valid else 0,
                "distinct2": d2,
            }
            print(f"{rel.id:16} {len(rs):5d} {len(valid):6d} {100 * summary['relations'][rel.id]['valid_rate']:6.1f}% "
                  f"{len(viol):5d} {100 * summary['relations'][rel.id]['violation_rate']:6.1f}% {d2:6.3f}")
        tot_valid = sum(1 for r in rows if r["valid"])
        tot_viol = sum(1 for r in rows if r["violation"])
        summary["total"] = {"generated": len(rows), "valid": tot_valid, "violations": tot_viol}
        print(f"{'TOTAL':16} {len(rows):5d} {tot_valid:6d} {'':7} {tot_viol:5d}")
        if gen_fail:
            print(f"（LLM 生成失敗 {gen_fail} 次：看 out/cache 裡 ok=false 的檔）")
        (OUT / f"summary_{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        if args.show_violations:
            print("\n-- 違反蛻變關係的案例（valid 且 violation）--")
            for r in rows:
                if r["violation"]:
                    arrow = "≠" if r["expect"] == "same" else "＝(不該)"
                    print(f"[{r['relation']}] {r['seed']!r} → {r['text']!r}: {r['got']} {arrow} {r['seed_label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
