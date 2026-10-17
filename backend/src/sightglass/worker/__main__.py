"""Run a worker: ``pixi run worker`` (``python -m sightglass.worker``)."""

from sightglass.log import configure_logging
from sightglass.worker.jobs import make_app


def main() -> None:
    """Process analysis jobs until interrupted."""
    configure_logging()
    make_app().run_worker()


if __name__ == "__main__":
    main()
