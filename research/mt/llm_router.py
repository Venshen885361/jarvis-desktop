"""第三個受測對象（E11）：用模型做意圖路由——同一句話交給 Gemini 分類到跟 router.py 一樣的標籤空間。

為什麼：router.py 是 regex 找關鍵字、Home Assistant 是整句匹配，兩個都是規則式。
「用模型當 router」是另一種常見做法（prompt 列出意圖 → 模型回 JSON）。同一套蛻變關係、縮減 / 排序、
包含關係跑在它上面，看：模型路由在 R2 / R4（禮貌語、填充詞）是不是天生就會、在 R5（近似句）是不是反而過度觸發、
以及它自己的非確定性（同一句問兩次答案一不一樣）跟成本（每句一次 API）。

標籤空間 = harness.Label 的 kind / target（見 harness.py 開頭）；prompt 把每個意圖寫成一行「名稱：定義｜target 格式｜例句」。
突變測試對象是 **prompt**（llm_router_mutation.py）：刪一個意圖、刪一條規則、刪例句——跟刪 regex 分支是同一件事。

    python -m research.mt.llm_router --try "幫我開一下記事本" "音量調大是要按哪個按鈕"
    python -m research.mt.llm_router --seeds research/mt/seeds.json          # 87 條種子答對幾條 + 同句問兩次的一致率
    python -m research.mt.run --subject llm --gen rules --seeds research/mt/seeds.json --tag-suffix _llmr
    python -m research.mt.run --subject llm --gen llm --temperature 0 --seed-filter "^(?!sv_)" --tag-suffix _llmr

快取在 out/cache_llmrouter/（鍵 = 模型 | 溫度 | prompt 的 hash | 句子 | rep），同一句不重打。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .harness import Label
from .harness import same_route as _same_route

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "out" / "cache_llmrouter"
MODEL = os.environ.get("JARVIS_MT_ROUTER_MODEL", "gemini-3.5-flash-lite")
# E12：換模型 / 換 prompt 寫法看 RQ10 的結論是不是通則。style：full（名稱｜定義｜格式｜例句 + 規則）、
# noex（沒例句）、nodef（沒定義）、names（只有名稱與格式）、norules（full 但沒有全域規則）
STYLES = ("full", "noex", "nodef", "names", "norules")
CONFIG = {"model": MODEL, "style": os.environ.get("JARVIS_MT_ROUTER_STYLE", "full")}


def configure(model: str | None = None, style: str | None = None) -> None:
    if model:
        CONFIG["model"] = model
    if style:
        if style not in STYLES:
            raise SystemExit(f"style 要是 {STYLES} 之一")
        CONFIG["style"] = style
TEMPERATURE = 0.0
WORKERS = 4

# 每個意圖一行：名稱｜定義｜target 格式｜例句 → 突變體就是刪掉其中一行 / 一欄
INTENTS: list[tuple[str, str, str, str]] = [
    ("open_application", "開啟電腦上的程式", "程式名（去掉「程式 / 軟體 / app」）", "打開記事本 → open_application:記事本"),
    ("open_folder", "開啟資料夾", "資料夾名（去掉「資料夾」）", "打開下載資料夾 → open_folder:下載"),
    ("open_url", "開網址，或上 Google 搜尋", "網址；搜尋寫 google:查詢字", "搜尋 python 教學 → open_url:google:python 教學；開啟github.com → open_url:github.com"),
    ("youtube_play", "用 YouTube 播歌 / 影片", "歌名或關鍵字（去掉「的歌」）", "播放周杰倫的歌 → youtube_play:周杰倫"),
    ("install_app", "下載 / 安裝程式", "程式名", "下載 Discord → install_app:Discord"),
    ("install_steam_game", "用 Steam 安裝或開遊戲", "遊戲名", "用 Steam 安裝 Terraria → install_steam_game:Terraria"),
    ("home_control", "控制家電（燈 / 冷氣 / 電視…）", "裝置=on 或 裝置=off 或 裝置=set=數字", "把客廳燈關掉 → home_control:客廳燈=off；冷氣設 26 度 → home_control:冷氣=set=26"),
    ("set_volume", "調音量 / 靜音", "up / down / mute", "音量調大 → set_volume:up；切換到靜音 → set_volume:mute"),
    ("focus_window", "切換到某個視窗", "視窗 / 程式名", "切換到 Chrome → focus_window:Chrome"),
    ("device_switch", "切換要控制的裝置（手機 / 電腦）", "手機 或 電腦", "切換到手機 → device_switch:手機"),
    ("lock_screen", "鎖定螢幕", "空", "鎖定螢幕 → lock_screen"),
    ("computer:key", "媒體鍵", "nexttrack / prevtrack / playpause", "下一首 → computer:key:nexttrack；播放 → computer:key:playpause"),
    ("switch_input_method", "切換輸入法", "english / chinese / toggle_lang", "輸入法切成英文 → switch_input_method:english"),
    ("read_clipboard", "唸出剪貼簿內容", "空", "剪貼簿裡有什麼 → read_clipboard"),
    ("lens_search", "以圖搜圖（Google Lens）", "空", "以圖搜圖 → lens_search"),
    ("camera_search", "用鏡頭拍東西來查", "空", "用鏡頭查這是什麼 → camera_search"),
    ("time", "問現在幾點", "空", "現在幾點 → time"),
    ("date", "問今天日期 / 星期幾", "空", "今天星期幾 → date"),
    ("math", "算算術", "空", "1加1等於多少 → math"),
    ("weather", "問天氣", "原句", "查一下台北天氣 → weather:查台北天氣"),
    ("greeting", "打招呼", "空", "早安 → greeting"),
    ("hide", "把桌寵藏起來", "空", "藏起來 → hide"),
    ("device_list", "問有哪些裝置", "空", "有哪些裝置 → device_list"),
    ("info", "純問答：在問知識、推薦、怎麼做、為什麼，不是要執行動作", "空", "附近有什麼好吃的 → info；音量調大是要按哪個按鈕 → info"),
    ("model", "以上都不是、或不確定、或句子不是指令（否定句、閒聊、抱怨）", "空", "不要打開記事本 → model；今天很開心 → model"),
]

RULES: list[str] = [
    "句首的填充詞（欸、那個、嗯、Jarvis）和客氣話（幫我、請、麻煩）不影響意圖，也不是 target 的一部分。",
    "句尾的語助詞和禮貌語（一下、好嗎、謝謝、拜託你了喔）不是 target 的一部分。",
    "受詞在前（「記事本幫我打開」「把 Chrome 啟動起來」）跟動詞在前意思一樣。",
    "否定句（不要、別、取消）、問句（怎麼用、是要按哪個、了嗎）、陳述句（上次、不小心、一直失敗）都不是指令：問知識回 info，其他回 model。",
    "不確定就回 model，不要猜一個動作。",
]

_HEADER = "你是語音助理的意圖路由器。使用者講一句中文，你要判斷它屬於哪個意圖，只輸出 JSON 物件 {\"kind\": \"<意圖名稱>\", \"target\": \"<target 或空字串>\"}，不要任何說明。\n\n意圖（{cols}）："
# 標題列固定寫「名稱：定義｜target 格式｜例子」，不隨 --style 變：E12 的 noex / names 批次（各 ~2,450 次 API）是用這個標題跑的，
# 改標題 = 換 prompt = 快取全部失效（prompt sha 97fe544d8759 / f836553a62a0）。少一欄只在每行少那一段。
_COLS = dict.fromkeys(STYLES, "名稱：定義｜target 格式｜例子")


def build_prompt(intents: list[tuple[str, str, str, str]] | None = None, rules: list[str] | None = None, style: str | None = None) -> str:
    style = style or CONFIG["style"]
    intents = INTENTS if intents is None else intents
    rules = RULES if rules is None else rules
    if style == "norules":
        rules = []
    lines = [_HEADER.replace("{cols}", _COLS[style])]
    for name, desc, fmt, ex in intents:
        if style == "noex":
            lines.append(f"- {name}：{desc}｜{fmt}")
        elif style == "nodef":
            lines.append(f"- {name}：{fmt}｜{ex}")
        elif style == "names":
            lines.append(f"- {name}：{fmt}")
        else:
            lines.append(f"- {name}：{desc}｜{fmt}｜{ex}")
    if rules:
        lines.append("\n規則：")
        lines += [f"- {r}" for r in rules]
    return "\n".join(lines)


DEFAULT_PROMPT = build_prompt(style="full")


def default_prompt() -> str:
    return build_prompt()


def _key(prompt: str, text: str, rep: int, model: str, temperature: float) -> Path:
    ph = hashlib.sha1(prompt.encode()).hexdigest()[:12]
    h = hashlib.sha1(f"{model}|{temperature}|{ph}|{text}|rep{rep}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _parse(raw: str) -> Label:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return Label("error", "parse")
        try:
            d = json.loads(m.group())
        except json.JSONDecodeError:
            return Label("error", "parse")
    if not isinstance(d, dict):
        return Label("error", "parse")
    kind = str(d.get("kind", "")).strip()
    target = str(d.get("target", "") or "").strip()
    if kind.startswith("computer:key:"):      # 模型把 target 寫進 kind
        kind, target = "computer:key", kind.split(":", 2)[2]
    if kind == "open_url" and target.lower().startswith("google:"):
        target = "google:" + target[7:].strip()
    return Label(kind, target)


def _ask(prompt: str, text: str, *, rep: int = 0, model: str | None = None, temperature: float = TEMPERATURE, use_cache: bool = True) -> dict:
    model = model or CONFIG["model"]
    key = _key(prompt, text, rep, model, temperature)
    if use_cache and key.is_file():
        cached = json.loads(key.read_text(encoding="utf-8"))
        if cached["kind"] != "error":       # 舊快取裡的解析失敗不算，重問
            return cached
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("需要 GEMINI_API_KEY（.env 或環境變數）")
    client = genai.Client(api_key=api_key)
    t0 = time.time()
    # 會思考的模型（gemini-3.5-flash）把 thinking 算進 output tokens：200 不夠就被截斷、JSON 解析失敗。
    # 關掉思考（路由不需要）、放寬上限；舊版 SDK 沒有 ThinkingConfig 就退回不設
    cfg = {"system_instruction": prompt, "temperature": temperature, "max_output_tokens": 1024, "response_mime_type": "application/json"}
    try:
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except AttributeError:
        pass
    try:
        resp = client.models.generate_content(model=model, contents=text, config=types.GenerateContentConfig(**cfg))
        raw = resp.text or ""
    except Exception as e:
        raw = f"__ERROR__ {type(e).__name__}: {e}"
    lab = Label("error", "api") if raw.startswith("__ERROR__") else _parse(raw)
    res = {"text": text, "kind": lab.kind, "target": lab.target, "raw": raw[:500],
           "meta": {"model": model, "temperature": temperature, "rep": rep, "prompt_sha": hashlib.sha1(prompt.encode()).hexdigest()[:12],
                    "ms": int((time.time() - t0) * 1000), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}}
    if use_cache and lab.kind != "error":      # 解析失敗 / API 錯誤不進快取，下次重問
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def batch_labels(texts: list[str], prompt: str | None = None, *, rep: int = 0, model: str | None = None,
                 temperature: float = TEMPERATURE, workers: int = WORKERS) -> list[Label]:
    """同一批句子一起問（快取命中的不打 API；沒命中的開 workers 條線）。模型 / prompt 寫法看 CONFIG（configure()）。"""
    prompt = prompt or default_prompt()
    model = model or CONFIG["model"]
    out: list[Label | None] = [None] * len(texts)
    todo = []
    for i, t in enumerate(texts):
        key = _key(prompt, t, rep, model, temperature)
        if key.is_file():
            d = json.loads(key.read_text(encoding="utf-8"))
            if d["kind"] == "error":          # 以前快取過的解析失敗：當作沒問過
                todo.append(i)
            else:
                out[i] = Label(d["kind"], d["target"])
        else:
            todo.append(i)
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, res in zip(todo, ex.map(lambda i: _ask(prompt, texts[i], rep=rep, model=model, temperature=temperature), todo), strict=True):
                out[i] = Label(res["kind"], res["target"])
    return [lab for lab in out if lab is not None]


def route_label(text: str) -> Label:
    return batch_labels([text])[0]


def same_route(a: Label, b: Label) -> bool:
    # 模型的 target 格式比 regex 鬆：去空白、全形冒號、大小寫
    norm = lambda x: Label(x.kind.strip(), re.sub(r"\s+", "", x.target).replace("：", ":"))  # noqa: E731
    return _same_route(norm(a), norm(b))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--try", dest="try_text", nargs="*")
    ap.add_argument("--seeds", help="seeds.json：答對幾條 + 同句再問一次（rep 1）的一致率")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--prompt", action="store_true", help="印出 prompt")
    ap.add_argument("--model", default=None, help="換模型（預設 gemini-3.5-flash-lite）")
    ap.add_argument("--style", default=None, choices=STYLES, help="prompt 寫法（預設 full）")
    a = ap.parse_args()
    configure(a.model, a.style)
    if a.prompt:
        print(default_prompt())
        return 0
    if a.try_text:
        for t, lab in zip(a.try_text, batch_labels(a.try_text), strict=True):
            print(f"{t!r:30} {lab}")
        return 0
    if a.seeds:
        seeds = json.loads(Path(a.seeds).read_text(encoding="utf-8"))["seeds"]
        texts = [s["text"] for s in seeds]
        l0 = batch_labels(texts)
        l1 = batch_labels(texts, rep=a.rep)
        ok = sum(1 for s, lab in zip(seeds, l0, strict=True) if same_route(lab, Label(*s["expect"].partition(":")[::2])))
        agree = sum(1 for x, y in zip(l0, l1, strict=True) if same_route(x, y))
        print(f"種子答對 {ok} / {len(seeds)}；同句問兩次一致 {agree} / {len(seeds)}")
        for s, x, y in zip(seeds, l0, l1, strict=True):
            exp = Label(*s["expect"].partition(":")[::2])
            flag = "" if same_route(x, exp) else "  ← 錯"
            flag2 = "" if same_route(x, y) else f"  ← 第二次 {y}"
            print(f"  {s['text']!r:28} 期望 {str(exp):30} 得到 {str(x):30}{flag}{flag2}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
