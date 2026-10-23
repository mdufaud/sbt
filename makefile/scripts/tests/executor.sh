#!/bin/bash
# Static test executor. Copied verbatim into <build>/test/execute_tests.sh by
# generate.sh, which writes the sibling .env (paths + platform facts + app test
# env). Sourced config: APP_NAME TEST_PATH TEST_BIN_PATH PROJECT_ROOT_PATH
# TEST_RUNNER TEST_BIN_EXT and the SBT_* platform facts. Cross builds launch
# test binaries through the build's runner.sh (wine/qemu/node + its env);
# native ones may wrap in a debugger directly.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.env"
if [ -n "${TEST_BENCH:-}" ]; then
    TEST_PATH="$BENCH_PATH"
    TEST_BIN_PATH="$BENCH_BIN_PATH"
    TEST_PROFILE=benchmark
fi
SANITIZER_FAILURE_PATTERN='^(==[0-9]+==)?(ERROR|WARNING|SUMMARY): (AddressSanitizer|LeakSanitizer|ThreadSanitizer|UndefinedBehaviorSanitizer|MemorySanitizer|HWAddressSanitizer):|^.+:[0-9]+(:[0-9]+)?: runtime error:'
# before the profile source: profiles reference $REPORT_DIR; unset-only default
# so an explicit empty TEST_REPORT_FLAGS stays an opt-out
export REPORT_DIR="$TEST_PATH/reports"
mkdir -p "$REPORT_DIR"
: "${TEST_REPORT_FLAGS=--gtest_output=xml:$REPORT_DIR/}"
# Test framework profile (gtest by default). Sourced after .env so any flag the
# project already exported via app.generate_test_command takes precedence.
profile_dir="${TEST_PROFILE_DIR:-$SCRIPT_DIR/profiles}"
source "$profile_dir/${TEST_PROFILE:-gtest}.sh"
cd "$TEST_PATH"

log_dir="$TEST_PATH/logs"

# Cross builds go through the build runner (it applies wine/qemu/node and its
# env); native builds wrap in the debugger directly — gdb must attach to the
# binary, not to a wrapper script.
if [ -n "$TEST_RUNNER" ]; then
    TEST_WRAPPER="$BUILD_PATH/runner.sh"
else
    TEST_WRAPPER="env $DEBUGGER $DEBUGGER_ARGS"
fi

module_list="$2"
if [ -z "${module_list// }" ] || [ "${module_list// }" = "all" ]; then
    # Only files carrying the test suffix are test modules: a web build drops
    # the .wasm side product in the same dir, and stripping suffixes from a
    # raw ls would turn it into a bogus module name.
    if [ -n "$TEST_BIN_EXT" ]; then
        module_list=$(cd "$TEST_BIN_PATH" && ls | grep -E "\\${TEST_BIN_EXT}\$")
    else
        module_list=$(cd "$TEST_BIN_PATH" && ls)
    fi
    module_list="${module_list//${APP_NAME}_/}"
    if [ -n "$TEST_BIN_EXT" ]; then
        module_list="${module_list//${TEST_BIN_EXT}/}"
    fi
fi
test_filter="$3"

print_module_failure()
(
    local module="$1"
    local output_log="${log_dir}/${module}/output.log"
    local exit_code
    exit_code="$(cat "${log_dir}/${module}/exit_code" 2>/dev/null)"
    if [ -n "$timeout_wrapper" ] && { [ "$exit_code" = "124" ] || [ "$exit_code" = "137" ]; }; then
        echo ""
        echo "--- ${module} timed out after ${test_timeout}s ---"
    fi
    [ -s "${output_log}" ] || return 0

    echo ""
    echo "--- ${module} ---"
    echo "output log: ${output_log}"
    echo "------------------"
    # show each [ FAILED ] line with the assertion context above it (colors kept);
    # markers/assertions are in the combined log since 2>&1. fall back to tail if
    # no failed marker (crash/sanitizer before any gtest output)
    local failure_pattern="${TEST_FAILURE_PATTERN}|${SANITIZER_FAILURE_PATTERN}"
    if grep -qaE "$failure_pattern" "${output_log}"; then
        grep -aE -B 12 -A 1 "$failure_pattern" "${output_log}"
    else
        tail -n 40 "${output_log}"
    fi
    echo ""
)

module_failed()
(
    local module="$1"
    local exit_log="${log_dir}/${module}/exit_code"
    local output_log="${log_dir}/${module}/output.log"

    if [ -f "${exit_log}" ] && [ "$(cat "${exit_log}")" != "0" ]; then
        return 0
    fi
    if [ -f "${output_log}" ] && grep -qaE "$SANITIZER_FAILURE_PATTERN" "${output_log}" 2>/dev/null; then
        return 0
    fi
    if [ -n "${TEST_LOG_FAILURE_PATTERN:-}" ] && [ -f "${output_log}" ] \
        && grep -qaE "$TEST_LOG_FAILURE_PATTERN" "${output_log}" 2>/dev/null; then
        return 0
    fi
    return 1
)

