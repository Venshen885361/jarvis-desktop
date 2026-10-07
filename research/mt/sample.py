"""E1 有效性人工抽樣：`valid%` 現在幾乎 100%，因為過濾器只檢查「目標詞還在不在」。
真正的問題是「改寫句有沒有保留原意圖」——這只有人能判。

    python -m research.mt.sample --per 40 --seed 1
        → out/e1_label.csv   給標記者：id, 種子, 關係要求, 改寫句, label（空）, note（空）；順序打亂、看不出來自哪個生成器
        → out/e1_key.json    答案卷：id → 生成器 / 溫度 / seed_id / 關係 / 路由結果 / 違反與否（標記者不要看）

    python -m research.mt.sample --score out/e1_label_A.csv out/e1_label_B.csv
        → 兩位標記者的 Cohen's κ；各生成器的 precision（被標為保留原意圖的比例）；
          「真違反率」= 只算兩人都標 1 的句子裡的違反率（把 LLM 語意漂移造成的假違反拿掉）

標記規則（寫在 CSV 第一列的說明裡）：label = 1 這句還是在要求同一件事（同一個程式 / 歌 / 裝置 / 動作），
0 = 意圖變了或句子不通；近似句關係（R5）的 1 = 這句**確實**不該觸發原本的動作。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from .relations import RELATIONS

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
REL = {r.id: r for r in RELATIONS}


def _gen_of(tag: str) -> str:
    return "rules" if tag == "rules" else "llm"


def _load_all() -> list[dict]:
    rows = []
    for p in sorted(OUT.glob("tests_*.jsonl")):
        tag = p.stem[len("tests_"):]
        if "_rep" in tag:  # E2 的重跑批次不抽，跟第一次是同分佈
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r["tag"] = tag
                rows.append(r)
    return rows


def cmd_sample(per: int, seed: int) -> int:
    rows = [r for r in _load_all() if r["valid"]]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(_gen_of(r["tag"]), r["relation"])].append(r)
    rng = random.Random(seed)
    picked: list[dict] = []
    for key in sorted(groups):
        pool = groups[key]
        picked += rng.sample(pool, min(per, len(pool)))
    rng.shuffle(picked)
    key_out = {}
    with (OUT / "e1_label.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "seed", "relation", "requirement", "text", "label", "note"])
        w.writerow(["說明", "label：1 = 改寫句仍在要求同一件事（同一個程式 / 歌 / 裝置 / 動作）；0 = 意圖變了或句子不通。"
                    "R5 近似句的 1 = 這句確實不該觸發原本的動作。note 選填。", "", "", "", "", ""])
        for i, r in enumerate(picked, 1):
            sid = f"e1-{i:04d}"
            rel = REL[r["relation"]]
            w.writerow([sid, r["seed"], rel.name, rel.instruction, r["text"], "", ""])
            key_out[sid] = {"tag": r["tag"], "gen": _gen_of(r["tag"]), "seed_id": r["seed_id"], "relation": r["relation"],
                            "expect": r["expect"], "got": r["got"], "violation": r["violation"]}
    (OUT / "e1_key.json").write_text(json.dumps(key_out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_g = {k: len(v) for k, v in groups.items()}
    print(f"抽了 {len(picked)} 句 → out/e1_label.csv（給人標）、out/e1_key.json（答案卷）")
    print("各組可抽數：", {f"{g}/{r}": n for (g, r), n in sorted(n_g.items())})
    return 0


def _read_labels(path: Path) -> dict[str, int]:
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not row["id"].startswith("e1-"):
                continue
            v = row["label"].strip()
            if v in ("0", "1"):
                out[row["id"]] = int(v)
    return out


def kappa(a: dict[str, int], b: dict[str, int]) -> tuple[float, int]:
    ids = sorted(set(a) & set(b))
    n = len(ids)
    if n == 0:
        return 0.0, 0
    agree = sum(1 for i in ids if a[i] == b[i]) / n
    pa1 = sum(a[i] for i in ids) / n
    pb1 = sum(b[i] for i in ids) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return (agree - pe) / (1 - pe) if pe < 1 else 1.0, n


def cmd_score(files: list[str]) -> int:
    key = json.loads((OUT / "e1_key.json").read_text(encoding="utf-8"))
    labels = [_read_labels(Path(f)) for f in files]
    if len(labels) >= 2:
        k, n = kappa(labels[0], labels[1])
        print(f"Cohen's κ = {k:.3f}（共同標了 {n} 句）")
    # 共識：兩人都標的取「都是 1」才算保留；只有一人標就用那個人的
    consensus: dict[str, int] = {}
    for sid in key:
        vs = [lab[sid] for lab in labels if sid in lab]
        if vs:
            consensus[sid] = int(all(vs))
    by = defaultdict(lambda: {"n": 0, "kept": 0, "viol_raw": 0, "viol_true": 0})
    for sid, v in consensus.items():
        k_ = key[sid]
        for g in {k_["gen"], f"{k_['gen']}/{k_['relation']}", k_["tag"]}:   # set：rules 的 gen 和 tag 同名，不能算兩次
            d = by[g]
            d["n"] += 1
            d["kept"] += v
            d["viol_raw"] += k_["violation"]
            d["viol_true"] += k_["violation"] and v
    print(f"{'組':40} {'n':>4} {'precision':>10} {'原違反率':>8} {'真違反率':>8}")
    for g in sorted(by):
        d = by[g]
        print(f"{g:40} {d['n']:4d} {d['kept'] / d['n']:10.1%} {d['viol_raw'] / d['n']:8.1%} "
              f"{(d['viol_true'] / d['kept'] if d['kept'] else 0):8.1%}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=40, help="每個 生成器×關係 抽幾句")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--score", nargs="+", metavar="LABELED_CSV")
    a = ap.parse_args()
    if a.score:
        return cmd_score(a.score)
    return cmd_sample(a.per, a.seed)


if __name__ == "__main__":
    sys.exit(main())
