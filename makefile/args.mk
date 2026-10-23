##################
# Positional args
##################

MAKEARG_1 := $(word 1, $(MAKECMDGOALS))
MAKEARG_2 := $(word 2, $(MAKECMDGOALS))
MAKEARG_3 := $(word 3, $(MAKECMDGOALS))
MAKEARG_4 := $(word 4, $(MAKECMDGOALS))

MAKEARG_REST := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))

# Commands reading the following goals as positional arguments instead of targets
MAKEARG_COMMANDS := mod dep pkgdep demo dist cppcheck \
					newmod newtest newclass newinterface \
					sbtnewfs sbtnewgit adb android-emu-run

# Every goal handled by the test branch — the single declaration of that list:
# args.mk routes the goal with it (exact match; a goal merely *containing*
# "test", e.g. `make latest`, must not enter it) and makefile/test.mk derives
# its .PHONY from it. A new test goal is added here and nowhere else.
TEST_GOALS := test itest nointeract_test gdbtest gdb_test bench \
	asantest asan_test iasantest nointeract_asan_test \
	ubsantest ubsan_test iubsantest nointeract_ubsan_test \
	tsantest tsan_test itsantest nointeract_tsan_test \
	lsantest lsan_test ilsantest nointeract_lsan_test \
	msantest msan_test imsantest nointeract_msan_test \
	hwasantest hwasan_test ihwasantest nointeract_hwasan_test \
	covtest coverage_test \
	valtest valgrind_test ivaltest nointeract_valgrind_test \
	lvaltest valgrind_leak_test ilvaltest nointeract_valgrind_leak_test \
	ttest strace_test ittest nointeract_strace_test \
	ivtest iltest \
	perftest perf_test iperftest nointeract_perf_test
MAKEARG_TEST_GOAL := $(filter $(TEST_GOALS),$(MAKEARG_1))

# Sub-commands owning a real rule - never stubbed here
MAKEARG_KEYWORDS :=
ifeq ($(MAKEARG_1), dep)
MAKEARG_KEYWORDS := mod demo test bench list tree licenses sbom install search update
else ifeq ($(MAKEARG_1), pkgdep)
MAKEARG_KEYWORDS := mod demo test
else ifeq ($(MAKEARG_1), dist)
MAKEARG_KEYWORDS := mod
else ifneq ($(MAKEARG_TEST_GOAL), )
MAKEARG_KEYWORDS := ls
endif

ifneq ($(filter $(MAKEARG_1),$(MAKEARG_COMMANDS))$(MAKEARG_TEST_GOAL), )

MAKEARG_STUBS := $(filter-out $(MAKEARG_KEYWORDS),$(MAKEARG_REST))

ifneq ($(MAKEARG_STUBS), )
.PHONY: $(MAKEARG_STUBS)
$(MAKEARG_STUBS):
	@:
endif

endif