print_failures()
(
    local any_failure=0

    for module in $module_list;
    do
        if module_failed "${module}"; then
            any_failure=1
            break
        fi
    done

    if [ "${any_failure}" -eq 1 ]; then
        echo ""
        echo "==================== TEST FAILURES ===================="
        for module in $module_list;
        do
            if module_failed "${module}"; then
                print_module_failure "${module}"
            fi
        done
        echo "======================================================="
        return 1
    fi
)

# summary.json + merged report.xml + console recap (written even on failure)
write_summary()
{
    local failed_modules=""
    for module in $module_list;
    do
        if module_failed "${module}"; then
            failed_modules="${failed_modules} ${module}"
        fi
    done
    # the test env's PYTHONHOME serves the bindings' embedded interpreter; the
    # host python must resolve its own stdlib
    env -u PYTHONHOME FAILED_MODULES="${failed_modules}" \
        TEST_TIMEOUT_SECONDS="$([ -n "$timeout_wrapper" ] && echo "$test_timeout")" \
        "${PYTHON_BIN:-python3}" "$SCRIPT_DIR/summary.py" \
        "$TEST_PATH" "$APP_NAME" $module_list
}

# Concurrent shards per test binary (jtest=N); the env is not forwarded to
# emulated/remote targets, an attached debugger is interactive.
shards=1
if [ "${JTEST:-0}" -gt 1 ] 2>/dev/null; then
    if [ -z "${TEST_SHARD_ENV:-}" ]; then
        echo "warning: test profile defines no TEST_SHARD_ENV - jtest ignored" >&2
    elif [ "${DEBUGGER:-}" = "gdb" ] || [ "${SBT_PLATFORM:-}" = "web" ] || [ "${SBT_PLATFORM:-}" = "android" ]; then
        echo "warning: jtest ignored under gdb, web and android" >&2
    else
        shards=$JTEST
    fi
fi

# per test binary (per shard with jtest): test_timeout= wins, else non-interactive
# runs take app.test_timeout or 5 minutes; 0 disables it. -k kills what ignores
# SIGTERM. Non-interactive runs kill the whole process group: a child left alive
# keeps the log pipe open. Interactive ones keep the tty (--foreground), child included.
test_timeout="${TEST_TIMEOUT:-}"
if [ -z "$test_timeout" ] && [ -n "${TEST_NONINTERACTIVE:-}" ]; then
    test_timeout="${TEST_APP_TIMEOUT:-300}"
fi
timeout_wrapper=
if [ -n "$test_timeout" ] && [ "$test_timeout" != "0" ] && [ "${DEBUGGER:-}" != "gdb" ]; then
    if [ -n "${TEST_NONINTERACTIVE:-}" ]; then
        timeout_wrapper="timeout -k 10 $test_timeout"
    else
        timeout_wrapper="timeout --foreground -k 10 $test_timeout"
    fi
fi

perf_wrapper=
perf_dir="$REPORT_DIR/perf"

# perftest: profile natively only, a runner would profile the emulator itself
setup_perf()
{
    [ -n "${TEST_PERF:-}" ] || return 0
    if [ -n "$TEST_RUNNER" ] || [ "${SBT_PLATFORM:-}" = "web" ] || [ "${SBT_PLATFORM:-}" = "android" ]; then
        echo "warning: perf profile ignored under a test runner, web and android - timing only" >&2
        return 0
    fi
    if ! command -v perf >/dev/null 2>&1; then
        echo "error: perf not found, install it to use perftest" >&2
        return 1
    fi
    rm -rf "$perf_dir"
    mkdir -p "$perf_dir"
    perf_wrapper="perf record -q -F 499 --user-callchains --call-graph dwarf"
}

perf_report()
{
    local data
    for data in "$perf_dir/$1".data "$perf_dir/$1".[0-9]*.data; do
        [ -f "$data" ] || continue
        perf report --stdio --no-children --percent-limit 1 -i "$data" > "${data%.data}.perf.txt" 2>/dev/null \
            || echo "warning: perf report failed for $data" >&2
    done
}

