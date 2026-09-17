"""AST statement coverage for enrich + cluster under unittest. Stdlib only."""
from __future__ import annotations

import ast
import sys
import trace
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("enrich.py", "cluster_issues.py", "ambient_pulse.py", "life_facets.py")


def statement_lines(src: str) -> set[int]:
    tree = ast.parse(src)
    lines: set[int] = set()

    class V(ast.NodeVisitor):
        def visit(self, node: ast.AST):
            if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
                # Skip module docstring / import noise later via filter
                lines.add(node.lineno)
            self.generic_visit(node)

    V().visit(tree)
    return lines


def function_body_statements(tree: ast.AST) -> set[int]:
    """Executable stmts in functions — skip leading docstrings (never traced as hits)."""
    keep: set[int] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        for child in body:
            for sub in ast.walk(child):
                if isinstance(sub, ast.stmt) and hasattr(sub, "lineno"):
                    keep.add(sub.lineno)
    return keep


def main() -> int:
    tracer = trace.Trace(count=True, trace=False, ignoredirs=[sys.prefix, sys.base_prefix])

    def run_suite() -> None:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=0).run(suite)
        if not result.wasSuccessful():
            raise SystemExit(1)

    tracer.runfunc(run_suite)
    counts = tracer.results().counts

    print("=== AST statement coverage (stdlib trace) ===")
    worst = 1.0
    for name in TARGETS:
        path = ROOT / "scripts" / name
        src = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)
        keep = function_body_statements(tree)
        exec_lines = {
            lineno
            for (fname, lineno), n in counts.items()
            if Path(fname).name == name and n > 0
        }
        hit = keep & exec_lines
        miss = sorted(keep - exec_lines)
        pct = len(hit) / len(keep) if keep else 0.0
        worst = min(worst, pct)
        print(f"{name}: {len(hit)}/{len(keep)} statements = {pct:.1%}")
        if miss:
            print(f"  miss stmt lines: {miss}")
    print(f"min statement ratio: {worst:.1%}")
    return 0 if worst >= 0.92 else 2


if __name__ == "__main__":
    raise SystemExit(main())
