//! Line diffs between two versions of a file, as unified hunks with line numbers.
//!
//! Lines are compared as raw bytes, newline included, so a file that only lost its final newline still differs; text is
//! decoded for display only. Inputs over the size or line limits aren't diffed, and a deadline bounds the work on
//! pathological inputs: past it the diff is still correct but may not be minimal, and says so.

use std::time::{Duration, Instant};

use similar::{Algorithm, DiffOp, DiffTag, capture_diff_slices_deadline, group_diff_ops};

/// Limits that bound the work a diff can cause.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Limits {
    /// Largest input, in bytes, on either side.
    pub max_size: u64,
    /// Most lines on either side.
    pub max_lines: usize,
    /// Time after which the diff stops looking for a minimal result.
    pub timeout: Duration,
    /// Unchanged lines kept around each change.
    pub context: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_size: 4 * 1024 * 1024,
            max_lines: 100_000,
            timeout: Duration::from_secs(2),
            context: 3,
        }
    }
}

/// What a diff line is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LineKind {
    Context,
    Added,
    Removed,
}

impl LineKind {
    /// The kind as a lowercase name.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Context => "context",
            Self::Added => "added",
            Self::Removed => "removed",
        }
    }
}

/// One line of a hunk, with its 1-based line numbers on the sides it appears on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Line {
    pub kind: LineKind,
    pub old_line: Option<usize>,
    pub new_line: Option<usize>,
    /// The line without its newline, decoded as UTF-8 with invalid bytes replaced.
    pub text: String,
    /// The line is the last in its file and has no newline.
    pub missing_newline: bool,
}

/// A unified diff hunk. Starts are 1-based; an empty side's start is the line before it, as in `diff -u`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Hunk {
    pub old_start: usize,
    pub old_len: usize,
    pub new_start: usize,
    pub new_len: usize,
    pub lines: Vec<Line>,
}

/// The hunks of a diff and its line counts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diff {
    pub hunks: Vec<Hunk>,
    pub added: usize,
    pub removed: usize,
    /// The deadline was reached, so the diff may not be minimal.
    pub approximate: bool,
}

impl Diff {
    /// Every added line, with its line number in the new file.
    pub fn added_lines(&self) -> impl Iterator<Item = (usize, &str)> {
        self.hunks
            .iter()
            .flat_map(|h| &h.lines)
            .filter(|l| l.kind == LineKind::Added)
            .filter_map(|l| Some((l.new_line?, l.text.as_str())))
    }
}

/// The result of diffing two inputs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FileDiff {
    Lines(Diff),
    /// An input is over the size or line limit.
    TooLarge,
}

fn split_lines(data: &[u8]) -> Vec<&[u8]> {
    data.split_inclusive(|&b| b == b'\n').collect()
}

fn line(kind: LineKind, old_line: Option<usize>, new_line: Option<usize>, raw: &[u8]) -> Line {
    let missing_newline = !raw.ends_with(b"\n");
    let raw = raw.strip_suffix(b"\n").unwrap_or(raw);
    Line {
        kind,
        old_line,
        new_line,
        text: String::from_utf8_lossy(raw).into_owned(),
        missing_newline,
    }
}

fn start(range: &std::ops::Range<usize>) -> usize {
    if range.is_empty() {
        range.start
    } else {
        range.start + 1
    }
}

fn hunk(group: &[DiffOp], old: &[&[u8]], new: &[&[u8]]) -> Hunk {
    let (first, last) = (&group[0], &group[group.len() - 1]);
    let old_range = first.old_range().start..last.old_range().end;
    let new_range = first.new_range().start..last.new_range().end;
    let mut lines = Vec::new();
    for op in group {
        let (tag, o, n) = op.as_tag_tuple();
        if tag == DiffTag::Equal {
            lines.extend(
                o.zip(n)
                    .map(|(i, j)| line(LineKind::Context, Some(i + 1), Some(j + 1), old[i])),
            );
            continue;
        }
        lines.extend(o.map(|i| line(LineKind::Removed, Some(i + 1), None, old[i])));
        lines.extend(n.map(|j| line(LineKind::Added, None, Some(j + 1), new[j])));
    }
    Hunk {
        old_start: start(&old_range),
        old_len: old_range.len(),
        new_start: start(&new_range),
        new_len: new_range.len(),
        lines,
    }
}

/// Diff two versions of a file line by line.
#[must_use]
pub fn diff(old: &[u8], new: &[u8], limits: &Limits) -> FileDiff {
    let too_big = |data: &[u8]| u64::try_from(data.len()).map_or(true, |n| n > limits.max_size);
    if too_big(old) || too_big(new) {
        return FileDiff::TooLarge;
    }
    let (old_lines, new_lines) = (split_lines(old), split_lines(new));
    if old_lines.len() > limits.max_lines || new_lines.len() > limits.max_lines {
        return FileDiff::TooLarge;
    }
    let deadline = Instant::now() + limits.timeout;
    // Histogram was benchmarked too: 300 times slower when only a few lines match (benches/diff.rs).
    let ops =
        capture_diff_slices_deadline(Algorithm::Myers, &old_lines, &new_lines, Some(deadline));
    let approximate = Instant::now() >= deadline;
    let (mut added, mut removed) = (0, 0);
    for op in &ops {
        if op.tag() != DiffTag::Equal {
            removed += op.old_range().len();
            added += op.new_range().len();
        }
    }
    let hunks = group_diff_ops(ops, limits.context)
        .iter()
        .map(|group| hunk(group, &old_lines, &new_lines))
        .collect();
    FileDiff::Lines(Diff {
        hunks,
        added,
        removed,
        approximate,
    })
}

#[cfg(test)]
mod tests;
