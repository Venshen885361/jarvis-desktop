"""第二個受測對象：Home Assistant 的 zh-TW 意圖模板（home-assistant-intents + hassil）。

為什麼選它：跟 router.py 一樣是「規則 → 意圖」的自然語言路由，但是別人寫的、正式產品在用的、
繁體中文、520 條模板，而且語法（`(a|b)` 分支、`[可選]`）跟我的突變運算子一一對應。
同一套蛻變關係、生成器、縮減 / 排序流程跑在它上面，看結論是不是只對我的 router 成立。

    pip install hassil home-assistant-intents
    python -m research.mt.hass --seeds              # 從模板自動展開種子句 → seeds_hass.json
    python -m research.mt.run --subject hass --gen rules --seeds research/mt/seeds_hass.json --tag-suffix _hass
    python -m research.mt.hass_mutation             # 模板突變體 × 測試 矩陣（跟 mutation.py 同格式，reduce / subsume 直接用）

標籤：`<意圖名>:<area>/<domain 或 device_class 或 name>`，例如 HassTurnOn:客廳/light；沒辨識到 = Label("none")。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .harness import Label

HERE = Path(__file__).resolve().parent
LANG = "zh-TW"

# 固定的裝置 / 區域清單（真實安裝裡來自使用者的設定；這裡給一組固定的，讓實驗可重現）
AREAS = ["客廳", "房間", "廚房", "浴室", "書房"]
FLOORS = ["一樓", "二樓"]
NAMES = ["客廳燈", "冷氣", "電視", "風扇", "門鎖", "窗簾", "音響", "掃地機器人", "咖啡機"]
# 展開模板時填的 slot 值（只拿來造種子句）
FILL = {"area": "客廳", "floor": "一樓", "name": "客廳燈", "temperature": "26", "brightness": "50", "volume": "30",
        "position": "50", "fan_speed": "60", "color_temperature": "3000", "timer_minutes": "5", "timer_hours": "1",
        "timer_seconds": "30", "search_query": "周杰倫", "message": "吃飯了", "zone": "家", "shopping_list_item": "牛奶",
        "todo_list_item": "繳電費", "timer_command": "關燈", "timer_name": "煮麵", "timer_half": "半"}

_intents = None
_slot_lists = None


def raw() -> dict:
    import home_assistant_intents as hai

    return hai.get_intents(LANG)


def build(data: dict | None = None):
    """把 intents dict 編成 hassil 物件；data=None 用原版。突變體就是改過的 dict。"""
    from hassil import Intents
    from hassil.intents import TextSlotList

    global _slot_lists
    if _slot_lists is None:
        _slot_lists = {"area": TextSlotList.from_strings(AREAS), "floor": TextSlotList.from_strings(FLOORS),
                       "name": TextSlotList.from_strings(NAMES)}
    return Intents.from_dict(data or raw())


def _label_of(result) -> Label:
    if result is None:
        return Label("none")
    ents = {k: str(v.value) for k, v in result.entities.items()}
    target = "/".join(x for x in (ents.get("area") or ents.get("floor") or ents.get("name") or "",
                                  ents.get("device_class") or ents.get("domain") or "") if x)
    # 數值類 slot 也要比（26 度 vs 27 度是不同指令）
    extra = [f"{k}={v}" for k, v in sorted(ents.items()) if k not in ("area", "floor", "name", "device_class", "domain")]
    if extra:
        target = (target + "|" if target else "") + ",".join(extra)
    return Label(result.intent.name, target)


def batch_labels(texts: list[str], intents=None) -> list[Label]:
    from hassil import recognize

    global _intents
    if intents is None:
        if _intents is None:
            _intents = build()
        intents = _intents
    out = []
    for t in texts:
        try:
            r = recognize(t, intents, slot_lists=_slot_lists, intent_context={"area": "客廳"})
        except Exception as e:  # 模板壞掉也是結果
            out.append(Label("error", type(e).__name__))
            continue
        out.append(_label_of(r))
    return out


def route_label(text: str) -> Label:
    return batch_labels([text])[0]


def same_route(a: Label, b: Label) -> bool:
    return (a.kind, a.target.strip().lower()) == (b.kind, b.target.strip().lower())


# ---------------------------------------------------------------- 從模板展開種子句
_RULE = re.compile(r"<(\w+)>")
_SLOT = re.compile(r"\{(\w+)(?::\w+)?\}")


def _first(expr: str, rules: dict[str, str], lists: dict, depth: int = 0) -> str:
    """hassil 模板 → 一句：每個 (a|b) 取第一個、[可選] 丟掉、<rule> 展開、{slot} 填值。"""
    if depth > 8:
        return expr
    expr = _RULE.sub(lambda m: f"({rules[m.group(1)]})" if m.group(1) in rules else "", expr)
    # 先處理可選 [ ... ]（可能巢狀）：丟掉
    while True:
        new = re.sub(r"\[[^\[\]]*\]", "", expr)
        if new == expr:
            break
        expr = new
    # 再處理 ( a | b )：取第一個
    while True:
        new = re.sub(r"\(([^()]*)\)", lambda m: m.group(1).split("|")[0], expr)
        if new == expr:
            break
        expr = new

    def fill(m):
        name = m.group(1)
        if name in FILL:
            return FILL[name]
        lst = lists.get(name, {})
        if "values" in lst and lst["values"]:
            v = lst["values"][0]
            s = v["in"] if isinstance(v, dict) else str(v)
            return _first(s, rules, lists, depth + 1)
        if "range" in lst:
            return str(lst["range"].get("from", 1) + 1)
        return name
    expr = _SLOT.sub(fill, expr)
    return re.sub(r"\s+", "", expr)


def make_seeds(per_intent: int = 2) -> list[dict]:
    d = raw()
    rules, lists = d["expansion_rules"], d["lists"]
    seeds = []
    for name, intent in d["intents"].items():
        n = 0
        for data in intent["data"]:
            for s in data.get("sentences", []):
                text = _first(s, rules, lists)
                lab = route_label(text)
                if lab.kind != name:   # 展開出來自己都認不得（模板語法沒展好或要別的 context）就跳過
                    continue
                seeds.append({"id": f"{name}_{n}", "text": text, "expect": str(lab), "template": s})
                n += 1
                break
            if n >= per_intent:
                break
    return seeds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", action="store_true", help="產生 seeds_hass.json")
    ap.add_argument("--per-intent", type=int, default=2)
    ap.add_argument("--try", dest="try_text", nargs="*", help="試幾句")
    a = ap.parse_args()
    if a.try_text:
        for t in a.try_text:
            print(f"{t!r:24} {route_label(t)}")
        return 0
    if a.seeds:
        seeds = make_seeds(a.per_intent)
        out = {"_doc": f"第二受測對象 Home Assistant {LANG} 意圖（home-assistant-intents）。種子由每個意圖的前 {a.per_intent} 條模板自動展開（分支取第一個、可選丟掉、slot 填固定值），expect 是原版的辨識結果。",
               "seeds": seeds}
        (HERE / "seeds_hass.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{len(seeds)} 條種子 → seeds_hass.json")
        for s in seeds:
            print(f"  {s['text']!r:28} {s['expect']}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
