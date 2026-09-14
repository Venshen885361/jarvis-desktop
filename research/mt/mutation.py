"""突變測試（E3）：對 jarvis/router.py 產生突變體，算「測試 × 突變體」矩陣。

為什麼自己寫而不用 mutmut：受測對象的邏輯幾乎都在 regex 字串和關鍵字 tuple 裡，
一般突變工具只改運算子和常數，碰不到 `(?:打開|開啟|開)` 裡的一個分支。
這裡的突變運算子是針對「意圖路由」設計的：

| 運算子 | 例子 | 模擬的真實錯誤 |
|---|---|---|
| ALT_DEL  | `(?:打開|開啟|開)` → `(?:打開|開)` | 少收一個同義詞 |
| LOOK_DEL | `開(?!心|會)` → `開` | 忘了排除誤觸 |
| OPT_DEL  | `(?:幫我)?` → `(?:幫我)` | 前綴從可選變必要 |
| KW_DEL   | `("幾點", "現在時間", "報時")` → 少一個 | 關鍵字表漏字 |
| NUM      | `len(text) <= 6` → `<= 5` / `<= 7` | 邊界值錯 |
| CMP      | `<=` → `<` | 邊界值錯 |
| BOOL     | `and` ↔ `or`、刪 `not` | 條件寫反 |

殺（kill）的定義：某條測試在原版路由到 X、在突變體路由到 ≠X（或炸掉）。
測試來源：`out/tests_*.jsonl` 裡原版**通過**的句子（valid 且非 violation）+ seeds。

    python -m research.mt.mutation                       # 用 out/ 裡所有批次
    python -m research.mt.mutation --tags rules gemini-3.5-flash-lite_T0.7
    python -m research.mt.mutation --list                # 只列突變體不跑

輸出（out/）：mutants.json、matrix_<tag>.csv（每列一測試、每欄一突變體、1 = 殺）、mutation_summary.json
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import re
import sys
import time
import token
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path

from . import harness

ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "jarvis" / "router.py"
OUT = Path(__file__).resolve().parent / "out"


@dataclass
class Mutant:
    id: str
    op: str
    line: int
    before: str
    after: str
    source: str  # 完整突變後原始碼（不寫進 json）


# ---------------------------------------------------------------------------
# 產生突變體
# ---------------------------------------------------------------------------
_ALT_GROUP = re.compile(r"\((\?:|\?P<\w+>|\?!|\?=)?([^()]*\|[^()]*)\)")   # 最內層、含 | 的括號
_LOOKAHEAD = re.compile(r"\(\?![^()]*\)")
_OPT_GROUP = re.compile(r"\)\?")          # `)?` → `)`
_TUPLE_STR = re.compile(r'\(\s*("[^"]+"(?:\s*,\s*"[^"]+")+)\s*,?\s*\)')  # ("a", "b", ...)


def _replace_span(src: str, start: int, end: int, new: str) -> str:
    return src[:start] + new + src[end:]


def _string_mutants(src: str, tok: tokenize.TokenInfo, offsets: list[int]) -> list[tuple[str, str, str]]:
    """對一個 STRING token 產生 (op, before, after)；回傳的是整個 token 的新字串。"""
    s = tok.string
    outs: list[tuple[str, str, str]] = []
    # ALT_DEL：每個含 | 的最內層群組，逐一刪掉一個分支
    for g in _ALT_GROUP.finditer(s):
        body = g.group(2)
        parts = body.split("|")
        if len(parts) < 2:
            continue
        for i in range(len(parts)):
            if not parts[i]:
                continue
            new_body = "|".join(parts[:i] + parts[i + 1:])
            new_group = "(" + (g.group(1) or "") + new_body + ")"
            outs.append(("ALT_DEL", g.group(0), new_group))
    # LOOK_DEL
    for g in _LOOKAHEAD.finditer(s):
        outs.append(("LOOK_DEL", g.group(0), ""))
    # OPT_DEL：`)?` → `)`（regex 字串裡才有意義）
    if s.startswith(("r", "rf", "fr", "R")):
        for _g in _OPT_GROUP.finditer(s):
            outs.append(("OPT_DEL", ")?", ")"))
    return outs


def generate(src: str) -> list[Mutant]:
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    lines = src.splitlines(keepends=True)
    line_start = [0]
    for ln in lines:
        line_start.append(line_start[-1] + len(ln))

    def abs_pos(row: int, col: int) -> int:
        return line_start[row - 1] + col

    mutants: list[Mutant] = []
    seen: set[str] = set()

    def add(op: str, row: int, before: str, after: str, new_src: str) -> None:
        key = new_src  # 同一行同一種改法可能出現多次（`)?` 一行三個），用結果去重最準
        if key in seen or new_src == src:
            return
        seen.add(key)
        mutants.append(Mutant(f"m{len(mutants):04d}", op, row, before[:60], after[:60], new_src))

    for t in toks:
        a, b = abs_pos(*t.start), abs_pos(*t.end)
        if t.type == token.STRING:
            for op, before, after in _string_mutants(src, t, line_start):
                # 同一 token 內 before 可能出現多次；每個出現位置各一個突變體
                for m in re.finditer(re.escape(before), t.string):
                    new_tok = t.string[:m.start()] + after + t.string[m.end():]
                    add(op, t.start[0], before, after, _replace_span(src, a, b, new_tok))
        elif t.type == token.NUMBER and t.string.isdigit():
            n = int(t.string)
            for d in (-1, 1):
                if n + d >= 0:
                    add("NUM", t.start[0], t.string, str(n + d), _replace_span(src, a, b, str(n + d)))
        elif t.type == token.OP and t.string in ("<=", ">=", "<", ">"):
            alt = {"<=": "<", ">=": ">", "<": "<=", ">": ">="}[t.string]
            add("CMP", t.start[0], t.string, alt, _replace_span(src, a, b, alt))
        elif t.type == token.NAME and t.string in ("and", "or"):
            alt = "or" if t.string == "and" else "and"
            add("BOOL", t.start[0], t.string, alt, _replace_span(src, a, b, alt))
        elif t.type == token.NAME and t.string == "not":
            # 刪掉 not（連同後面一個空白）
            add("BOOL", t.start[0], "not", "", _replace_span(src, a, b + 1, ""))

    # KW_DEL：關鍵字 tuple 逐一刪一個字串（在原始碼層級做，跳過 import / 註解）
    for m in _TUPLE_STR.finditer(src):
        row = src.count("\n", 0, m.start()) + 1
        items = re.findall(r'"[^"]+"', m.group(1))
        if len(items) < 2:
            continue
        for i in range(len(items)):
            new_tuple = "(" + ", ".join(items[:i] + items[i + 1:]) + ")"
            add("KW_DEL", row, items[i], "", _replace_span(src, m.start(), m.end(), new_tuple))
    return mutants


# ---------------------------------------------------------------------------
# 載入突變體、跑測試
# ---------------------------------------------------------------------------
def _load_router(source: str, tag: str):
    """把一份 router 原始碼當成 jarvis.router 載入（相對 import 靠 __package__）。"""
    path = OUT / "_mutant_tmp" / f"router_{tag}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("jarvis.router", path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "jarvis"
    old = sys.modules.get("jarvis.router")
    sys.modules["jarvis.router"] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        if old is not None:
            sys.modules["jarvis.router"] = old
        raise
    return mod, old


def _restore(old) -> None:
    if old is not None:
        sys.modules["jarvis.router"] = old


def load_tests(tags: list[str]) -> list[dict]:
    """原版通過的測試（valid 且非 violation）+ seeds；去重（同句只留一次）。"""
    tests: list[dict] = []
    seen: set[str] = set()
    seeds = json.loads((Path(__file__).resolve().parent / "seeds.json").read_text(encoding="utf-8"))["seeds"]
    for s in seeds:
        if s["text"] not in seen:
            seen.add(s["text"])
            src_tag = "seed_sv" if s["id"].startswith("sv_") else "seed"   # sv_：從存活突變體反推的 killer
            tests.append({"id": f"seed:{s['id']}", "text": s["text"], "expect": s["expect"], "src": src_tag, "relation": "seed"})
    for tag in tags:
        p = OUT / f"tests_{tag}.jsonl"
        if not p.is_file():
            print(f"[skip] {p.name} 不存在")
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if not r["valid"] or r["violation"] or r["text"] in seen:
                continue
            seen.add(r["text"])
            tests.append({"id": f"{tag}:{r['seed_id']}:{r['relation']}:{len(tests)}", "text": r["text"],
                          "expect": r["got"], "src": tag, "relation": r["relation"]})
    return tests


def run_matrix(tests: list[dict], mutants: list[Mutant], src: str) -> tuple[list[list[int]], list[str]]:
    """回 (matrix[test][mutant], 無法載入的突變體 id)。原版先跑一次確認 expect。"""
    labels_orig = harness.batch_labels([t["text"] for t in tests])
    bad = [t for t, lab in zip(tests, labels_orig, strict=True) if str(lab) != t["expect"]]
    if bad:
        print(f"[warn] {len(bad)} 條測試在原版就不等於記錄的結果（router 改過？），改用現在的結果當基準")
        for t, lab in zip(tests, labels_orig, strict=True):
            t["expect"] = str(lab)
    matrix = [[0] * len(mutants) for _ in tests]
    broken: list[str] = []
    t0 = time.time()
    for j, m in enumerate(mutants):
        try:
            mod, old = _load_router(m.source, m.id)
        except Exception:
            broken.append(m.id)  # 語法壞掉的突變體：等於「全部殺掉」，不計入
            continue
        try:
            labels = harness.batch_labels([t["text"] for t in tests])
        finally:
            _restore(old)
        for i, (t, lab) in enumerate(zip(tests, labels, strict=True)):
            if str(lab) != t["expect"]:
                matrix[i][j] = 1
        if (j + 1) % 50 == 0:
            print(f"  {j + 1}/{len(mutants)} 突變體，{time.time() - t0:.0f}s")
    return matrix, broken


def summarize(tests: list[dict], mutants_meta: list[dict], matrix: list[list[int]], broken: list[str], tag: str) -> dict:
    alive_idx = [j for j, m in enumerate(mutants_meta) if m["id"] not in broken]
    killed = [j for j in alive_idx if any(row[j] for row in matrix)]
    survived = [mutants_meta[j] for j in alive_idx if j not in killed]
    score = len(killed) / len(alive_idx) if alive_idx else 0
    per_src: dict[str, set[int]] = {}
    for t, row in zip(tests, matrix, strict=True):
        per_src.setdefault(t["src"], set()).update(j for j, v in enumerate(row) if v)
    summary = {
        "tag": tag, "tests": len(tests), "mutants": len(mutants_meta), "broken": len(broken),
        "killed": len(killed), "survived": len(survived), "mutation_score": round(score, 3),
        "killed_by_source": {k: len(v) for k, v in per_src.items()},
        "survivors": survived,
        "zero_kill_tests": sum(1 for row in matrix if not any(row)),
    }
    (OUT / "mutation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n可用突變體 {len(alive_idx)}（{len(broken)} 個語法壞掉）；殺掉 {len(killed)}，存活 {len(survived)}，突變分數 {score:.3f}")
    print("各來源殺掉的突變體數：", summary["killed_by_source"])
    print(f"一個突變體都殺不掉的測試：{summary['zero_kill_tests']} / {len(tests)}")
    ops: dict[str, int] = {}
    for m in survived:
        ops[m["op"]] = ops.get(m["op"], 0) + 1
    print("存活的突變體依運算子：", ops)
    return summary


def merge_parts() -> int:
    parts = sorted(OUT.glob("matrix_part_*.csv"), key=lambda p: int(p.stem.split("_")[-1].split("-")[0]))
    if not parts:
        print("沒有 matrix_part_*.csv")
        return 1
    header: list[str] = []
    rows: list[list[str]] = []
    for k, p in enumerate(parts):
        with p.open(encoding="utf-8") as f:
            data = list(csv.reader(f))
        if k == 0:
            header, rows = data[0], [r[:4] for r in data[1:]]
            cols = [r[4:] for r in data[1:]]
        else:
            assert [r[0] for r in data[1:]] == [r[0] for r in rows], f"{p.name} 的測試順序不同"
            header += data[0][4:]
            for i, r in enumerate(data[1:]):
                cols[i] += r[4:]
    meta = json.loads((OUT / "mutants.json").read_text(encoding="utf-8"))
    ids = header[4:]
    meta = [m for m in meta if m["id"] in set(ids)]
    tag = "merged"
    with (OUT / f"matrix_{tag}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r, c in zip(rows, cols, strict=True):
            w.writerow(r + c)
    tests = [{"id": r[0], "text": r[1], "relation": r[2], "src": r[3]} for r in rows]
    matrix = [[int(x) for x in c] for c in cols]
    print(f"合併 {len(parts)} 段 → matrix_{tag}.csv（{len(tests)} 測試 × {len(ids)} 突變體）")
    summarize(tests, meta, matrix, [], tag)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="*", default=None, help="要用的批次（預設 out/ 裡全部）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 個突變體（debug）")
    ap.add_argument("--range", type=int, nargs=2, metavar=("FROM", "TO"), help="只跑第 FROM..TO-1 個突變體（分段跑用），寫 matrix_part_FROM-TO.csv")
    ap.add_argument("--merge", action="store_true", help="把 out/matrix_part_*.csv 合併成完整矩陣並算統計")
    args = ap.parse_args()
    if args.merge:
        return merge_parts()

    src = ROUTER.read_text(encoding="utf-8")
    mutants = generate(src)
    if args.limit:
        mutants = mutants[: args.limit]
    all_mutants = mutants
    by_op: dict[str, int] = {}
    for m in mutants:
        by_op[m.op] = by_op.get(m.op, 0) + 1
    print(f"突變體 {len(mutants)}：{by_op}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mutants.json").write_text(
        json.dumps([{k: v for k, v in asdict(m).items() if k != "source"} for m in all_mutants], ensure_ascii=False, indent=1),
        encoding="utf-8")
    if args.range:
        mutants = mutants[args.range[0]: args.range[1]]
    if args.list:
        for m in mutants:
            print(f"{m.id} L{m.line:<4} {m.op:8} {m.before!r} → {m.after!r}")
        return 0

    tags = args.tags or sorted(p.stem[len("tests_"):] for p in OUT.glob("tests_*.jsonl"))
    tests = load_tests(tags)
    print(f"測試 {len(tests)} 條（來源：{', '.join(tags) or '只有 seeds'}）")
    matrix, broken = run_matrix(tests, mutants, src)

    tag = "+".join(tags) if tags else "seeds"
    name = f"matrix_part_{args.range[0]}-{args.range[1]}.csv" if args.range else f"matrix_{tag}.csv"
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["test_id", "text", "relation", "src"] + [m.id for m in mutants])
        for t, row in zip(tests, matrix, strict=True):
            w.writerow([t["id"], t["text"], t["relation"], t["src"]] + row)
    if args.range:
        print(f"寫入 {name}（{len(mutants)} / {len(all_mutants)} 個突變體）；全部跑完後 --merge")
        return 0

    summarize(tests, [{k: v for k, v in asdict(m).items() if k != "source"} for m in mutants], matrix, broken, tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
