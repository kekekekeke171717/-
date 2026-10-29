"""极简 YAML 读取：只支持本项目的配置子集（嵌套映射 + 标量 + 行内列表）。

刻意不引入 PyYAML：MVP 要求"零第三方依赖、离线可跑"，
配置项只有阈值与开关，用不到完整 YAML 规范。
"""
from __future__ import annotations

import os
from typing import Any


def _scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw == "" or raw == "~":
        return None
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw


def loads(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip() == "":
            node: dict = {}
            parent[key] = node
            stack.append((indent, node))
        else:
            parent[key] = _scalar(value)
    return root


def load(path: str | None = None) -> dict:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), "config", "default.yaml")
    with open(path, encoding="utf-8") as f:
        return loads(f.read())


def merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out
