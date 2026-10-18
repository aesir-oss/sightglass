"""Review a lockfile change between two git refs of a local checkout, as the GitHub App will for a pull request.

``pixi run review <owner/name> <pull number> <base ref> <head ref>`` reads the lockfile and its workspace manifest at
both refs, records the review and queues the analyses; ``pixi run dev`` then shows it at ``/reviews/<owner>/<name>/
<number>``. It uses the database in ``SIGHTGLASS_DATABASE_URL``, or the local one ``pixi run dev`` uses.
"""

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from sightglass.analyze import database
from sightglass.db.engine import make_engine
from sightglass.ecosystems.pypi import PypiClient
from sightglass.lockfiles.pixi import LockfileError
from sightglass.lockfiles.review import Snapshot, manifest_names, review_lockfile
from sightglass.log import configure_logging, get_logger
from sightglass.worker.jobs import enqueue_analysis, make_app
from sightglass.worker.pipeline import default_cache_dir

log = get_logger("sightglass.review")


class GitError(RuntimeError):
    """A ref or file couldn't be read from the checkout."""


def git(checkout: Path, *args: str) -> bytes:
    """Run a read-only git command in ``checkout`` and return its output."""
    result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise GitError(result.stderr.decode(errors="replace").strip() or f"git {' '.join(args)} failed")
    return result.stdout


def snapshot(checkout: Path, ref: str, lockfile: str) -> Snapshot:
    """The lockfile at ``ref``, with the first manifest found beside it."""
    content = git(checkout, "show", f"{ref}:{lockfile}")
    for name in manifest_names(lockfile):
        try:
            return Snapshot(content, (name, git(checkout, "show", f"{ref}:{name}")))
        except GitError:
            continue
    return Snapshot(content)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(prog="review", description="Review a lockfile change between two git refs.")
    parser.add_argument("repository", help="owner/name, as the review page's URL shows it")
    parser.add_argument("pull_number", type=int, help="pull request number to file the review under")
    parser.add_argument("base", help="base ref, such as main")
    parser.add_argument("head", help="head ref, such as a branch")
    parser.add_argument("--checkout", type=Path, default=Path.cwd(), help="the git checkout (default: here)")
    parser.add_argument("--lockfile", default="pixi.lock", help="the lockfile's path in the repository")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; returns the process exit code."""
    args = parse_args(argv)
    configure_logging()
    if args.repository.count("/") != 1:
        log.error("review_bad_repository", repository=args.repository, expected="owner/name")
        return 2
    try:
        base_sha = git(args.checkout, "rev-parse", f"{args.base}^{{commit}}").decode().strip()
        head_sha = git(args.checkout, "rev-parse", f"{args.head}^{{commit}}").decode().strip()
        base, head = snapshot(args.checkout, base_sha, args.lockfile), snapshot(args.checkout, head_sha, args.lockfile)
    except GitError as exc:
        log.error("review_git_failed", error=str(exc))
        return 1
    with database(default_cache_dir()) as url:
        engine = make_engine(url)
        app = make_app(url)
        try:
            with app.open(), Session(engine) as session:
                review_id = review_lockfile(
                    session,
                    pypi=PypiClient.default(),
                    enqueue=lambda eco, pkg, old, new: enqueue_analysis(app, eco, pkg, old, new),
                    repository=args.repository,
                    pull_number=args.pull_number,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    lockfile_path=args.lockfile,
                    base=base,
                    head=head,
                )
                session.commit()
        except LockfileError as exc:
            log.error("review_lockfile_unreadable", error=str(exc))
            return 1
        finally:
            engine.dispose()
    log.info("review_ready", review_id=review_id, page=f"/reviews/{args.repository}/{args.pull_number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
