#!/usr/bin/env bash
# Generates <build>/test/.env (paths + cross-test runner vars + app test env)
# from SBT_ENV_JSON and installs executor.sh as <build>/test/execute_tests.sh.
# Required env: SBT_ENV_JSON.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

test_path="$(jq -r '"\(.build_path)/\(.paths.test)"' "$SBT_ENV_JSON")"
env_file="$test_path/.env"
mkdir -p "$test_path"

# Whole .env in one pass: fixed paths, then runner env, then app test env.
# Add a var = add one `ex(...)` line; values shell-quoted via @sh.
jq -r '
    def ex($k; $v): "export \($k)=\($v | @sh)";
    .build_path as $b
    | [
        ex("APP_NAME";         .app_name),
        ex("PROJECT_ROOT_PATH";.root_path),
        ex("MODULES_PATH";     .modules_path),
        ex("BUILD_PATH";       $b),
        ex("LIB_PATH";         "\($b)/\(.paths.lib)"),
        ex("BIN_PATH";         "\($b)/\(.paths.bin)"),
        ex("ETC_PATH";         "\($b)/\(.paths.etc)"),
        ex("SHARE_PATH";       "\($b)/\(.paths.share)"),
        ex("EXTLIB_PATH";      "\($b)/\(.paths.extlib)"),
        ex("EXTLIB_LIB_PATH";  "\($b)/\(.paths.extlib_lib)"),
        ex("TEST_PATH";        "\($b)/\(.paths.test)"),
        ex("TEST_BIN_PATH";    "\($b)/\(.paths.test_bin)"),
        ex("TEST_RUNNER";      .test.runner),
        ex("TEST_BIN_EXT";     .test.bin_ext)
      ]
    + [ (.test.runner_env // {} | to_entries[] | ex(.key; .value)) ]
    + [ (.test.env        // {} | to_entries[] | ex(.key; .value)) ]
    + [ (.test.command    // {} | to_entries[] | ex(.key; .value)) ]
    | .[]
    ' "$SBT_ENV_JSON" > "$env_file"

cp "$SCRIPT_DIR/executor.sh" "$test_path/execute_tests.sh"
chmod +x "$test_path/execute_tests.sh"
cp -r "$SCRIPT_DIR/profiles" "$test_path/profiles"

printf 'generated test env: %s\n' "$env_file"
printf 'generated test executor: %s\n' "$test_path/execute_tests.sh"
