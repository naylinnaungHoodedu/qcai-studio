"""Write docs/security/authorization-matrix.md from the API's route policies (plan task 1.2).

Run: python scripts/authorization_matrix.py           (writes the file)
     python scripts/authorization_matrix.py --check   (exits 1 if the file is out of date)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
MATRIX_PATH = REPO_ROOT / "docs" / "security" / "authorization-matrix.md"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Importing the app must not create or touch a database file.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.authorization import render_matrix, route_keys, served_routes  # noqa: E402
from app.main import ROUTERS, app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed matrix is out of date")
    args = parser.parse_args()
    expected = render_matrix(route_keys(served_routes(app, ROUTERS)))
    if args.check:
        current = MATRIX_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") if MATRIX_PATH.exists() else ""
        if current != expected:
            print(f"{MATRIX_PATH.relative_to(REPO_ROOT)} is out of date; run python scripts/authorization_matrix.py")
            return 1
        print(f"{MATRIX_PATH.relative_to(REPO_ROOT)} is current")
        return 0
    MATRIX_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"wrote {MATRIX_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
