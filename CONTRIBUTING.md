# 參與開發

## 環境

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install ruff
```

## 檢查

```bash
ruff check jarvis/
python -m compileall -q jarvis/
python -m jarvis --text --once "現在幾點"    # 不需要金鑰，走本機路由
```

## 加一個新工具

1. 在 `jarvis/tools/` 底下寫一個普通的 Python function。
   **type hint 與 docstring 就是 schema** —— 兩個 provider 都靠它們生成工具定義，
   所以 docstring 的 `Args:` 區塊要寫清楚每個參數是什麼。
2. 加進 `jarvis/tools/__init__.py` 的 `CLAUDE_TOOLS`（Gemini 會自動繼承）。
3. 如果這件事本機規則就能判斷，順手在 `jarvis/router.py` 加一條規則 ——
   每加一條就少一次 API 呼叫。
4. 想在 HUD 的 Active Modules 亮燈，到 `hud/jarvis_hub.html` 加一個
   `<div class="t" data-tool="你的工具名">`。

## 加一個新平台

實作 `jarvis/platform_/base.py` 的 `Platform` 介面，在 `platform_/__init__.py`
的 `get_platform()` 加上偵測分支。不要在上層 `tools/` 裡寫平台判斷。

## 風格

- 註解寫「為什麼」，不寫「這行在做什麼」。
- 工具失敗要回傳明確的失敗訊息，不要吞掉例外然後回一句聽起來成功的話。
  模型會照單全收，然後跟使用者說任務完成了。
