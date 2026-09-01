"""從 Python 函式自動生成 Anthropic custom tool 的 input_schema。

google-genai SDK 本來就會做這件事（直接吃 function 物件），Anthropic SDK 不會，
所以這裡補一個最小可用的轉換器：讀 type hint 決定型別、讀 docstring 的
Args 區塊決定每個參數的描述。這樣兩個 provider 可以共用同一份工具函式。
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _split_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """回傳 (整體描述, {參數名: 描述})。"""
    if not doc:
        return "", {}
    lines = inspect.cleandoc(doc).splitlines()
    desc_lines: list[str] = []
    args: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if re.match(r"^Args?:\s*$", stripped):
            in_args = True
            continue
        if in_args:
            m = re.match(r"^(\w+)\s*:\s*(.*)$", stripped)
            if m:
                current = m.group(1)
                args[current] = m.group(2).strip()
            elif current and stripped:
                args[current] += " " + stripped
        else:
            desc_lines.append(line)
    return "\n".join(desc_lines).strip(), args


def to_anthropic_tool(fn: Callable[..., Any]) -> dict:
    description, arg_docs = _split_docstring(fn.__doc__ or "")
    # eval_str=True 是必要的：工具模組都用了 `from __future__ import annotations`，
    # 不求值的話 annotation 會是字串 "int"，型別對照表就全部落空變成 string。
    try:
        sig = inspect.signature(fn, eval_str=True)
    except Exception:
        sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        json_type = _TYPE_MAP.get(param.annotation, "string")
        prop: dict[str, Any] = {"type": json_type}
        if pname in arg_docs:
            prop["description"] = arg_docs[pname]
        properties[pname] = prop
        if param.default is inspect.Parameter.empty:
            required.append(pname)

    return {
        "name": fn.__name__,
        "description": description or fn.__name__,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
