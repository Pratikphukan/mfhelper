import ast
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "deploy" / "vercel" / "web"


def _vendor_module():
    return runpy.run_path(str(WEB / "vendor.py"))


def _mfhelper_imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mfhelper"):
            parts = node.module.split(".")
            if len(parts) > 1:
                modules.add(parts[1] + ".py")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "mfhelper" and len(parts) > 1:
                    modules.add(parts[1] + ".py")
    return modules


def test_vendor_list_covers_every_transitive_mfhelper_import_of_the_app():
    listed = set(_vendor_module()["MODULES"])
    pending = ["vercel_holdings_import_app.py"]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(_mfhelper_imports(ROOT / "mfhelper" / name))

    assert seen <= listed, f"vendor.py is missing: {sorted(seen - listed)}"


def test_vendored_service_imports_without_the_rest_of_the_repo(tmp_path):
    vendored = tmp_path / "service"
    count = _vendor_module()["vendor"](vendored / "mfhelper")
    (vendored / "main.py").write_text((WEB / "main.py").read_text())
    assert count == len(_vendor_module()["MODULES"])

    env = {
        "PATH": "/usr/bin:/bin",
        "MFHELPER_SESSION_SECRET": "s" * 48,
    }
    result = subprocess.run(
        [sys.executable, "-c", "import main; print(main.app.title)"],
        cwd=vendored,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert not (vendored / "analytics_main.py").exists()


def test_service_requirements_stay_light():
    requirements = (WEB / "requirements.txt").read_text().lower()

    for heavy in ("matplotlib", "yfinance", "gspread", "anthropic", "mcp", "pandas", "oci"):
        assert heavy not in requirements.replace("python-multipart", "")
    assert "vercel-blob" in requirements


def test_vercel_json_routes_only_the_two_services_and_exposes_nothing_else():
    config = json.loads((ROOT / "vercel.json").read_text())

    assert set(config["services"]) == {"web", "upload_token"}
    rewrites = config["rewrites"]
    assert rewrites[0]["source"].startswith("/upload-token/")
    assert rewrites[0]["destination"] == {"service": "upload_token"}
    assert rewrites[-1]["destination"] == {"service": "web"}
    assert config["services"]["web"]["buildCommand"] == "python3 vendor.py"
