"""Write a fake password-protected CDSL CAS PDF for safe end-to-end importer tests.

The PDF contains one made-up fund and is encrypted with the fake PAN ABCDE1234F.
It holds no real personal data.

Usage: python scripts/make_synthetic_cas.py [output.pdf]
"""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_casl_import import _make_encrypted_cdsl_pdf  # noqa: E402


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic-cas.pdf")
    output.write_bytes(_make_encrypted_cdsl_pdf())
    print(f"Wrote {output} (password: ABCDE1234F)")


if __name__ == "__main__":
    main()
