#!/bin/bash
# Google Benchmark profile, forced by make bench (TEST_BENCH). Assigned, not
# defaulted: .env overrides from app.generate_test_command target the test
# framework. Placeholders FILTER / REPEAT / @MODULE@ are substituted by the
# executor at call time.
TEST_RUN_FLAGS="--benchmark_counters_tabular=true"
TEST_LIST_FLAGS="--benchmark_list_tests=true"
TEST_FILTER_FLAG="--benchmark_filter=FILTER"
TEST_REPEAT_FLAGS="--benchmark_repetitions=REPEAT"
TEST_BRIEF_FLAGS=
TEST_SHARD_ENV=
TEST_REPORT_FLAGS="--benchmark_out=$REPORT_DIR/${APP_NAME}_@MODULE@.json --benchmark_out_format=json"
# SkipWithError still exits 0: the log line fails the module
TEST_FAILURE_PATTERN="ERROR OCCURRED:"
TEST_LOG_FAILURE_PATTERN="$TEST_FAILURE_PATTERN"
# results print once a benchmark ends: no start line names a crashed one
TEST_START_PATTERN=
TEST_END_PATTERN=
export TEST_START_PATTERN TEST_END_PATTERN
