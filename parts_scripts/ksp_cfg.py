"""Minimal parser for KSP `.cfg` (ConfigNode) files.

KSP config files are a brace-delimited node format:

    PART
    {
        name = somePart
        mass = 0.2
        RESOURCE
        {
            name = ElectricCharge
            amount = 100
            maxAmount = 100
        }
    }

This module tokenizes that format into an immutable-ish `Node` tree. It does
NOT attempt to interpret ModuleManager patch operators (@, %, +, -, !); those
are surfaced as node names verbatim so callers can filter them out.

It also provides helpers for resolving KSP localization tokens
(`#autoLOC_######`) which appear as values with the human-readable string
hiding in a trailing `//` comment, or in `Localization/dictionary.cfg`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class Node:
    """A parsed config node. `props` maps a key to the list of values seen for
    that key (keys can legitimately repeat, e.g. multiple `texture =` lines)."""

    name: str = ""
    props: Dict[str, List[str]] = field(default_factory=dict)
    children: List["Node"] = field(default_factory=list)

    def first(self, key: str) -> Optional[str]:
        vals = self.props.get(key)
        return vals[0] if vals else None

    def children_named(self, name: str) -> List["Node"]:
        return [c for c in self.children if c.name == name]


def _strip_comment(line: str) -> str:
    idx = line.find("//")
    return line[:idx] if idx >= 0 else line


def _tokenize(text: str) -> List[str]:
    """Flatten file text into a stream of tokens: bare braces on their own,
    and each remaining non-empty (comment-stripped) line as one token."""
    tokens: List[str] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        buf = ""
        for ch in line:
            if ch in "{}":
                if buf.strip():
                    tokens.append(buf.strip())
                tokens.append(ch)
                buf = ""
            else:
                buf += ch
        if buf.strip():
            tokens.append(buf.strip())
    return tokens


def _parse_block(tokens: List[str], i: int) -> Tuple[Node, int]:
    """Parse tokens starting at index `i` until a matching `}` (or EOF).
    Returns the populated node and the index just past the close brace."""
    node = Node()
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "}":
            return node, i + 1
        if tok == "{":
            i += 1
            continue
        if "=" in tok:
            key, _, val = tok.partition("=")
            node.props.setdefault(key.strip(), []).append(val.strip())
            i += 1
            continue
        # Bare identifier => a child node header; its `{` follows.
        name = tok
        j = i + 1
        while j < n and tokens[j] != "{":
            # Defensive: a header should be immediately followed by `{`.
            # If not (malformed), treat the intervening token as the header.
            name = tokens[j]
            j += 1
        child, nxt = _parse_block(tokens, j + 1)
        child.name = name
        node.children.append(child)
        i = nxt
    return node, i


def parse_text(text: str) -> Node:
    """Parse full file text into a root node whose `children` are the
    top-level nodes (PART, @PART, etc.)."""
    root, _ = _parse_block(_tokenize(text), 0)
    return root


def parse_file(path: Path) -> Node:
    # utf-8-sig strips the BOM that KSP's Windows-authored files carry.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return parse_text(text)


# --- Localization -----------------------------------------------------------

_INLINE_RE = re.compile(r"(#autoLOC_\w+)\s*//\s*#?autoLOC_\w+\s*=\s*(.+?)\s*$")
_DICT_RE = re.compile(r"^\s*(#autoLOC_\w+)\s*=\s*(.+?)\s*$")


def collect_inline_localizations(text: str, into: Dict[str, str]) -> None:
    """Harvest `key = #autoLOC_X //#autoLOC_X = Human Text` mappings from raw
    file text into `into` (mutated in place; later files do not override
    earlier ones for the same token)."""
    for raw in text.splitlines():
        m = _INLINE_RE.search(raw)
        if m:
            into.setdefault(m.group(1), m.group(2))


def load_dictionary(dict_path: Path) -> Dict[str, str]:
    """Parse a `dictionary.cfg` localization file into {token: text}."""
    mapping: Dict[str, str] = {}
    if not dict_path.is_file():
        return mapping
    for raw in dict_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = _DICT_RE.match(raw)
        if m:
            mapping.setdefault(m.group(1), m.group(2))
    return mapping


def resolve(value: Optional[str], *maps: Dict[str, str]) -> Optional[str]:
    """Resolve a possibly-localized value. If it is an `#autoLOC` token, look it
    up across the provided maps in order; otherwise return it unchanged."""
    if value is None:
        return None
    if value.startswith("#autoLOC"):
        for m in maps:
            if value in m:
                return m[value]
    return value
