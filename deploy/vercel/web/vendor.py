"""Copy the few shared ``mfhelper`` modules this service needs into its own root.

The Vercel service root is ``deploy/vercel/web`` so only a small dependency set
is installed (not the repo's analytics/Sheets/MCP requirements). The importer
code lives in the shared ``mfhelper`` package, so ``vercel.json`` runs this
script as the service build command. The copy is generated, git-ignored, and
checked by ``tests/test_vercel_packaging.py``.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

MODULES = (
    "__init__.py",
    "casl_import.py",
    "holdings_cache.py",
    "upload_ticket.py",
    "vercel_holdings_cache.py",
    "vercel_holdings_import_app.py",
)


def vendor(destination: Path | None = None) -> int:
    here = Path(__file__).resolve().parent
    source = here.parents[2] / "mfhelper"
    target = destination or here / "mfhelper"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in MODULES:
        shutil.copy2(source / name, target / name)
    return len(MODULES)


if __name__ == "__main__":
    count = vendor(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(f"vendored {count} mfhelper modules")
