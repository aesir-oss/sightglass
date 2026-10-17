//! Tests for line diffs.

use std::fmt::Write;

use super::*;

fn lines(diff: &FileDiff) -> &Diff {
    match diff {
        FileDiff::Lines(d) => d,
        FileDiff::TooLarge => panic!("expected a diff"),
    }
}

fn render(d: &Diff) -> String {
    let mut out = String::new();
    for h in &d.hunks {
        writeln!(
            out,
            "@@ -{},{} +{},{} @@",
            h.old_start, h.old_len, h.new_start, h.new_len
        )
        .unwrap();
        for l in &h.lines {
            let sign = match l.kind {
                LineKind::Context => ' ',
                LineKind::Added => '+',
                LineKind::Removed => '-',
            };
            writeln!(out, "{sign}{}", l.text).unwrap();
            if l.missing_newline {
                out += "\\ No newline at end of file\n";
            }
        }
    }
    out
}

fn numbered_lines(lines: impl Iterator<Item = usize>) -> String {
    lines.fold(String::new(), |mut out, i| {
        writeln!(out, "line {i}").unwrap();
        out
    })
}

fn numbered(n: usize) -> String {
    numbered_lines(1..=n)
}

#[test]
fn identical_inputs_have_no_hunks() {
    let d = diff(b"a\nb\n", b"a\nb\n", &Limits::default());
    assert_eq!(
        d,
        FileDiff::Lines(Diff {
            hunks: vec![],
            added: 0,
            removed: 0,
            approximate: false
        })
    );
}

#[test]
fn change_in_the_middle_has_context_and_line_numbers() {
    let old = numbered(10);
    let new = old.replace("line 5\n", "line five\nline 5.5\n");
    let d = diff(old.as_bytes(), new.as_bytes(), &Limits::default());
    let d = lines(&d);
    assert_eq!(
        render(d),
        "@@ -2,7 +2,8 @@\n line 2\n line 3\n line 4\n-line 5\n+line five\n+line 5.5\n line 6\n line 7\n line 8\n"
    );
    assert_eq!((d.added, d.removed), (2, 1));
    let removed = &d.hunks[0].lines[3];
    assert_eq!((removed.old_line, removed.new_line), (Some(5), None));
    let context = &d.hunks[0].lines[6];
    assert_eq!((context.old_line, context.new_line), (Some(6), Some(7)));
}

#[test]
fn distant_changes_are_separate_hunks() {
    let old = numbered(30);
    let new = old
        .replace("line 2\n", "line two\n")
        .replace("line 28\n", "line twenty-eight\n");
    let d = diff(old.as_bytes(), new.as_bytes(), &Limits::default());
    let starts: Vec<_> = lines(&d)
        .hunks
        .iter()
        .map(|h| (h.old_start, h.new_start))
        .collect();
    assert_eq!(starts, vec![(1, 1), (25, 25)]);
}

#[test]
fn context_setting_is_used() {
    let old = numbered(10);
    let new = old.replace("line 5\n", "line five\n");
    let limits = Limits {
        context: 0,
        ..Limits::default()
    };
    assert_eq!(
        render(lines(&diff(old.as_bytes(), new.as_bytes(), &limits))),
        "@@ -5,1 +5,1 @@\n-line 5\n+line five\n"
    );
}

#[test]
fn empty_sides_use_the_line_before() {
    let created = diff(b"", b"a\nb\n", &Limits::default());
    assert_eq!(render(lines(&created)), "@@ -0,0 +1,2 @@\n+a\n+b\n");
    let deleted = diff(b"a\n", b"", &Limits::default());
    assert_eq!(render(lines(&deleted)), "@@ -1,1 +0,0 @@\n-a\n");
    let appended = diff(b"a\n", b"a\nb\n", &Limits::default());
    assert_eq!(render(lines(&appended)), "@@ -1,1 +1,2 @@\n a\n+b\n");
}

#[test]
fn missing_final_newline_is_a_change() {
    let d = diff(b"a\nb", b"a\nb\n", &Limits::default());
    assert_eq!(
        render(lines(&d)),
        "@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+b\n"
    );
}

#[test]
fn bytes_are_compared_exactly_and_decoded_for_display() {
    let d = diff(b"x = '\xe9'\r\n", b"x = '\xe8'\r\n", &Limits::default());
    let d = lines(&d);
    assert_eq!((d.added, d.removed), (1, 1));
    assert_eq!(d.hunks[0].lines[0].text, "x = '\u{fffd}'\r");
}

#[test]
fn added_lines_view() {
    let old = numbered(20);
    let new = old
        .replace("line 3\n", "import base64\n")
        .replace("line 15\n", "line 15\nexec(base64.b64decode(blob))\n");
    let d = diff(old.as_bytes(), new.as_bytes(), &Limits::default());
    let added: Vec<_> = lines(&d).added_lines().collect();
    assert_eq!(
        added,
        vec![(3, "import base64"), (16, "exec(base64.b64decode(blob))")]
    );
}

#[test]
fn inputs_over_the_limits_are_too_large() {
    let size = Limits {
        max_size: 3,
        ..Limits::default()
    };
    assert_eq!(diff(b"abcd", b"", &size), FileDiff::TooLarge);
    assert_eq!(diff(b"", b"abcd", &size), FileDiff::TooLarge);
    let count = Limits {
        max_lines: 2,
        ..Limits::default()
    };
    assert_eq!(diff(b"a\nb\nc\n", b"a\n", &count), FileDiff::TooLarge);
    assert!(matches!(
        diff(b"a\nb\n", b"a\n", &count),
        FileDiff::Lines(_)
    ));
}

#[test]
fn zero_timeout_still_gives_a_correct_diff() {
    let old = numbered(2000);
    let new = numbered_lines((1..=2000).rev());
    let limits = Limits {
        timeout: Duration::ZERO,
        context: 10_000,
        ..Limits::default()
    };
    let d = diff(old.as_bytes(), new.as_bytes(), &limits);
    let d = lines(&d);
    assert!(d.approximate);
    let mut rebuilt = String::new();
    for h in &d.hunks {
        for l in h.lines.iter().filter(|l| l.kind != LineKind::Removed) {
            rebuilt += &l.text;
            rebuilt += "\n";
        }
    }
    assert_eq!(rebuilt, new);
}

#[test]
fn line_kind_names() {
    let names: Vec<_> = [LineKind::Context, LineKind::Added, LineKind::Removed]
        .iter()
        .map(|k| k.as_str())
        .collect();
    assert_eq!(names, ["context", "added", "removed"]);
}
