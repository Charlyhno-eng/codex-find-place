"""Prepare the frontend as part of the application's single entry point."""

import hashlib
import shutil
import subprocess
from pathlib import Path


def prepare_frontend(project: Path):
    output = project / "osint_picture/static/dist/index.html"
    if not (project / "frontend/src").is_dir():
        # Installed wheels include the compiled frontend rather than its sources.
        if not output.is_file():
            raise RuntimeError("The installed application is missing its frontend assets.")
        return

    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("Install Node.js and npm, then run uv run codex-find-place again.")

    fingerprint = hashlib.sha256()
    for name in ("package.json", "package-lock.json"):
        fingerprint.update((project / name).read_bytes())
    expected = fingerprint.hexdigest()
    stamp = project / "node_modules/.find-place-dependencies"
    if not stamp.is_file() or stamp.read_text() != expected:
        print("Installing frontend dependencies…", flush=True)
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=project, check=True)
        stamp.write_text(expected)

    print("Preparing frontend…", flush=True)
    subprocess.run([npm, "run", "build"], cwd=project, check=True)
