"""蛻變關係（Metamorphic Relations）的定義。

一個關係 = 「怎麼改寫種子句」+「改寫後路由結果應該怎樣」。
路由沒有 oracle（沒人能列出所有句子的正確答案），但關係有：
同義改寫後「應該走同一條路」；近似句「不應該走那條路」。

兩種生成器（rules.py 規則式、llm.py 模型式）都照同一份關係生，才能公平比較。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Relation:
    id: str
    name: str
    instruction: str          # 給 LLM 的改寫指令（規則式生成器各自實作）
    expect: str               # "same"：路由必須與種子相同；"different"：必須不同（近似句）


RELATIONS: list[Relation] = [
    Relation(
        "R1_synonym", "同義改寫",
        "把句子改成意思完全相同的另一種說法：換動詞（打開/開啟/啟動/幫我開）、換句式，"
        "但**目標（程式名、歌名、裝置名、數字）一個字都不能改、不能翻譯、不能加別的動作**。",
        "same",
    ),
    Relation(
        "R2_politeness", "加語助詞 / 禮貌詞",
        "在句子前後加上口語的禮貌詞或語助詞（幫我、請、麻煩、一下、好嗎、可以嗎、謝謝、喔、啦），"
        "句子的意思與目標完全不變。",
        "same",
    ),
    Relation(
        "R3_reorder", "換語序",
        "把句子的語序調換（例如把目標放到前面：「記事本幫我開一下」「晴天播一下」），"
        "口語上要自然，意思與目標完全不變。",
        "same",
    ),
    Relation(
        "R4_filler", "插入無關前綴",
        "在句首加上說話時常出現的無意義前綴（欸、那個、嗯、JARVIS、Jarvis 幫我、對了），"
        "句子其餘部分不變。",
        "same",
    ),
    Relation(
        "R5_near_miss", "近似句（不該觸發）",
        "寫出**包含同樣關鍵字、但意思完全不是這個指令**的句子。例如種子是「打開記事本」，"
        "近似句可以是「打開記事本的教學在哪」「我記事本打不開怎麼辦」「不要打開記事本」。"
        "這些句子不應該讓系統真的去做種子那件事。",
        "different",
    ),
]

BY_ID = {r.id: r for r in RELATIONS}
