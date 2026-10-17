"""The development launcher with real child processes."""

import os
import sys
import time

import pytest

from sightglass import devserver

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


@pytest.mark.integration
def test_one_exit_stops_the_others() -> None:
    """When one process exits, its code is returned and the others are stopped."""
    started = time.monotonic()
    code = devserver.run(
        [("long", SLEEP, None), ("quits", [sys.executable, "-c", "raise SystemExit(3)"], None)], dict(os.environ), 0.05
    )
    assert code == 3 and time.monotonic() - started < 15


@pytest.mark.integration
def test_ctrl_c_stops_everything() -> None:
    """Ctrl-C stops every process and exits cleanly."""

    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    assert devserver.run([("long", SLEEP, None)], dict(os.environ), sleep=interrupt) == 0
