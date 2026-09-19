"""Atomic writes for pipeline stores (stdlib only).

One law in one place: a crash, a full disk or a concurrent reader must never
see a truncated handoff file. Text is written to a sibling temp file and
replaced atomically on the same volume, so readers keep the previous store
until the new one is complete. Callers stay fail-soft: an OSError from here is
theirs to diagnose, never a reason to leave half a store behind.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".tmp")
    part.write_text(text, encoding=encoding)
    os.replace(part, path)


def write_json_atomic(path: Path, doc, *, indent: int = 2) -> None:
    write_text_atomic(path, json.dumps(doc, ensure_ascii=False, indent=indent))