# $1 module, $2 module path, $3 command, $4 report flags embedded in the command
run_sharded()
{
    local module="$1" module_path="$2" cmd="$3" report_args="$4"
    local shard_dir="${log_dir}/${module}/shards"
    local shard_cmd shard_env shard_report code
    local rc=0 i

    rm -rf "$shard_dir" "${REPORT_DIR}/shards/${module}"
    mkdir -p "$shard_dir"
    for ((i = 0; i < shards; i++)); do
        shard_env="${TEST_SHARD_ENV//"@TOTAL@"/$shards}"
        shard_env="${shard_env//"@INDEX@"/$i}"
        shard_cmd="$cmd"
        if [ -n "$report_args" ]; then
            shard_report="${report_args//"$REPORT_DIR/"/"$REPORT_DIR/shards/$module/$i/"}"
            shard_cmd="${cmd/"$report_args"/"$shard_report"}"
        fi
        shard_cmd="${shard_cmd//"@SHARD@"/.$i}"
        (cd $module_path && env $shard_env $shard_cmd; echo $? > "${shard_dir}/${i}.exit") > "${shard_dir}/${i}.log" 2>&1 &
    done
    wait

    : > "${log_dir}/${module}/output.log"
    for ((i = 0; i < shards; i++)); do
        printf '# shard %s/%s\n' "$((i + 1))" "$shards" >> "${log_dir}/${module}/output.log"
        cat "${shard_dir}/${i}.log" >> "${log_dir}/${module}/output.log"
        code="$(cat "${shard_dir}/${i}.exit" 2>/dev/null || echo 1)"
        # a crash/timeout code outranks a plain test failure (1)
        if [ "$rc" = "0" ] || { [ "$rc" = "1" ] && [ "$code" != "0" ]; }; then
            rc="$code"
        fi
    done
    echo "$rc" > "${log_dir}/${module}/exit_code"
    rm -rf "$shard_dir"
}

execute_tests()
(
    rm -rf "$REPORT_DIR/shards"
    rm -f "$REPORT_DIR"/*.xml "$REPORT_DIR"/*.json "$TEST_PATH/report.xml" "$TEST_PATH/summary.json"
    for module in $module_list;
    do
        module_path=${MODULES_PATH:-$PROJECT_ROOT_PATH}/$module
        test_bin_path=$TEST_BIN_PATH/${APP_NAME}_${module}${TEST_BIN_EXT}

        repeat_args=
        if [ ! -z "$REPEAT" ]; then
            repeat_args="${TEST_REPEAT_FLAGS//REPEAT/$REPEAT}"
        fi

        brief_args=
        case "$BRIEF" in
            ""|0|[Ff][Aa][Ll][Ss][Ee]) ;;
            *) brief_args="$TEST_BRIEF_FLAGS" ;;
        esac

        report_args=
        if [ ! -z "${TEST_REPORT_FLAGS:-}" ]; then
            report_args="${TEST_REPORT_FLAGS//"@MODULE@"/$module}"
        fi

        wrapper="$TEST_WRAPPER"
        if [ -n "$perf_wrapper" ]; then
            # one data file per shard: perf cannot merge them
            # perf blocks SIGWINCH and ignores SIGUSR2 in its workload: restore the defaults
            wrapper="$perf_wrapper -o $perf_dir/$module$([ "$shards" -gt 1 ] && echo @SHARD@).data -- env --default-signal"
        fi
        if [ -n "$timeout_wrapper" ]; then
            wrapper="$timeout_wrapper $wrapper"
        fi

        cmd="$wrapper $test_bin_path \
                $TEST_RUN_FLAGS \
                $report_args \
                ${TEST_FILTER_FLAG//FILTER/$test_filter} \
                $repeat_args $brief_args $TEST_ARGS"

        output_log="${log_dir}/${module}/output.log"
        exit_log="${log_dir}/${module}/exit_code"

        echo ""
        echo "###################################################################################"
        echo "# testing module: $module"
        echo "# test command: $(echo "$cmd" | tr -s ' ')"
        if [ "$shards" -gt 1 ]; then
            echo "# shards: $shards"
        fi
        echo "###################################################################################"
        echo ""

        mkdir -p "${log_dir}/${module}"
        if [ "$shards" -gt 1 ]; then
            run_sharded "$module" "$module_path" "$cmd" "$report_args"
            if [ -z "$brief_args" ]; then
                cat "$output_log"
            fi
        elif [ -n "$brief_args" ]; then
            # brief: write everything to the log only, no live console output;
            # failures are printed at the end by print_failures
            (cd $module_path && $cmd; echo $? > "${exit_log}") > "${output_log}" 2>&1
        else
            # merge stdout (gtest markers/assertions) and stderr (myapp debug logs)
            # into one ordered log so failure context stays correlated
            (cd $module_path && $cmd; echo $? > "${exit_log}") 2>&1 | tee "${output_log}"
        fi

        if [ -n "$perf_wrapper" ]; then
            perf_report "$module"
        fi
    done

    print_failures
    local rc=$?
    write_summary
    return $rc
)

list_tests()
(
    modules=( $module_list )
    if [ ${#modules[@]} -eq 0 ]; then
        echo "no test binaries found in ${TEST_BIN_PATH}" >&2
        return 1
    fi
    modules_count=${#modules[@]}

    for module in $module_list;
    do
        if [ $modules_count -gt 1 ]; then
            echo ""
            echo "Module $module tests:"
            echo ""
        fi

        test_bin_path=$TEST_BIN_PATH/${APP_NAME}_${module}${TEST_BIN_EXT}

        $TEST_WRAPPER $test_bin_path $TEST_LIST_FLAGS
    done
)

case $1 in
    test)
        setup_perf || exit 1
        execute_tests
        ;;
    list)
        list_tests
        ;;
    *)
        false
        ;;
esac
