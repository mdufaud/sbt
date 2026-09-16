#!/usr/bin/env bash
# Cross-platform binary runner. Copied verbatim into <build>/runner.sh by the
# builder, next to the generated runner.env (emulator command + its env).
# Usage: runner.sh <binary> [args...]
# The binary is exec'd exactly as passed — no path or suffix rewriting — under
# the build's emulator when there is one: wine (windows), qemu-<arch> (foreign
# linux machine), node (web tests). Exit code is the binary's.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$script_dir/runner.env"

if [ "$#" -eq 0 ]; then
    echo "usage: runner.sh <binary> [args...]" >&2
    exit 2
fi

if [ -n "$TEST_RUNNER" ]; then
    exec "$TEST_RUNNER" "$@"
fi
exec "$@"
