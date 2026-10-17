//! Line diff benchmarks on large inputs: `pixi run bench-rs`.

use std::fmt::Write;
use std::hint::black_box;

use criterion::{Criterion, criterion_group, criterion_main};
use sightglass_core::diff::{Limits, diff};

/// A Python-like source file of `n` lines.
fn source(n: usize, salt: &str) -> String {
    let mut out = String::new();
    for i in 0..n {
        if i % 20 == 0 {
            writeln!(out, "def handler_{i}(event, context):").unwrap();
        } else {
            writeln!(out, "    value_{i} = compute(event, {i}, {salt:?})").unwrap();
        }
    }
    out
}

fn bench(c: &mut Criterion) {
    let limits = Limits::default();
    let base = source(50_000, "a");
    let mut edited = base.clone();
    for i in (0..50_000).step_by(1_000) {
        edited = edited.replacen(
            &format!("compute(event, {i},"),
            &format!("compute(event, {i} + 1,"),
            1,
        );
    }
    let rewritten = source(50_000, "b");
    let reversed = base.lines().rev().fold(String::new(), |mut out, l| {
        writeln!(out, "{l}").unwrap();
        out
    });
    let minified = "x=1;".repeat(1_000_000);
    let mut group = c.benchmark_group("diff");
    group.sample_size(10);
    group.bench_function("50k lines identical", |b| {
        b.iter(|| {
            diff(
                black_box(base.as_bytes()),
                black_box(base.as_bytes()),
                &limits,
            )
        });
    });
    group.bench_function("50k lines, 50 scattered edits", |b| {
        b.iter(|| {
            diff(
                black_box(base.as_bytes()),
                black_box(edited.as_bytes()),
                &limits,
            )
        });
    });
    group.bench_function("50k lines, all but every 20th changed", |b| {
        b.iter(|| {
            diff(
                black_box(base.as_bytes()),
                black_box(rewritten.as_bytes()),
                &limits,
            )
        });
    });
    group.bench_function("50k lines reversed", |b| {
        b.iter(|| {
            diff(
                black_box(base.as_bytes()),
                black_box(reversed.as_bytes()),
                &limits,
            )
        });
    });
    group.bench_function("4 MB single line", |b| {
        b.iter(|| diff(black_box(minified.as_bytes()), black_box(b"x=2;"), &limits));
    });
    group.finish();
}

criterion_group!(benches, bench);
criterion_main!(benches);
