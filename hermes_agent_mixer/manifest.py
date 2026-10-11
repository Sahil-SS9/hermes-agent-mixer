"""Minimal YAML subset parser for plugin manifests (stdlib only).

Supports nested block mappings, inline [..]/plain scalars and quoted
strings. Not a general YAML implementation: this is only a check of our own
manifest's schema types; the host's loader never imports it.
"""

from __future__ import annotations


def _inline_scalar(text: str):
    text = text.strip()
    if not text:
        return None
    if (text[0] == text[-1]) and text[0:1] in ("'", '"') and len(text) >= 2:
        return text[1:-1].replace("''", "'") if text[0] == "'" else text[1:-1]
    if text[0] == "[":
        body = text[1:text.rindex("]")] if "]" in text else text[1:]
        items = []
        current = ""
        quote = ""
        for ch in body:
            if quote:
                current += ch
                if ch == quote:
                    quote = ""
            elif ch in ("'", '"'):
                current += ch
                quote = ch
            elif ch == ",":
                items.append(_inline_scalar(current))
                current = ""
            else:
                current += ch
        if current.strip():
            items.append(_inline_scalar(current))
        return items
    return text


def loads(text: str) -> dict:
    """Parse manifest-level block mappings into nested dicts/scalars."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip():
            parent[key.strip()] = _inline_scalar(value)
        else:
            parent[key.strip()] = {}
            stack.append((indent, parent[key.strip()]))
    return root