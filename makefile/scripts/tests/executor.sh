#!/bin/bash
# Static test executor. Copied verbatim into <build>/test/execute_tests.sh by
# generate.sh, which writes the sibling .env (paths + platform facts + app test
# env). Sourced config: APP_NAME TEST_PATH TEST_BIN_PATH PROJECT_ROOT_PATH
# TEST_RUNNER TEST_BIN_EXT and the SBT_* platform facts. Cross builds launch
# test binaries through the build's runner.sh (wine/qemu/node + its env);
# native ones may wrap in a debugger directly.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.env"
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

# summary.json: module -> exit code + report/log paths (written even on failure)
write_summary()
{
    # the test env's PYTHONHOME serves the bindings' embedded interpreter; the
    # host python must resolve its own stdlib
    env -u PYTHONHOME "${PYTHON_BIN:-python3}" "$SCRIPT_DIR/summary.py" \
        "$TEST_PATH" "$APP_NAME" $module_list > "${TEST_PATH}/summary.json"
}

execute_tests()
(
    for module in $module_list;
    do
        module_path=${MODULES_PATH:-$PROJECT_ROOT_PATH}/$module
        test_bin_path=$TEST_BIN_PATH/${APP_NAME}_${module}${TEST_BIN_EXT}

        repeat_args=
        if [ ! -z "$REPEAT" ]; then
            repeat_args="${TEST_REPEAT_FLAGS//REPEAT/$REPEAT}"
        fi

        brief_args=
        if [ ! -z "$BRIEF" ] && [ "$BRIEF" != "0" ]; then
            brief_args="$TEST_BRIEF_FLAGS"
        fi

        report_args=
        if [ ! -z "${TEST_REPORT_FLAGS:-}" ]; then
            report_args="$TEST_REPORT_FLAGS"
        fi

        cmd="$TEST_WRAPPER $test_bin_path \
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
        echo "###################################################################################"
        echo ""

        mkdir -p "${log_dir}/${module}"
        if [ -n "$brief_args" ]; then
            # brief: write everything to the log only, no live console output;
            # failures are printed at the end by print_failures
            (cd $module_path && $cmd; echo $? > "${exit_log}") > "${output_log}" 2>&1
        else
            # merge stdout (gtest markers/assertions) and stderr (myapp debug logs)
            # into one ordered log so failure context stays correlated
            (cd $module_path && $cmd; echo $? > "${exit_log}") 2>&1 | tee "${output_log}"
        fi
    done

    write_summary
    print_failures
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
        execute_tests
        ;;
    list)
        list_tests
        ;;
    *)
        false
        ;;
esac
