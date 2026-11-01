#!/usr/bin/env bash
# Runs the libFuzzer binaries built by make fuzztest, each for FUZZ_TIME seconds
# (default 15). Usage: fuzz.sh <test .env file> "<modules>" "<filter>" ; no module =
# every binary in FUZZ_BIN_PATH, a module keeps <app>_<module> and <app>_<module>_*,
# a filter keeps the binaries whose name contains it. Per binary state lives in
# <fuzz>/work/<binary>/: corpus/ is replayed and grown by every run, artifacts/ keeps
# the crash-* inputs. <binary>.dict and <binary>.seeds/ next to a binary are its
# dictionary and its read-only seed corpus; FUZZ_ARGS are extra libFuzzer flags,
# parsed after the defaults so they win.
set -uo pipefail

# shellcheck source=/dev/null
source "$1"
module_list="$2"
name_filter="$3"

fuzz_time="${FUZZ_TIME:-15}"
log_dir="$FUZZ_PATH/logs"
candidates=()
bins=()

shopt -s nullglob
if [[ -z "${module_list// }" || "${module_list// }" == "all" ]]; then
    candidates=("$FUZZ_BIN_PATH"/*)
else
    for module in $module_list; do
        before=${#candidates[@]}
        for bin in "$FUZZ_BIN_PATH/${APP_NAME}_${module}${TEST_BIN_EXT}" "$FUZZ_BIN_PATH/${APP_NAME}_${module}_"*; do
            [[ -e "$bin" ]] && candidates+=("$bin")
        done
        [[ ${#candidates[@]} -gt $before ]] || printf 'Warning: no fuzzer for module %s\n' "$module" >&2
    done
fi

for bin in "${candidates[@]}"; do
    [[ -f "$bin" && -x "$bin" && "$(basename -- "$bin")" == *"$name_filter"* ]] && bins+=("$bin")
done

if [[ ${#bins[@]} -eq 0 ]]; then
    printf 'Error: no fuzzer binaries found in %s\n' "$FUZZ_BIN_PATH" >&2
    exit 1
fi

read -ra wrapper <<< "${DEBUGGER:-} ${DEBUGGER_ARGS:-}"
read -ra extra_args <<< "${FUZZ_ARGS:-}"
mkdir -p "$log_dir"
cd "$FUZZ_PATH" || exit 1

failed=0
for bin in "${bins[@]}"; do
    name="$(basename -- "$bin")"
    work="$FUZZ_PATH/work/$name"
    mkdir -p "$work/corpus" "$work/artifacts"

    fuzz_flags=("-max_total_time=$fuzz_time" -timeout=10 -use_value_profile=1 -print_final_stats=1
        "-artifact_prefix=$work/artifacts/")
    [[ -f "$bin.dict" ]] && fuzz_flags+=("-dict=$bin.dict")
    inputs=("$work/corpus")
    [[ -d "$bin.seeds" ]] && inputs+=("$bin.seeds")
    cmd=(timeout -k 10 "$((fuzz_time + 60))" env "${wrapper[@]}" "$bin" "${fuzz_flags[@]}" "${extra_args[@]}" "${inputs[@]}")

    printf '\n# fuzzing: %s for %ss\n# command: %s\n\n' "$name" "$fuzz_time" "${cmd[*]}"
    "${cmd[@]}" 2>&1 | tee "$log_dir/$name.log"
    code="${PIPESTATUS[0]}"
    if [[ "$code" != "0" ]]; then
        failed=$((failed + 1))
        printf '\n--- %s failed with exit code %s ---\nlog: %s/%s.log\nartifacts: %s/artifacts (replay: %s <artifact>)\n' \
            "$name" "$code" "$log_dir" "$name" "$work" "$bin"
    else
        printf '\n# %s: %s\n' "$name" "$(sed -n 's/^#[0-9]*[[:space:]]*DONE[[:space:]]*//p' "$log_dir/$name.log" | tail -n 1)"
    fi
done

printf '\nfuzz: %d binaries, %d failed\n' "${#bins[@]}" "$failed"
[[ "$failed" -eq 0 ]]
