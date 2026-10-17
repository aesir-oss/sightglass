"""The report stored with each analysis: what the page shows besides the signals.

It holds the two artifacts, every file pair, the source and sdist checks, and a before-and-after table of release
facts. It is computed once, when the pair is analyzed, and stored as JSON on the ``analysis`` row.
"""

from typing import Any

from sightglass.ecosystems.provenance import Provenance
from sightglass.ecosystems.pypi import PypiFile
from sightglass.ecosystems.sources import CouldNotCompare, SourceSnapshot
from sightglass.rules.base import PairAnalysis, ReleaseFacts
from sightglass.rules.build import generator
from sightglass.rules.dependencies import read_requirements
from sightglass.rules.pairing import IndexedFile, SourceComparison

REPORT_VERSION = 1


def _artifact(file: PypiFile) -> dict[str, Any]:
    return {"filename": file.filename, "kind": file.kind, "sha256": file.sha256, "size": file.size}


def _publisher(provenance: Provenance | None) -> dict[str, Any] | None:
    if provenance is None or not provenance.attestations:
        return None
    p = provenance.attestations[0].publisher
    return {"kind": p.kind, "repository": p.repository, "workflow": p.workflow, "environment": p.environment}


def _facts(release: ReleaseFacts, file: PypiFile, files: list[IndexedFile], texts: dict[str, str]) -> dict[str, Any]:
    requirements = read_requirements(texts)
    provenance = release.provenance
    return {
        "version": release.version,
        "published_at": release.published_at.isoformat() if release.published_at else None,
        "attestation": provenance.status if provenance else "unknown",
        "publisher": _publisher(provenance),
        "build_tool": generator(texts),
        "file_count": len(files),
        "total_size": sum(f.size for f in files),
        "artifact_sha256": file.sha256,
        "requires_dist": (
            sorted(e.text for entries in requirements.by_name.values() for e in entries) if requirements else None
        ),
    }


def _checks(comparison: SourceComparison) -> dict[str, Any]:
    return {
        "root": comparison.root,
        "files": [
            {"path": c.path, "status": c.status, "source_path": c.source_path, "text": c.text} for c in comparison.files
        ],
        "excluded": list(comparison.excluded),
    }


def _source(analysis: PairAnalysis, snapshot: SourceSnapshot | None) -> dict[str, Any]:
    if isinstance(analysis.source, CouldNotCompare):
        repo = analysis.source.repository
        return {
            "state": "could_not_compare",
            "reason": analysis.source.reason,
            "detail": analysis.source.detail,
            "repository": repo.slug if repo else None,
        }
    if isinstance(analysis.source, SourceComparison) and snapshot is not None:
        return {
            "state": "compared",
            "label": analysis.source_label,
            "repository": snapshot.repository.slug,
            "commit": snapshot.commit,
            "ref": snapshot.ref,
            "origin": snapshot.origin,
            **_checks(analysis.source),
        }
    return {"state": "unknown"}


def build_report(
    analysis: PairAnalysis,
    *,
    old_file: PypiFile,
    new_file: PypiFile,
    old_files: list[IndexedFile],
    new_files: list[IndexedFile],
    snapshot: SourceSnapshot | None,
) -> dict[str, Any]:
    """The JSON report for one analyzed artifact pair."""
    return {
        "version": REPORT_VERSION,
        "artifacts": {"old": _artifact(old_file), "new": _artifact(new_file)},
        "files": [
            {
                "path": p.path,
                "status": p.status,
                "text": p.text,
                "compiled": any(f.compiled for f in (p.old, p.new) if f is not None),
                "old_size": p.old.size if p.old else None,
                "new_size": p.new.size if p.new else None,
                "old_sha256": p.old.sha256 if p.old else None,
                "new_sha256": p.new.sha256 if p.new else None,
            }
            for p in analysis.files
        ],
        "source": _source(analysis, snapshot),
        "sdist": _checks(analysis.sdist) if analysis.sdist else None,
        "facts": {
            "old": _facts(analysis.old, old_file, old_files, analysis.old_text),
            "new": _facts(analysis.new, new_file, new_files, analysis.new_text),
        },
    }
