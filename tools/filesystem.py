"""Filesystem tools — read/write/edit/search within a workspace root."""
from __future__ import annotations

import os
import re
from pathlib import Path

from tools.base import Tool


def _resolve(workspace: Path, path: str) -> Path:
    p = (workspace / path).resolve()
    # stay inside the workspace
    if workspace.resolve() not in p.parents and p != workspace.resolve():
        raise PermissionError(f"Path outside workspace: {path}")
    return p


def read_file(path: str, workspace: Path | None = None,
              start: int | None = None, end: int | None = None) -> dict:
    ws = workspace or Path.cwd()
    target = _resolve(ws, path)
    if not target.is_file():
        return {"error": f"not found: {path}", "path": str(target)}
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    if start is not None or end is not None:
        a, b = (start or 1) - 1, (end or len(lines))
        lines = lines[max(0, a):b]
    return {"path": str(target), "lines": lines}


def write_file(path: str, content: str,
               workspace: Path | None = None) -> dict:
    ws = workspace or Path.cwd()
    target = _resolve(ws, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "written": True,
            "bytes": len(content.encode("utf-8"))}


def edit_file(path: str, old_text: str, new_text: str,
              workspace: Path | None = None) -> dict:
    ws = workspace or Path.cwd()
    target = _resolve(ws, path)
    if not target.is_file():
        return {"error": f"not found: {path}"}
    text = target.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count != 1:
        return {"error": f"old_text matched {count} times (need exactly 1)"}
    target.write_text(text.replace(old_text, new_text), encoding="utf-8")
    return {"path": str(target), "replaced": 1}


def search_files(pattern: str, path: str = ".",
                 workspace: Path | None = None) -> dict:
    ws = workspace or Path.cwd()
    base = _resolve(ws, path)
    rx = re.compile(pattern, re.IGNORECASE)
    hits = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith((".git", ".venv",
                                                        "node_modules"))]
        for name in files:
            fp = Path(root) / name
            hits.append(str(fp.relative_to(ws)))
    matched = [h for h in hits if rx.search(h)]
    return {"pattern": pattern, "matches": matched[:200],
            "total": len(matched)}


def list_directory(path: str = ".", workspace: Path | None = None) -> dict:
    ws = workspace or Path.cwd()
    target = _resolve(ws, path)
    if not target.is_dir():
        return {"error": f"not a directory: {path}"}
    items = sorted(p.relative_to(target).as_posix()
                   + ("/" if p.is_dir() else "")
                   for p in target.iterdir())
    return {"path": str(target), "entries": items}


FILE_TOOLS = [
    Tool("fs_read_file",
         "Read text from a file (optionally a line range).",
         {"type": "object",
          "properties": {
              "path": {"type": "string", "description": "file path"},
              "start": {"type": "integer", "description": "start line"},
              "end": {"type": "integer", "description": "end line"},
          }},
         required=["path"], fn=read_file),
    Tool("fs_write_file",
         "Create or overwrite a file with the given content.",
         {"type": "object",
          "properties": {
              "path": {"type": "string"},
              "content": {"type": "string"},
          }},
         required=["path", "content"], fn=write_file),
    Tool("fs_edit_file",
         "Replace an exact old_text with new_text inside a file.",
         {"type": "object",
          "properties": {
              "path": {"type": "string"},
              "old_text": {"type": "string"},
              "new_text": {"type": "string"},
          }},
         required=["path", "old_text", "new_text"], fn=edit_file),
    Tool("fs_search_files",
         "Find files whose path matches a regex pattern.",
         {"type": "object",
          "properties": {
              "pattern": {"type": "string"},
              "path": {"type": "string", "description": "start dir"},
          }},
         required=["pattern", "path"], fn=search_files),
    Tool("fs_list_directory",
         "List entries in a directory.",
         {"type": "object",
          "properties": {
              "path": {"type": "string", "description": "directory path"},
          }},
         required=["path"], fn=list_directory),
]
