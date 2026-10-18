"""Run a worker: ``pixi run worker`` (``python -m sightglass.worker``)."""

import asyncio

import procrastinate

from sightglass.log import configure_logging
from sightglass.worker.jobs import make_app, retry_stalled_jobs


async def _recover(app: procrastinate.App) -> None:
    async with app.open_async():
        await retry_stalled_jobs(app)


def main() -> None:
    """Recover jobs a stopped worker left behind, then process analysis jobs until interrupted."""
    configure_logging()
    app = make_app()
    asyncio.run(_recover(app))
    app.run_worker()


if __name__ == "__main__":
    main()
