#!/usr/bin/env bash
# Run one fuzz target for a fixed time with rustup's nightly toolchain.
# Usage: run.sh <target> [seconds]. New inputs go to work/<target>; corpus/<target> is read as seeds.
# run.sh seeds regenerates the generated part of corpus/.
set -euo pipefail
target="${1:?usage: run.sh <target> [seconds]}"
seconds="${2:-60}"
cd "$(dirname "$0")"
# pixi puts its stable rustc first on PATH; cargo-fuzz needs nightly's.
nightly_bin="$(dirname "$(rustup which --toolchain nightly rustc)")"
export PATH="$nightly_bin:$PATH"
if [[ "$target" == seeds ]]; then
    exec cargo run --quiet --bin make-seeds
fi
mkdir -p "work/$target"
exec cargo fuzz run "$target" "work/$target" "corpus/$target" -- -max_total_time="$seconds"
