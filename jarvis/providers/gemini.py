"""Google Gemini provider —— 原始實作的延續，成本比 Claude 低，
但沒有官方 computer-use toolset，GUI 操作靠 locate_and_type 的視覺定位。

同樣套用了截圖壓縮、歷史裁切、模型分級三項節流。
"""

from __future__ import annotations

import json
import re

from ..config import settings
from ..devices import get_devices
from ..hud import emit_state, emit_tool, emit_usage
from ..screen import capture
from ..tools import GEMINI_TOOLS
from ..usage import tracker
from .base import Provider
from .prompt import answer_prompt, system_prompt

_SCREEN_HINTS = ("畫面", "螢幕", "截圖", "點", "按鈕", "搜尋", "輸入", "打字")


def is_quota_error(e: Exception) -> bool:
    s = str(e).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self) -> None:
        from google import genai

        if not settings.gemini_api_key:
            raise RuntimeError(
                "未設定 GEMINI_API_KEY。請複製 .env.example 成 .env 並填入金鑰。"
            )
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_models[0]
        self.history: list = []

    # ------------------------------------------------------------------
    def _config(self, tools: bool = True):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system_prompt(),
            max_output_tokens=300,
            tools=GEMINI_TOOLS if tools else None,
            # 自己接管工具執行：執行完要把結果餵回去讓模型接續判斷
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

    def _prune(self) -> None:
        limit = settings.history_keep_turns * 2
        if len(self.history) <= limit:
            return
        # 切點必須是一般的 user 訊息（不是 function_response），
        # 否則歷史會留下沒有配對的 function_call / function_response。
        for i in range(len(self.history) - limit, len(self.history)):
            c = self.history[i]
            if getattr(c, "role", None) != "user":
                continue
            parts = getattr(c, "parts", []) or []
            if not any(getattr(p, "function_response", None) for p in parts):
                self.history = self.history[i:]
                return

    # ------------------------------------------------------------------
    def run_turn(self, user_text: str) -> str:
        from google.genai import types

        # 分級路由：不需要視覺／GUI 的閒聊用 flash-lite
        candidates = (
            list(settings.gemini_models)
            if any(h in user_text for h in _SCREEN_HINTS)
            else [settings.gemini_model_light, *settings.gemini_models]
        )

        devs = get_devices()
        if devs.current_name != "local":
            user_text = f"[目前控制的裝置：{devs.current_name}（{devs.current.platform}）] {user_text}"
        trial = self.history + [
            types.Content(role="user", parts=[types.Part(text=user_text)])
        ]

        for model_name in candidates:
            try:
                reply, self.history = self._agentic_turn(model_name, trial)
                self._prune()
                return reply
            except Exception as e:
                print(f"[系統] 模型 {model_name} 無法使用（{e}）")
                if is_quota_error(e):
                    break

        self.history = self.history + [
            types.Content(role="user", parts=[types.Part(text=user_text)]),
            types.Content(
                role="model",
                parts=[types.Part(text="Sir, 雲端服務暫時無法使用。")],
            ),
        ]
        return "Sir, 雲端服務目前暫時無法使用，這個指令沒辦法完成，請稍後再試。"

    def _agentic_turn(self, model_name: str, history: list) -> tuple[str, list]:
        from google.genai import types

        history = list(history)  # 在複本上操作，整輪成功才回寫

        for _ in range(settings.max_tool_steps):
            emit_state("thinking")
            response = self.client.models.generate_content(
                model=model_name, contents=history, config=self._config()
            )
            self._record_usage(model_name, response)

            if not response.function_calls:
                text = response.text or "Sir, 指令已收到。"
                history.append(response.candidates[0].content)
                return text, history

            # 直接沿用 SDK 回傳的 content：thinking 模型的 function_call 帶有
            # thought_signature，自己重組會弄丟，下一輪就會被 API 以
            # 400 INVALID_ARGUMENT (missing thought_signature) 拒絕。
            history.append(response.candidates[0].content)

            parts = []
            for call in response.function_calls:
                args = dict(call.args) if call.args else {}
                devs = get_devices()
                print(f"[tool@{devs.current_name}] {call.name}({args})")
                emit_tool(call.name, args)
                try:
                    result = self.truncate_tool_result(str(devs.run_tool(call.name, args)))
                except Exception as e:
                    result = f"工具 {call.name} 執行失敗：{e}"
                parts.append(
                    types.Part.from_function_response(
                        name=call.name, response={"result": result}
                    )
                )
            history.append(types.Content(role="user", parts=parts))

        fallback = "Sir, 這個任務的步驟有點多，我先停在這裡。"
        history.append(types.Content(role="model", parts=[types.Part(text=fallback)]))
        return fallback, history

    # ------------------------------------------------------------------
    def _record_usage(self, model: str, response) -> None:
        meta = getattr(response, "usage_metadata", None)
        if not meta:
            return
        tracker.add(
            model,
            input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
            output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
            cache_read=getattr(meta, "cached_content_token_count", 0) or 0,
        )
        emit_usage()

    # ------------------------------------------------------------------
    def answer(self, user_text: str, context: str = "") -> str:
        """純問答 + Google 搜尋 grounding（附近美食這種需要即時資料的問題才答得出來）。"""
        from google.genai import types

        model = settings.gemini_models[0]
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction=answer_prompt(context),
                    max_output_tokens=700,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
        except Exception as e:
            # grounding 不可用（配額 / 地區）時退回純模型回答，如實標記
            print(f"[answer] 搜尋 grounding 失敗，改用純模型：{e}")
            response = self.client.models.generate_content(
                model=model,
                contents=user_text,
                config=types.GenerateContentConfig(system_instruction=answer_prompt(context + "\n（目前沒有網路搜尋能力，只能憑既有知識回答，請說明這點。）"), max_output_tokens=700),
            )
        self._record_usage(model, response)
        text = (response.text or "").strip()
        self.remember(user_text, text)
        return text or "Sir, 我沒有找到可靠的資訊。"

    # ------------------------------------------------------------------
    def describe_image(self, data: bytes, media_type: str, prompt: str) -> str:
        from google.genai import types

        response = self.client.models.generate_content(
            model=settings.gemini_model_light,
            contents=[
                types.Part.from_bytes(data=data, mime_type=media_type),
                prompt,
            ],
        )
        self._record_usage(settings.gemini_model_light, response)
        return (response.text or "").strip()

    def locate_element(self, description: str) -> tuple[int, int] | None:
        from google.genai import types

        shot = capture()
        prompt = f"""這是目前的電腦螢幕截圖（尺寸 {shot.width}x{shot.height}）。
請找出畫面中「{description}」的中心點像素座標 (x, y)。
如果畫面上根本沒有這個元素，回傳 {{"found": false}}，絕對不要亂猜座標。
找到的話回傳 {{"found": true, "x": 500, "y": 300}}。
只回傳 JSON，不要 Markdown 標籤或任何額外文字。"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                types.Part.from_bytes(data=shot.data, mime_type=shot.media_type),
                prompt,
            ],
        )
        self._record_usage(self.model, response)

        match = re.search(r"\{.*\}", (response.text or "").strip(), re.DOTALL)
        if not match:
            return None
        try:
            coord = json.loads(match.group())
        except json.JSONDecodeError:
            return None
        if not coord.get("found"):
            return None
        # 模型看到的是縮小後的圖，座標要換算回真實螢幕
        return shot.to_screen(coord["x"], coord["y"])

    def remember(self, user_text: str, reply: str) -> None:
        from google.genai import types

        self.history.append(
            types.Content(role="user", parts=[types.Part(text=user_text)])
        )
        self.history.append(
            types.Content(role="model", parts=[types.Part(text=reply)])
        )
        self._prune()
