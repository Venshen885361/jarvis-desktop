"""LLM 生成器：照蛻變關係叫模型改寫種子句。

- 只用 Gemini（專案本來就有 google-genai、金鑰在 .env 的 GEMINI_API_KEY）。
- temperature 是實驗變因，由呼叫端指定；模型名、溫度、時間都寫進輸出，實驗才可重現。
- 回傳一律 JSON 陣列；模型不聽話（多講話、少引號）時盡量搶救，搶救不了就記成失敗，不假裝成功。
- 有磁碟快取：同（模型, 溫度, 種子, 關係, n）不重打 API —— 免費額度有限。

⚠️ 溫度 0 不等於確定性：同一組參數重跑仍可能得到不同句子，這是這個研究要面對的事實，不是 bug。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from .relations import Relation

CACHE_DIR = Path(__file__).resolve().parent / "out" / "cache"

_SYSTEM = """你是軟體測試的資料產生器。使用者會給你一句對語音助理下的中文指令（種子句）和一條改寫規則。
請產生 {n} 句改寫，規則：
- 一律台灣用語的繁體中文，口語、像真的對著麥克風講的話。
- {instruction}
- 每句都要跟其他句不同，不要只換標點。
- 只輸出 JSON 陣列（字串陣列），不要任何說明、不要 markdown 圍欄。"""


def _cache_key(model: str, temperature: float, seed: str, relation_id: str, n: int) -> Path:
    h = hashlib.sha1(f"{model}|{temperature}|{seed}|{relation_id}|{n}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _parse_array(text: str) -> list[str] | None:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        arr = json.loads(t)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()]
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", t, re.S)  # 模型前後多講了話：抓中間的陣列
    if m:
        try:
            arr = json.loads(m.group())
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except json.JSONDecodeError:
            return None
    return None


def generate(seed_text: str, relation: Relation, n: int, *, model: str, temperature: float,
             use_cache: bool = True) -> dict:
    """回 {"items": [...], "ok": bool, "raw": str, "meta": {...}}。"""
    key = _cache_key(model, temperature, seed_text, relation.id, n)
    if use_cache and key.is_file():
        return json.loads(key.read_text(encoding="utf-8"))

    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("需要 GEMINI_API_KEY（.env 或環境變數）")
    client = genai.Client(api_key=api_key)
    prompt = f"種子句：{seed_text}"
    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM.format(n=n, instruction=relation.instruction),
                temperature=temperature,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        raw = resp.text or ""
    except Exception as e:  # 配額 / 網路：記下來，跑完整批再看
        raw = f"__ERROR__ {type(e).__name__}: {e}"
    items = _parse_array(raw) if not raw.startswith("__ERROR__") else None
    result = {
        "items": items or [],
        "ok": items is not None,
        "raw": raw[:4000],
        "meta": {"model": model, "temperature": temperature, "seed": seed_text, "relation": relation.id,
                 "n": n, "ms": int((time.time() - t0) * 1000), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
    }
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
