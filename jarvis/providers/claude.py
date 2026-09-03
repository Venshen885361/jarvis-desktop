"""Anthropic provider —— 用官方 computer-use toolset 真正控制這台電腦。

工具規格（type / tool_result 形狀 / 批次動作規則）依官方文件實作：
https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
prompt caching 依：
https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching

省 token 的四個著力點都在這個檔案裡：
1. 分級路由：不需要看畫面的指令用便宜模型，而且完全不掛 computer toolset
   （工具定義本身就要錢）。模型自己判斷需要看畫面時，呼叫
   escalate_to_computer_control 升級到完整模型重跑這一輪。
2. 截圖壓縮：screen.capture() 縮到長邊 1024 + JPEG，見 screen.py。
3. 歷史壓縮：舊截圖從歷史移除（同一張圖留在歷史裡每輪都要重算），
   工具文字結果截斷，訊息數超量時從安全邊界裁切。
4. prompt caching：system 與 tools 掛 cache_control ephemeral 斷點。
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from ..devices import get_devices
from ..hud import emit_log, emit_state, emit_usage
from ..tools import CLAUDE_TOOLS
from ..usage import tracker
from .base import Provider
from .prompt import JARVIS_PROMPT, LIGHT_PROMPT
from .schema import to_anthropic_tool

COMPUTER_TOOLSET = "computer_toolset_20260801"
NOT_EXECUTED = "Not executed: an earlier computer action in this turn failed."

# 明顯需要看畫面 / 操作 GUI 的字眼。命中就直接用完整模型，省一次無謂的往返。
_SCREEN_HINTS = (
    "畫面", "螢幕", "截圖", "點", "按鈕", "選單", "捲動", "滾動", "拖", "框",
    "填", "表單", "分頁", "視窗裡", "上面寫", "唸出", "讀出", "看一下",
    "幫我在", "貼上", "複製這", "存檔", "另存",
)

_ESCALATE_TOOL = {
    "name": "escalate_to_computer_control",
    "description": (
        "當這個指令必須看螢幕內容或操作滑鼠鍵盤才能完成時呼叫，"
        "會把任務交給具備完整電腦控制權限的模型接手。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "為什麼需要看畫面或操作 GUI"}
        },
        "required": ["reason"],
    },
}


def _needs_screen(text: str) -> bool:
    return any(h in text for h in _SCREEN_HINTS)


class ClaudeProvider(Provider):
    name = "claude"

    def __init__(self) -> None:
        import anthropic

        if not settings.anthropic_api_key:
            raise RuntimeError(
                "未設定 ANTHROPIC_API_KEY。請複製 .env.example 成 .env 並填入金鑰。"
            )
        # 多工作區金鑰要在每個請求帶 anthropic-workspace-id，不然是 400
        # invalid_request_error。單一 workspace 的金鑰不需要，留空即可。
        headers = (
            {"anthropic-workspace-id": settings.anthropic_workspace_id}
            if settings.anthropic_workspace_id
            else None
        )
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, default_headers=headers
        )
        self.model = settings.claude_model
        self.messages: list[dict[str, Any]] = []
        self._custom_tools = [to_anthropic_tool(fn) for fn in CLAUDE_TOOLS]

    # ------------------------------------------------------------------
    # 工具定義
    # ------------------------------------------------------------------
    def _tools(self, with_computer: bool) -> list[dict]:
        tools: list[dict] = []
        if with_computer:
            tools.append({"type": COMPUTER_TOOLSET})
        else:
            tools.append(_ESCALATE_TOOL)
        tools.extend(self._custom_tools)
        if settings.enable_prompt_cache and tools:
            # 斷點放在工具清單最後一項：system + 全部工具定義一起被快取。
            # 工具定義是每輪都會重送、內容又完全固定的部分，最值得快取。
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools

    def _system(self, with_computer: bool) -> list[dict]:
        text = JARVIS_PROMPT if with_computer else LIGHT_PROMPT
        block: dict[str, Any] = {"type": "text", "text": text}
        if settings.enable_prompt_cache:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    # ------------------------------------------------------------------
    # 歷史壓縮
    # ------------------------------------------------------------------
    def _prune(self) -> None:
        msgs = self.messages

        # 1) 只保留最近 N 張截圖，更舊的換成佔位文字。
        #    這是這裡最有效的一招：一張 1024x576 的圖約 786 tokens，
        #    留在歷史裡每一輪都會被重新計費一次。
        kept = 0
        for msg in reversed(msgs):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                if not isinstance(inner, list):
                    continue
                has_image = any(
                    isinstance(b, dict) and b.get("type") == "image" for b in inner
                )
                if not has_image:
                    continue
                if kept < settings.history_keep_images:
                    kept += 1
                else:
                    block["content"] = [
                        {"type": "text", "text": "[舊截圖已移除以節省 token]"}
                    ]

        # 2) 訊息過多時從安全邊界裁切：切點必須是一個「不是 tool_result」的 user 訊息，
        #    否則會留下沒有配對 tool_use 的 tool_result，API 會直接拒絕。
        limit = settings.history_keep_turns * 2
        if len(msgs) <= limit:
            return
        for i in range(len(msgs) - limit, len(msgs)):
            msg = msgs[i]
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                self.messages = msgs[i:]
                return
            if isinstance(content, list) and not any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                self.messages = msgs[i:]
                return

    # ------------------------------------------------------------------
    # 主迴圈
    # ------------------------------------------------------------------
    def run_turn(self, user_text: str) -> str:
        with_computer = _needs_screen(user_text)
        # 目標裝置不是本機時，把它寫在 user 訊息前面（而不是 system prompt），
        # 這樣 system + tools 的快取不會因為切裝置而失效。
        devs = get_devices()
        if devs.current_name != "local":
            user_text = f"[目前控制的裝置：{devs.current_name}（{devs.current.platform}）] {user_text}"
        self.messages.append({"role": "user", "content": user_text})
        reply = self._loop(with_computer)
        self._prune()
        return reply

    def _loop(self, with_computer: bool) -> str:
        model = settings.claude_model if with_computer else settings.claude_model_light

        for _ in range(settings.max_tool_steps):
            emit_state("thinking")
            response = self.client.messages.create(
                model=model,
                max_tokens=settings.claude_max_tokens,
                system=self._system(with_computer),
                tools=self._tools(with_computer),
                messages=self.messages,
            )
            self._record_usage(model, response)

            self.messages.append(
                {"role": "assistant", "content": response.content}
            )

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                return text or "Sir, 指令已收到。"

            # 分級路由的升級點：輕量模型自己說牠需要看畫面
            if any(b.name == "escalate_to_computer_control" for b in tool_uses):
                emit_log("SYS", "指令需要畫面存取，升級到完整電腦控制模型。")
                # 丟掉那次不完整的 assistant 回合，用完整模型重跑同一句指令
                self.messages.pop()
                return self._loop(with_computer=True)

            results, _failed = self._run_tools(tool_uses)
            self.messages.append({"role": "user", "content": results})
            self._prune()

        return "Sir, 這個任務的步驟有點多，我先停在這裡，麻煩您確認目前狀態。"

    def _run_tools(self, tool_uses: list) -> tuple[list[dict], bool]:
        """依官方規範：批次動作依序執行，第一個失敗之後的全部標成 NOT_EXECUTED。"""
        results: list[dict] = []
        failed = False

        for block in tool_uses:
            is_computer = getattr(block, "toolset_name", None) == "computer"
            result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": block.id,
            }
            if is_computer:
                result["toolset_name"] = "computer"

            if failed:
                result["content"] = NOT_EXECUTED
                result["is_error"] = True
                results.append(result)
                continue

            try:
                devs = get_devices()
                if is_computer:
                    print(f"[computer@{devs.current_name}] {block.name}({dict(block.input)})")
                    from ..hud import emit_tool

                    emit_tool(f"computer:{block.name}", dict(block.input))
                    out = devs.run_tool(f"computer:{block.name}", dict(block.input))
                    if hasattr(out, "b64"):  # ImageResult
                        result["content"] = [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": out.media_type,
                                    "data": out.b64,
                                },
                            }
                        ]
                    else:
                        result["content"] = [{"type": "text", "text": str(out)}]
                else:
                    print(f"[tool@{devs.current_name}] {block.name}({dict(block.input)})")
                    from ..hud import emit_tool

                    emit_tool(block.name, dict(block.input))
                    out = devs.run_tool(block.name, dict(block.input))
                    result["content"] = self.truncate_tool_result(str(out))
            except Exception as e:
                result["content"] = f"Error: {e}"
                result["is_error"] = True
                failed = True

            results.append(result)

        return results, failed

    # ------------------------------------------------------------------
    def _record_usage(self, model: str, response) -> None:
        u = getattr(response, "usage", None)
        if not u:
            return
        tracker.add(
            model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        emit_usage()

    # ------------------------------------------------------------------
    def describe_image(self, data: bytes, media_type: str, prompt: str) -> str:
        import base64

        response = self.client.messages.create(
            model=settings.claude_model_light,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(data).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        self._record_usage(settings.claude_model_light, response)
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def remember(self, user_text: str, reply: str) -> None:
        self.messages.append({"role": "user", "content": user_text})
        self.messages.append({"role": "assistant", "content": reply})
        self._prune()
