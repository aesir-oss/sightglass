"""Tests for the development launcher's process list."""

import sys

from sightglass import devserver


def test_commands_run_api_worker_and_vite() -> None:
    """The API reloads on changes on API_PORT, a worker runs from the same Python, and Vite runs in frontend/."""
    procs = {name: (cmd, cwd) for name, cmd, cwd in devserver.commands()}
    api, _ = procs["api"]
    assert api[:3] == [sys.executable, "-m", "uvicorn"] and "--reload" in api and str(devserver.API_PORT) in api
    assert procs["worker"][0] == [sys.executable, "-m", "sightglass.worker"]
    assert procs["web"] == (["pnpm", "run", "dev"], devserver.FRONTEND)
    assert (devserver.FRONTEND / "package.json").is_file()
