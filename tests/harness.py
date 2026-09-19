"""Import lookout scripts as modules. Stdlib only — no package install.

unittest discover starts in tests/, so this module is `import harness`.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Hermetic identity policy: tests that simulate transport stalls must never
# write the real data/raw/_ua_policy.json. Tests that exercise the policy
# patch this path themselves.
import ingest_rss  # noqa: E402

ingest_rss.UA_POLICY_PATH = Path(tempfile.mkdtemp(prefix="vigie-test-ua-")) / "_ua_policy.json"
