"""
Vigie - one-shot refresh: collect, verify, stage, deploy to production.

Designed to run unattended (Windows Task Scheduler, every 6 hours - the same
cadence as the roadworks stale threshold). Every failing step stops the
chain: a broken edition is never deployed and the previously deployed site
stays up.

Steps:
  1. pipeline.py --stage   full online collection + render + stage
  2. verify.py             tests + syntax + stage + smoke. Never --rebuild:
                           an offline rebuild collapses the honest diffs
                           between editions (roadworks, change ledger).
  3. vercel link           re-link deploy/public (staging wipes .vercel, and
                           verify re-stages, so this must come after)
  4. vercel deploy --prod  publish. Later deploys of a linked project default
                           to preview, so --prod is explicit.

Appends to data/ops/refresh.log. A lock file prevents overlapping runs; a
lock older than two hours is treated as stale and taken over. Exit code 0
only when the chain completed (or was skipped because another run is active).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "data" / "ops" / "refresh.log"
LOCK_PATH = ROOT / "data" / "ops" / "refresh.lock"
LOCK_STALE_SECONDS = 2 * 3600
TEAM = "deemto"
PROJECT = "vigie"
DEPLOY_DIR = ROOT / "deploy" / "public"


def log(line: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} {line}", flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {line}\n")


def run_step(name: str, command: list[str], timeout: int, cwd: Path = ROOT) -> None:
    log(f"START {name}")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{name} timed out after {timeout}s") from None
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        err = "\n".join((proc.stderr or "").strip().splitlines()[-10:])
        out = "\n".join((proc.stdout or "").strip().splitlines()[-10:])
        raise RuntimeError(f"{name} failed (code {proc.returncode})\n{err}\n{out}")
    log(f"DONE {name} in {elapsed:.0f}s")
    tail = (proc.stdout or "").strip().splitlines()[-4:]
    for line in tail:
        log(f"  | {line}")


def acquire_lock() -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - LOCK_PATH.stat().st_mtime
        except OSError:
            return True  # vanished between open and stat; caller proceeds
        if age < LOCK_STALE_SECONDS:
            return False
        log(f"WARN stale lock ({age:.0f}s old) - taking over")
        try:
            LOCK_PATH.unlink()
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (OSError, FileExistsError):
            return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect, verify and deploy one edition.")
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="Collect, verify and stage only; do not touch Vercel",
    )
    args = parser.parse_args()

    if not acquire_lock():
        log("SKIP another refresh is already running (lock held)")
        return 0
    try:
        python = sys.executable
        run_step(
            "pipeline",
            [python, "-X", "utf8", str(ROOT / "scripts" / "pipeline.py"), "--stage"],
            timeout=1800,
        )
        run_step(
            "verify",
            [python, "-X", "utf8", str(ROOT / "scripts" / "verify.py")],
            timeout=1800,
        )
        if args.no_deploy:
            log("OK refresh complete (deploy skipped by --no-deploy)")
            return 0
        vercel = shutil.which("vercel")
        if not vercel:
            raise RuntimeError("vercel CLI not found on PATH")
        run_step(
            "link",
            [
                vercel, "link", "--yes",
                "--scope", TEAM,
                "--project", PROJECT,
                "--cwd", str(DEPLOY_DIR),
            ],
            timeout=300,
        )
        run_step(
            "deploy",
            [vercel, "deploy", str(DEPLOY_DIR), "-y", "--no-wait", "--prod"],
            timeout=900,
        )
        log("OK production updated")
        return 0
    except (RuntimeError, OSError) as exc:
        log(f"FAIL {exc}")
        return 1
    finally:
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
