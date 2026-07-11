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

# Sub-commands owning a real rule - never stubbed here
MAKEARG_KEYWORDS :=
ifeq ($(MAKEARG_1), dep)
MAKEARG_KEYWORDS := mod demo test list tree licenses install search update
else ifeq ($(MAKEARG_1), pkgdep)
MAKEARG_KEYWORDS := mod demo test
else ifeq ($(MAKEARG_1), dist)
MAKEARG_KEYWORDS := mod
else ifneq ($(findstring test,$(MAKEARG_1)), )
MAKEARG_KEYWORDS := ls
endif

ifneq ($(filter $(MAKEARG_1),$(MAKEARG_COMMANDS))$(findstring test,$(MAKEARG_1)), )

MAKEARG_STUBS := $(filter-out $(MAKEARG_KEYWORDS),$(MAKEARG_REST))

ifneq ($(MAKEARG_STUBS), )
.PHONY: $(MAKEARG_STUBS)
$(MAKEARG_STUBS):
	@:
endif

endif
