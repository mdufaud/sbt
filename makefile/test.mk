########
# Test
########

# Every goal handled here is declared ONCE in args.mk (TEST_GOALS) — the same
# list drives the args.mk stub branch and this .PHONY. Goal reference:
#   test                     build modules, tests and run tests ([modules|all|ls] [filter] [repeat=x])
#   itest nointeract_test    same with stdin closed (non-interactive)
#   gdbtest gdb_test         run tests under gdb
#   asantest asan_test iasantest nointeract_san_test          address sanitizer
#   ubsantest ubsan_test iubsantest nointeract_ubsan_test    undefined behavior sanitizer
#   tsantest tsan_test itsantest nointeract_tsan_test         thread sanitizer
#   lsantest lsan_test ilsantest nointeract_lsan_test         leak sanitizer
#   msantest msan_test imsantest nointeract_msan_test         memory sanitizer (clang only)
#   hwasantest hwasan_test ihwasantest nointeract_hwasan_test hwaddress sanitizer (arm64 only)
#   covtest coverage_test    coverage instrumentation, emits coverage.xml (cobertura)
#   valtest valgrind_test ivaltest nointeract_valgrind_test   valgrind
#   lvaltest valgrind_leak_test ilvaltest nointeract_valgrind_leak_test   valgrind leak check
#   ttest strace_test ittest nointeract_strace_test           strace
#   ivtest iltest             non-interactive valgrind / valgrind leak check
.PHONY: $(TEST_GOALS)

# enter the test branch only for goals in the exact TEST_GOALS list (args.mk)
ifneq ($(MAKEARG_TEST_GOAL), )

# --gtest_color=(yes|no|auto) (Enable/disable colored output. The default is auto)
# --gtest_brief=1 (Only print test failures.)
# --gtest_recreate_environments_when_repeating
# --gtest_list_tests
# --gtest_also_run_disabled_tests
# --gtest_output=(json|xml)[:DIRECTORY_PATH/|:FILE_PATH]
# --gtest_stream_result_to=HOST:PORT
# --gtest_catch_exceptions=0
# --gtest_break_on_failure
TEST_ARGS :=
TEST_ACTION := test
TEST_SCRIPT_ARGS :=
DEBUGGER :=
DEBUGGER_ARGS :=

# handles:
#	make test
#	make test MODULE FILTER
#	make test MODULE ls
#	make test ls
#	make test t=FILTER
MODULES_NAME := $(MAKEARG_2),$(m)
TEST_NAME_FILTER := $(MAKEARG_3)$(t)

ifeq ($(MODULES_NAME),all)
	MODULES_NAME :=
endif

# case: make test ls
ifeq ($(MAKEARG_2),ls)
ifeq ($(TEST_NAME_FILTER), )
	TEST_ACTION := list
	MODULES_NAME :=
endif
endif

# case: make test MODULE ls
ifeq ($(MAKEARG_3),ls)
	TEST_ACTION := list
endif

ifeq ($(TEST_ACTION),list)
ls:
	$(QUIET) echo > /dev/null
endif

ifneq ($(MODULES_NAME), )
test: modules = $(MODULES_NAME)
endif

COMMA := ,
MODULES_NAME_SPLIT := $(subst $(COMMA), ,$(MODULES_NAME))

# JSON build description consumed by generate.sh; written by the recipe below
# (not at make parse time) so a plain `make` never touches the filesystem.
SBT_ENV_JSON_PATH := $(BUILD_PATH)/sbt_env.json

test: test = 1
test: build
	$(call mk_log_info,makefile,starting tests in build: $(TEST_PATH))
	$(if $(TEST_RUNNER),$(call mk_log_warning,makefile,test runner '$(TEST_RUNNER)' active - DEBUGGER and sanitizer options disabled (unsupported under emulation)))
	$(QUIET) $(PYTHON_BIN) $(SBT_CLI) dump >/dev/null
	$(QUIET) env SBT_ENV_JSON="$(SBT_ENV_JSON_PATH)" \
					bash $(MAKEFILE_TOOLS)/scripts/tests/generate.sh
	$(QUIET) env DEBUGGER="$(if $(TEST_RUNNER),,$(DEBUGGER))" \
					DEBUGGER_ARGS="$(if $(TEST_RUNNER),,$(DEBUGGER_ARGS))" \
					TEST_ARGS="$(TEST_ARGS)" \
					REPEAT="$(repeat)" \
					BRIEF="$(brief)" \
					ASAN_OPTIONS="$(if $(TEST_RUNNER),,$(ASAN_OPTIONS))" \
					UBSAN_OPTIONS="$(if $(TEST_RUNNER),,$(UBSAN_OPTIONS))" \
					TSAN_OPTIONS="$(if $(TEST_RUNNER),,$(TSAN_OPTIONS))" \
					LSAN_OPTIONS="$(if $(TEST_RUNNER),,$(LSAN_OPTIONS))" \
					MSAN_OPTIONS="$(if $(TEST_RUNNER),,$(MSAN_OPTIONS))" \
					bash $(TEST_PATH)/execute_tests.sh "$(TEST_ACTION)" "$(MODULES_NAME_SPLIT)" "$(TEST_NAME_FILTER)" $(TEST_SCRIPT_ARGS)

