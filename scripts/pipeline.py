"""Vigie v0 - one-command Critical Path.

Runs: ingest -> normalize -> enrich -> cluster -> rank/display.
Stdlib only. Does not start the server (open a second terminal for that).

Usage (from repo root):
  python scripts/pipeline.py
Then:
  python scripts/serve.py
  open http://127.0.0.1:8765/
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "ingest_rss.py",
    "normalize.py",
    "enrich.py",
    "cluster_issues.py",
    "rank_display.py",
]


def run(script: str) -> None:
    path = ROOT / "scripts" / script
    print(f"\n=== {script} ===", flush=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, str(path)], cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise SystemExit(f"{script} failed with code {proc.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Reuse raw snapshots; make no network requests")
    mode.add_argument("--render-only", action="store_true", help="Render the existing enriched store without changing upstream data")
    parser.add_argument("--stage", action="store_true", help="Validate and stage the complete static release after building")
    args = parser.parse_args()
    selected = SCRIPTS[-1:] if args.render_only else SCRIPTS[1:] if args.offline else SCRIPTS
    print("Vigie pipeline" + (" (offline snapshots)" if args.offline else " (render existing store)" if args.render_only else " (refresh sources)"))
    for name in selected:
        run(name)
    if args.stage:
        run("stage_public.py")
    print("\nDone. Serve with: python scripts/serve.py")
    print("Then open: http://127.0.0.1:8765/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
