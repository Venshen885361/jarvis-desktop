"""規則式（模板）生成器 —— LLM 生成的對照組。

同一份蛻變關係，用固定模板產生改寫；沒有隨機性、不花錢、可完全重現。
它故意「笨」：模板寫得到的句型才有，寫不到的就沒有。
LLM 生成好不好，就是跟這一組比。
"""

from __future__ import annotations

import itertools
import re

from .relations import Relation

# 動詞同義表：種子句裡出現左邊的詞，就換成右邊每一個
_VERB_SYNONYMS = {
    "打開": ["開啟", "啟動", "開", "幫我開", "執行"],
    "開啟": ["打開", "啟動", "開", "幫我開"],
    "開": ["打開", "開啟", "啟動"],
    "播放": ["播", "放", "放一下", "幫我播"],
    "播": ["播放", "放", "放一下"],
    "放": ["播", "播放"],
    "下載": ["安裝", "幫我裝", "下載並安裝"],
    "安裝": ["下載", "幫我裝", "裝"],
    "裝": ["安裝", "下載"],
    "搜尋": ["google一下", "上網查", "查一下網路"],
    "切換到": ["切到", "跳到", "回到"],
    "關掉": ["關閉", "關"],
    "鎖定螢幕": ["鎖屏", "鎖電腦"],
}
_PREFIX_POLITE = ["幫我", "請", "麻煩", "請幫我", "可以幫我"]
_SUFFIX_POLITE = ["一下", "好嗎", "可以嗎", "謝謝", "喔", "啦", "一下好嗎"]
_FILLERS = ["欸", "那個", "嗯", "JARVIS", "Jarvis 幫我", "對了", "欸那個"]
_NEAR_MISS_TEMPLATES = [
    "{text}的教學在哪",
    "我{text}都打不開怎麼辦",
    "不要{text}",
    "剛剛{text}了嗎",
    "{text}會怎樣",
    "我不想{text}",
    "為什麼{text}會失敗",
]


def _split_verb(text: str) -> tuple[str, str, str] | None:
    """找出句首的動詞片語（含「幫我 / 請」前綴），回 (prefix, verb, rest)。"""
    m = re.match(r"^(幫我|請)?\s*(打開|開啟|播放|下載|安裝|搜尋|切換到|鎖定螢幕|開|播|放|裝|關掉)\s*(.*)$", text)
    if not m:
        return None
    return (m.group(1) or "", m.group(2), m.group(3))


def generate(seed_text: str, relation: Relation, n: int) -> list[str]:
    out: list[str] = []
    if relation.id == "R1_synonym":
        parts = _split_verb(seed_text)
        if parts:
            _, verb, rest = parts
            for alt in _VERB_SYNONYMS.get(verb, []):
                out.append(f"{alt}{rest}" if not rest.startswith(" ") else f"{alt}{rest}")
    elif relation.id == "R2_politeness":
        for p, s in itertools.product([""] + _PREFIX_POLITE, [""] + _SUFFIX_POLITE):
            if p or s:
                out.append(f"{p}{seed_text}{s}")
    elif relation.id == "R3_reorder":
        parts = _split_verb(seed_text)
        if parts and parts[2].strip():
            _, verb, rest = parts
            rest = rest.strip()
            out += [f"{rest}{verb}一下", f"{rest}幫我{verb}", f"把{rest}{verb}", f"{rest}，{verb}"]
    elif relation.id == "R4_filler":
        for f in _FILLERS:
            out.append(f"{f} {seed_text}")
            out.append(f"{f}，{seed_text}")
    elif relation.id == "R5_near_miss":
        for t in _NEAR_MISS_TEMPLATES:
            out.append(t.format(text=seed_text))
    # 去重、去掉跟種子一樣的
    seen, uniq = set(), []
    for s in out:
        s = re.sub(r"\s+", " ", s).strip()
        if s and s != seed_text and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:n]
