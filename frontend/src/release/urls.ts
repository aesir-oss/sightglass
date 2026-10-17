// Page URLs for the release diff page. The canonical form always names both versions.
import type { ArtifactRef } from "../api/types";

/** `?kind=sdist` or `?wheel=<file>` for a non-default artifact; nothing for the default wheel pair. */
export function artifactQuery(artifact: ArtifactRef, defaultArtifact: ArtifactRef | undefined): string {
  if (defaultArtifact && artifact.new_filename === defaultArtifact.new_filename) return "";
  if (artifact.kind === "sdist") return "?kind=sdist";
  return `?wheel=${encodeURIComponent(artifact.new_filename)}`;
}

export function pairPath(ecosystem: string, pkg: string, from: string, to: string, query = ""): string {
  return `/${ecosystem}/${encodeURIComponent(pkg)}/${encodeURIComponent(from)}...${encodeURIComponent(to)}${query}`;
}

/** Describe an artifact pair for the picker: the sdist, or the wheel's tag. */
export function artifactLabel(artifact: ArtifactRef): string {
  if (artifact.kind === "sdist") return "Source distribution (sdist)";
  const tag = artifact.new_filename
    .replace(/\.whl$/, "")
    .split("-")
    .slice(-3)
    .join("-");
  return artifact.match === "platform_changed" ? `Wheel ${tag} (platform tag changed)` : `Wheel ${tag}`;
}
