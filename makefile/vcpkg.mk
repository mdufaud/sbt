##################
# Extlibs
##################

.PHONY: pkgdep # List dependencies for registered package manager

ifeq ($(MAKEARG_1), pkgdep)

ifeq ($(MAKEARG_2),)
PKG_MANAGER_NAME := auto
else

DEMO_MOD := $(demo)
TEST_MOD := $(test)

# make pkgdep mod MODULE
ifeq ($(MAKEARG_2), mod)
.PHONY: mod
PKG_MANAGER_NAME := auto
MODULES_NAME := $(MAKEARG_3),$(m)
else ifeq ($(MAKEARG_2), demo)
.PHONY: demo
PKG_MANAGER_NAME := auto
MODULES_NAME := $(MAKEARG_3),$(m)
DEMO_MOD := 1
else ifeq ($(MAKEARG_2), test)
.PHONY: test
PKG_MANAGER_NAME := auto
MODULES_NAME := $(MAKEARG_3),$(m)
TEST_MOD := 1
else
PKG_MANAGER_NAME := $(MAKEARG_2)
endif # pkgdep mod


endif # pkgdep

.PHONY: pkgdep
pkgdep: test = $(TEST_MOD)
pkgdep: demo = $(DEMO_MOD)
pkgdep: modules = $(MODULES_NAME)
pkgdep: pkgdep = $(PKG_MANAGER_NAME)
pkgdep: build

$(PKG_MANAGER_NAME):
	$(QUIET) echo > /dev/null

endif # pkgdep

##################
# Demo
##################

.PHONY: demo

ifeq ($(MAKEARG_1), demo)

MODULES_NAME := $(MAKEARG_2),$(m)
demo: modules = $(MODULES_NAME)
demo: demo = 1
demo: build

endif


##################
# VCPKG (extlibs)
##################

.PHONY: vcpkg_deploy

vcpkg_deploy:
	$(QUIET) if [ ! -d "$(VCPKG_PATH)" ]; then git clone https://github.com/microsoft/vcpkg $(VCPKG_PATH); fi
	$(QUIET) if [ ! -f "$(VCPKG_BIN)" ]; then $(VCPKG_PATH)/bootstrap-vcpkg.sh -disableMetrics; fi

############################
# SBT external dependencies
############################

SBT_DEPS_SCRIPT_PATH := $(SBT_PATH)/build/sbt_deps.py
SBT_DEPS_SCRIPT = $(PYTHON_BIN) $(SBT_DEPS_SCRIPT_PATH) fetch

.PHONY: sbt_dep # Fetch and build SBT project dependencies

sbt_dep: vcpkg_deploy
	$(eval BUILD_CMD_LINE = \
			modules=$(modules) \
			test=$(test) \
			dist=$(dist) \
			mode=$(mode) \
			asan=$(asan) \
			ubsan=$(ubsan) \
			tsan=$(tsan) \
			lsan=$(lsan) \
			msan=$(msan) \
			hwasan=$(hwasan) \
			coverage=$(coverage) \
			verbose=$(verbose) \
			demo=$(demo) \
			libc=$(libc) \
			cpu=$(cpu) \
	)
	$(QUIET) $(SBT_DEPS_SCRIPT) $(BUILD_CMD_LINE)

##################
# Dependencies
##################

.PHONY: dep # Run vcpkg to get dependencies

dep: sbt_dep
	$(eval BUILD_CMD_LINE = \
			modules=$(modules)$(m) \
			test=$(test) \
			dist=$(dist) \
			mode=$(mode) \
			asan=$(asan) \
			ubsan=$(ubsan) \
			tsan=$(tsan) \
			lsan=$(lsan) \
			msan=$(msan) \
			hwasan=$(hwasan) \
			coverage=$(coverage) \
			verbose=$(verbose) \
			pkgdep=$(pkgdep) \
			demo=$(demo) \
			libc=$(libc) \
			cpu=$(cpu) \
			with-system-packages=$(with-system-packages) \
	)
	$(QUIET) $(VCPKG_SCRIPT) $(BUILD_CMD_LINE)

ifeq ($(MAKEARG_1), dep)

ifeq ($(MAKEARG_2), mod)
VCPKG_ACTION := fetch
MODULES_NAME := $(MAKEARG_3),$(m)
dep: modules = $(MODULES_NAME)
mod:
	$(QUIET) echo > /dev/null
endif

ifeq ($(MAKEARG_2), demo)
VCPKG_ACTION := fetch
MODULES_NAME := $(MAKEARG_3),$(m)
dep: demo = 1
dep: modules = $(MODULES_NAME)
demo:
	$(QUIET) echo > /dev/null
endif

ifeq ($(MAKEARG_2), test)
VCPKG_ACTION := fetch
MODULES_NAME := $(MAKEARG_3),$(m)
dep: test = 1
dep: modules = $(MODULES_NAME)
test:
	$(QUIET) echo > /dev/null
endif

ifeq ($(MAKEARG_2), list)
VCPKG_ACTION := list
list: dep
	$(QUIET) echo > /dev/null
endif

ifeq ($(MAKEARG_2), tree)
VCPKG_ACTION := tree
tree: dep
	$(QUIET) echo > /dev/null
endif

ifeq ($(MAKEARG_2), licenses)
VCPKG_ACTION := licenses
licenses: dep
	$(QUIET) echo > /dev/null
endif

ifeq ($(MAKEARG_2), install)
VCPKG_ACTION :=
install: vcpkg_deploy
	$(VCPKG_BIN) install $(MAKEARG_3)
endif

ifeq ($(MAKEARG_2), search)
VCPKG_ACTION :=
search: vcpkg_deploy
	$(VCPKG_BIN) search $(MAKEARG_3) --x-full-desc
endif

ifeq ($(MAKEARG_2), update)
VCPKG_ACTION :=
update: vcpkg_deploy
	cd $(VCPKG_PATH) && git pull && $(VCPKG_BIN) update
endif


endif # dep
