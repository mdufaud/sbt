MAKEFILE_TOOLS_TEMPLATES := $(MAKEFILE_TOOLS)/templates
MAKEFILE_TOOLS_SCRIPTS := $(MAKEFILE_TOOLS)/scripts

export MAKEFILE_TOOLS_TEMPLATES
export MAKEFILE_TOOLS_SCRIPTS

.PHONY: newmod # Generate a new module (<module_name>)

ifeq ($(MAKEARG_1), newmod)
MODULE_NAME := $(MAKEARG_2)$(m)

newmod:
	@bash $(MAKEFILE_TOOLS_SCRIPTS)/make_module.sh $(APP_NAME) $(MODULE_NAME)

# for no 'no rules to make...'
$(MODULE_NAME):
	$(QUIET) echo > /dev/null

endif

.PHONY: newtest # Generate a new c++ google test for module (<module_name> <test_name>)

ifeq ($(MAKEARG_1), newtest)
MODULE_NAME := $(MAKEARG_2)$(m)
TEST_NAME := $(MAKEARG_3)$(t)

newtest:
	@bash $(MAKEFILE_TOOLS_SCRIPTS)/make_test.sh $(APP_NAME) $(MODULE_NAME) $(TEST_NAME)

endif

.PHONY: newclass # Generate a new c++ class for module (<module_name> <class_name>)

ifeq ($(MAKEARG_1), newclass)
MODULE_NAME := $(MAKEARG_2)$(m)
CLASS_NAME := $(MAKEARG_3)$(c)

newclass:
	@bash $(MAKEFILE_TOOLS_SCRIPTS)/make_class.sh $(APP_NAME) $(MODULE_NAME) $(CLASS_NAME)

# for no 'no rules to make...'
$(MODULE_NAME):
	$(QUIET) echo > /dev/null

# for no 'no rules to make...'
$(CLASS_NAME):
	$(QUIET) echo > /dev/null

endif

.PHONY: newinterface # Generate a new c++ interface for module (<module_name> <class_name>)

ifeq ($(MAKEARG_1), newinterface)
MODULE_NAME := $(MAKEARG_2)$(m)
CLASS_NAME := $(MAKEARG_3)$(c)

newinterface:
	@bash $(MAKEFILE_TOOLS_SCRIPTS)/make_interface_file.sh $(APP_NAME) $(MODULE_NAME) $(CLASS_NAME)

# for no 'no rules to make...'
$(MODULE_NAME):
	$(QUIET) echo > /dev/null

# for no 'no rules to make...'
$(CLASS_NAME):
	$(QUIET) echo > /dev/null

endif
