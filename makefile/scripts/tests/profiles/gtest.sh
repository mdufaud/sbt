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
: "${TEST_FAILURE_PATTERN:=\[  FAILED  \]}"
