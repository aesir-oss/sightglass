"""The diff of one file in an analyzed pair, against the previous release or against the source.

Contents come from the blob store, where the worker put them, and are diffed by the Rust core on request. Lines that a
signal's evidence points at are marked. Binary files, files whose content wasn't kept, and files too large to diff
return metadata only.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from sightglass import _core
from sightglass.api.deps import Index, get_blobs, get_index, get_session
from sightglass.api.pairs import find_analysis, locate
from sightglass.db import models
from sightglass.storage.blobs import BlobCorruptError, BlobNotFoundError, BlobStore

router = APIRouter()

Base = Literal["previous", "source"]


class DiffLine(BaseModel):
    """One line of a hunk; ``marked`` when a signal's evidence points at it."""

    kind: Literal["context", "added", "removed"]
    old_line: int | None
    new_line: int | None
    text: str
    missing_newline: bool
    marked: bool


class Hunk(BaseModel):
    """A unified diff hunk."""

    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[DiffLine]


class FileDiff(BaseModel):
    """A file's diff, or why there is only metadata."""

    path: str
    base: Base
    base_label: str
    status: str
    text: bool
    old_path: str | None
    old_sha256: str | None
    new_sha256: str | None
    old_size: int | None
    new_size: int | None
    diff: Literal["shown", "binary", "too_large", "unavailable", "identical"]
    added: int = 0
    removed: int = 0
    hunks: list[Hunk] = []
    signals: list[str] = []


def _marks(session: Session, analysis_id: int, path: str) -> tuple[set[int], set[int], list[str]]:
    new_lines: set[int] = set()
    old_lines: set[int] = set()
    rules: list[str] = []
    for signal in session.scalars(select(models.Signal).where(models.Signal.analysis_id == analysis_id)):
        for item in signal.evidence.get("items", []):
            if item.get("file") != path:
                continue
            rules.append(signal.rule_id)
            start = item.get("line_start")
            if start is None:
                continue
            span = range(start, (item.get("line_end") or start) + 1)
            (old_lines if item.get("side") == "old" else new_lines).update(span)
    return new_lines, old_lines, sorted(set(rules))


def _source_sha(session: Session, package: str, source: dict[str, Any], source_path: str) -> str | None:
    snapshot_id = session.scalar(
        select(models.SourceSnapshot.id)
        .join(models.Package)
        .where(
            models.Package.name == package,
            models.SourceSnapshot.repository == source["repository"],
            models.SourceSnapshot.commit == source["commit"],
        )
    )
    return session.scalar(
        select(models.File.sha256).where(
            models.File.source_snapshot_id == snapshot_id,
            or_(models.File.path == source_path, models.File.path.endswith("/" + source_path, autoescape=True)),
        )
    )


def _read(blobs: BlobStore, sha256: str | None) -> bytes | None:
    if sha256 is None:
        return b""
    try:
        return blobs.read(sha256)
    except BlobNotFoundError, BlobCorruptError:
        return None


@router.get(
    "/api/{ecosystem}/{package}/{versions}/files/{path:path}",
    operation_id="getFileDiff",
    responses={404: {"description": "Unknown pair, an analysis that isn't done, or a file that isn't in it"}},
)
def get_file_diff(
    ecosystem: Annotated[str, Path(description="Package ecosystem; only pypi for now")],
    package: Annotated[str, Path(description="Package name, in any spelling")],
    versions: Annotated[str, Path(description="`<from>...<to>`, or one version")],
    path: Annotated[str, Path(description="The file's path in the pair, as in the analysis's `files`")],
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    index: Annotated[Index, Depends(get_index)],
    blobs: Annotated[BlobStore, Depends(get_blobs)],
    base: Annotated[Base, Query(description="Diff against the previous release or the source")] = "previous",
    kind: Annotated[Literal["wheel", "sdist"] | None, Query(description="Which artifact kind")] = None,
    wheel: Annotated[str | None, Query(description="The new release's wheel, from `alternatives`")] = None,
) -> FileDiff:
    """One file's diff in an analyzed pair, with the lines signals point at marked."""
    project, old, _, pair, _ = locate(index, ecosystem, package, versions, kind, wheel)
    row = find_analysis(session, project, pair)
    if row is None or row.status != "done" or row.report is None:
        raise HTTPException(404, "this pair isn't analyzed yet; request the pair first")
    entry = next((f for f in row.report.get("files", []) if f["path"] == path), None)
    if entry is None:
        raise HTTPException(404, f"{path} isn't in this pair")

    old_path: str | None = path if entry["old_sha256"] else None
    old_sha: str | None = entry["old_sha256"]
    label = f"{old.version}"
    if base == "source":
        source = row.report.get("source", {})
        check = next((c for c in source.get("files", []) if c["path"] == path), None)
        if source.get("state") != "compared" or check is None:
            raise HTTPException(404, f"{path} has no source to compare with")
        label = source["label"]
        old_path = check["source_path"]
        old_sha = _source_sha(session, project.normalized_name, source, old_path) if old_path else None

    result: dict[str, Any] = {
        "path": path,
        "base": base,
        "base_label": label,
        "status": entry["status"],
        "text": entry["text"],
        "old_path": old_path,
        "old_sha256": old_sha,
        "new_sha256": entry["new_sha256"],
        "old_size": entry["old_size"],
        "new_size": entry["new_size"],
    }
    response.headers["Cache-Control"] = "public, max-age=300"
    if not entry["text"]:
        return FileDiff(diff="binary", **result)
    if old_sha == entry["new_sha256"]:
        return FileDiff(diff="identical", **result)
    before, after = _read(blobs, old_sha), _read(blobs, entry["new_sha256"])
    if before is None or after is None:
        return FileDiff(diff="unavailable", **result)
    computed = _core.diff_lines(before, after)
    if computed.too_large:
        return FileDiff(diff="too_large", **result)
    new_marks, old_marks, rules = _marks(session, row.id, path)
    hunks = [
        Hunk(
            old_start=h.old_start,
            old_len=h.old_len,
            new_start=h.new_start,
            new_len=h.new_len,
            lines=[
                DiffLine(
                    kind=line.kind,
                    old_line=line.old_line,
                    new_line=line.new_line,
                    text=line.text,
                    missing_newline=line.missing_newline,
                    marked=(line.new_line in new_marks) or (line.kind == "removed" and line.old_line in old_marks),
                )
                for line in h.lines
            ],
        )
        for h in computed.hunks
    ]
    return FileDiff(diff="shown", added=computed.added, removed=computed.removed, hunks=hunks, signals=rules, **result)