nointeract_test: TEST_SCRIPT_ARGS += 0>&-
nointeract_test: test
itest: nointeract_test

valgrind_test: DEBUGGER_ARGS = --trace-children=no --track-origins=no --show-leak-kinds=definite
valgrind_test: DEBUGGER = valgrind
valgrind_test: test
valtest: valgrind_test

valgrind_leak_test: DEBUGGER_ARGS = --leak-check=full --show-leak-kinds=all --trace-children=no --track-origins=yes
valgrind_leak_test: DEBUGGER = valgrind
valgrind_leak_test: test
lvaltest: valgrind_leak_test

gdb_test: DEBUGGER_ARGS = --args
gdb_test: DEBUGGER = gdb
gdb_test: test
gdbtest: gdb_test

asan_test: ASAN_OPTIONS="detect_leaks=1:halt_on_error=0:strict_init_order=1:detect_odr_violation=1:detect_stack_use_after_return=1:detect_container_overflow=1:alloc_dealloc_mismatch=1:detect_invalid_pointer_pairs=2:verbosity=0:atexit=1:check_initialization_order=1"
asan_test: asan = 1
asan_test: test
asantest: asan_test

ubsan_test: UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=0:report_error_type=1"
ubsan_test: ubsan = 1
ubsan_test: test
ubsantest: ubsan_test

tsan_test: TSAN_OPTIONS="halt_on_error=0:second_deadlock_stack=1:history_size=7"
tsan_test: tsan = 1
tsan_test: test
tsantest: tsan_test

lsan_test: LSAN_OPTIONS="report_objects=1"
lsan_test: lsan = 1
lsan_test: test
lsantest: lsan_test

msan_test: MSAN_OPTIONS="halt_on_error=0:print_stats=1"
msan_test: msan = 1
msan_test: test
msantest: msan_test

hwasan_test: hwasan = 1
hwasan_test: test
hwasantest: hwasan_test

# Coverage: build with --coverage instrumentation, run tests, then run gcovr.
# The recipe runs after the 'test' prerequisite has executed, so .gcda files exist.
coverage_test: coverage = 1
coverage_test: test
	$(QUIET) command -v gcovr >/dev/null 2>&1 || { $(call echo_log_error,makefile,gcovr not found - install with: pip install gcovr); exit 1; }
	$(QUIET) $(call echo_log_info,makefile,generating cobertura coverage report at $(BUILD_PATH)/coverage/)
	$(QUIET) bash $(MAKEFILE_TOOLS)/scripts/run_coverage.sh \
		"$(BUILD_PATH)" "$(PROJECT_ROOT_PATH)" $(MODULES_NAME_SPLIT)
covtest: coverage_test

strace_test: DEBUGGER = strace
strace_test: test
ttest: strace_test

define mk_nointeract_debug_test
.PHONY: nointeract_$(1) $(2)
nointeract_$(1): TEST_SCRIPT_ARGS += 0>&-
nointeract_$(1): $(1)
$(2): nointeract_$(1)
endef

$(eval $(call mk_nointeract_debug_test,valgrind_test,ivtest))
$(eval $(call mk_nointeract_debug_test,valgrind_leak_test,iltest))
$(eval $(call mk_nointeract_debug_test,strace_test,ittest))
$(eval $(call mk_nointeract_debug_test,asan_test,iasantest))
$(eval $(call mk_nointeract_debug_test,ubsan_test,iubsantest))
$(eval $(call mk_nointeract_debug_test,tsan_test,itsantest))
$(eval $(call mk_nointeract_debug_test,lsan_test,ilsantest))
$(eval $(call mk_nointeract_debug_test,msan_test,imsantest))
$(eval $(call mk_nointeract_debug_test,hwasan_test,ihwasantest))

endif # test
