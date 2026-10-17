import { useState } from "react";
import {
  Button,
  ComboBox,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Select,
  SelectValue,
  type Key,
} from "react-aria-components";
import { useNavigate } from "react-router";
import type { ArtifactRef } from "../api/types";
import { artifactLabel, artifactQuery, pairPath } from "./urls";

interface HeaderProps {
  ecosystem: string;
  pkg: string;
  from: string;
  to: string;
  /** Every version, oldest first, for the pickers. */
  versions: string[];
  artifact: ArtifactRef;
  alternatives: ArtifactRef[];
}

function VersionPicker({
  label,
  value,
  versions,
  onChange,
}: {
  label: string;
  value: string;
  versions: string[];
  onChange: (version: string) => void;
}) {
  const items = versions.map((v) => ({ id: v, name: v })).reverse();
  return (
    <ComboBox
      className="picker"
      value={value}
      defaultItems={items}
      onChange={(key: Key | null) => {
        if (key !== null && String(key) !== value) onChange(String(key));
      }}
    >
      <Label>{label}</Label>
      {/* Input and button form one control; the gap is only between the label and the control. */}
      <div className="picker-control">
        <Input />
        <Button aria-label={`Show ${label.toLowerCase()} versions`}>▾</Button>
      </div>
      <Popover>
        <ListBox>{(item: { id: string; name: string }) => <ListBoxItem id={item.id}>{item.name}</ListBoxItem>}</ListBox>
      </Popover>
    </ComboBox>
  );
}

/** Section 1: the package, both versions with pickers, the artifact picker and a copy-link button. */
export function Header({ ecosystem, pkg, from, to, versions, artifact, alternatives }: HeaderProps) {
  const navigate = useNavigate();
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const defaultArtifact = alternatives.find((a) => a.kind === "wheel") ?? alternatives[0];
  // A different pair of versions has different wheel files, so only the sdist choice carries over.
  const keepKind = artifact.kind === "sdist" ? "?kind=sdist" : "";
  const canonical = `${window.location.origin}${pairPath(ecosystem, pkg, from, to, artifactQuery(artifact, defaultArtifact))}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(canonical);
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
  }

  return (
    <header className="top">
      <div className="wrap">
        <nav className="crumbs" aria-label="Breadcrumb">
          <span>Sightglass</span> / <span>{ecosystem === "pypi" ? "PyPI" : ecosystem}</span> / <span>{pkg}</span>
        </nav>
        <div className="titlerow">
          <h1>
            <span>{pkg}</span> <span className="vs">{`${from} → ${to}`}</span>
          </h1>
          <div className="pickers">
            <VersionPicker
              label="Compare"
              value={from}
              versions={versions}
              onChange={(v) => void navigate(pairPath(ecosystem, pkg, v, to, keepKind))}
            />
            <VersionPicker
              label="to"
              value={to}
              versions={versions}
              onChange={(v) => void navigate(pairPath(ecosystem, pkg, from, v, keepKind))}
            />
          </div>
          <div className="permalink">
            <code className="url">{canonical}</code>
            <button type="button" className="btn" onClick={() => void copy()}>
              Copy link
            </button>
            <span role="status" aria-live="polite">
              {copied === "copied"
                ? "Link copied"
                : copied === "failed"
                  ? "Couldn't copy; select the link instead"
                  : ""}
            </span>
          </div>
        </div>
        {alternatives.length > 1 ? (
          <Select
            className="artifact"
            value={artifact.new_filename}
            onChange={(key: Key | null) => {
              const chosen = alternatives.find((a) => a.new_filename === key);
              if (chosen) void navigate(pairPath(ecosystem, pkg, from, to, artifactQuery(chosen, defaultArtifact)));
            }}
          >
            <Label>Artifact</Label>
            <Button>
              <SelectValue />
              <span className="arrow" aria-hidden="true">
                ▾
              </span>
            </Button>
            <Popover>
              <ListBox>
                {alternatives.map((a) => (
                  <ListBoxItem key={a.new_filename} id={a.new_filename} textValue={artifactLabel(a)}>
                    {artifactLabel(a)}
                  </ListBoxItem>
                ))}
              </ListBox>
            </Popover>
          </Select>
        ) : (
          <p className="artifact">Artifact: {artifactLabel(artifact)}</p>
        )}
      </div>
    </header>
  );
}
