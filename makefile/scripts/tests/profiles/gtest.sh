#!/bin/bash
# Engine default test profile: GoogleTest.
# Sourced by execute_tests.sh AFTER .env, so any variable already set by .env
# (a project override emitted from app.generate_test_command) wins; otherwise
# these gtest defaults fill in. Placeholders FILTER / REPEAT are substituted by
# the executor at call time.
: "${TEST_RUN_FLAGS:=--gtest_death_test_style=threadsafe --gtest_shuffle --gtest_color=yes}"
: "${TEST_LIST_FLAGS:=--gtest_list_tests}"
: "${TEST_FILTER_FLAG:=--gtest_filter=*FILTER*}"
: "${TEST_REPEAT_FLAGS:=--gtest_repeat=REPEAT --gtest_throw_on_failure}"
: "${TEST_BRIEF_FLAGS:=--gtest_brief=1}"
: "${TEST_SHARD_ENV:=GTEST_TOTAL_SHARDS=@TOTAL@ GTEST_SHARD_INDEX=@INDEX@}"
# no default for TEST_REPORT_FLAGS here: the executor owns it (unset-only, empty = off)
: "${TEST_FAILURE_PATTERN:=\[  FAILED  \]}"
# python regexes naming the test a crash or a timeout cut short (group 1); brief runs print no start lines
: "${TEST_START_PATTERN:=^\[ RUN      \] (\S+)}"
: "${TEST_END_PATTERN:=^\[ +(?:OK|FAILED|SKIPPED) +\] (\S+)}"
: "${TEST_INTERRUPT_PATTERN:=}"
export TEST_START_PATTERN TEST_END_PATTERN TEST_INTERRUPT_PATTERN
