"""Engine purity guard: app/engine imports nothing from wa/convo/llm/web.

Definition of done for P2 — the engine stays a pure, deterministic core.
"""

from __future__ import annotations

import ast
import pathlib

ENGINE_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "engine"
FORBIDDEN = ("app.wa", "app.convo", "app.llm", "app.web")


def _imported_modules(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_engine_has_no_forbidden_imports():
    offenders: list[str] = []
    for path in ENGINE_DIR.glob("*.py"):
        mods = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        for m in mods:
            if any(m == f or m.startswith(f + ".") for f in FORBIDDEN):
                offenders.append(f"{path.name}: {m}")
    assert not offenders, f"engine must stay pure, found: {offenders}"
