##################
# Cppcheck
##################

.PHONY: cppcheck # Run cppcheck static analysis ([m=modules])

ifeq ($(MAKEARG_1), cppcheck)

# Allow `make cppcheck mod` and `make cppcheck mod mod` in addition to `make cppcheck m=mod`
ifeq ($(MAKEARG_2), mod)
CPPCHECK_MODULES_ARG := $(MAKEARG_3),$(m)
else
CPPCHECK_MODULES_ARG := $(MAKEARG_2),$(m)
endif

cppcheck:
	$(QUIET) command -v cppcheck >/dev/null 2>&1 || { $(call echo_log_error,makefile,cppcheck not found - install with your package manager); exit 1; }
	$(QUIET) $(call echo_log_info,makefile,running cppcheck - reports in $(BUILD_PATH)/cppcheck/)
	$(QUIET) $(PYTHON_BIN) $(SBT_PATH)/scripts/run_cppcheck.py \
		"$(BUILD_PATH)" "$(PROJECT_ROOT_PATH)" \
		$(shell printf '%s' "$(CPPCHECK_MODULES_ARG)" | tr ',' ' ')

# Prevent 'no rule to make target' for module name args
ifneq ($(MAKEARG_2),)
$(MAKEARG_2):
	$(QUIET) echo > /dev/null
endif
ifneq ($(MAKEARG_3),)
$(MAKEARG_3):
	$(QUIET) echo > /dev/null
endif

endif # cppcheck
