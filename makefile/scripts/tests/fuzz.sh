#!/usr/bin/env bash
# Runs the libFuzzer binaries built by make fuzztest, each for FUZZ_TIME seconds
# (default 15). Usage: fuzz.sh <test .env file> "<modules>" ; no module = every
# binary in FUZZ_BIN_PATH. Per binary state lives in <fuzz>/work/<binary>/: corpus/
# is replayed and grown by every run, artifacts/ keeps the crash-* inputs.
set -uo pipefail

# shellcheck source=/dev/null
source "$1"
module_list="$2"

fuzz_time="${FUZZ_TIME:-15}"
log_dir="$FUZZ_PATH/logs"
bins=()

shopt -s nullglob
if [[ -z "${module_list// }" || "${module_list// }" == "all" ]]; then
    bins=("$FUZZ_BIN_PATH"/*)
else
    for module in $module_list; do
        bins+=("$FUZZ_BIN_PATH/${APP_NAME}_${module}${TEST_BIN_EXT}")
    done
fi

if [[ ${#bins[@]} -eq 0 ]]; then
    printf 'Error: no fuzzer binaries found in %s\n' "$FUZZ_BIN_PATH" >&2
    exit 1
fi

read -ra wrapper <<< "${DEBUGGER:-} ${DEBUGGER_ARGS:-}"
mkdir -p "$log_dir"
cd "$FUZZ_PATH" || exit 1

failed=0
for bin in "${bins[@]}"; do
    name="$(basename -- "$bin")"
    if [[ ! -x "$bin" ]]; then
        printf 'Error: fuzzer %s not found\n' "$bin" >&2
        failed=$((failed + 1))
        continue
    fi

    work="$FUZZ_PATH/work/$name"
    mkdir -p "$work/corpus" "$work/artifacts"
    cmd=(timeout -k 10 "$((fuzz_time + 60))" env "${wrapper[@]}" "$bin"
        "-max_total_time=$fuzz_time" "-artifact_prefix=$work/artifacts/" "$work/corpus")

    printf '\n# fuzzing: %s for %ss\n# command: %s\n\n' "$name" "$fuzz_time" "${cmd[*]}"
    "${cmd[@]}" 2>&1 | tee "$log_dir/$name.log"
    code="${PIPESTATUS[0]}"
    if [[ "$code" != "0" ]]; then
        failed=$((failed + 1))
        printf '\n--- %s failed with exit code %s ---\nlog: %s/%s.log\nartifacts: %s/artifacts (replay: %s <artifact>)\n' \
            "$name" "$code" "$log_dir" "$name" "$work" "$bin"
    fi
done

printf '\nfuzz: %d binaries, %d failed\n' "${#bins[@]}" "$failed"
[[ "$failed" -eq 0 ]]
