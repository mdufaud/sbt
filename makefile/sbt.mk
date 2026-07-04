find_exec = $(shell if command -v which >/dev/null 2>&1; then which $(1) 2>/dev/null; elif command -v command >/dev/null 2>&1; then command -v $(1) 2>/dev/null; elif command -v type >/dev/null 2>&1; then type -P $(1) 2>/dev/null; fi)

PYTHON_BIN := python3
ifeq (, $(call find_exec,$(PYTHON_BIN)))
PYTHON_BIN := python
endif

PIP_BIN := pip3
ifeq (, $(call find_exec,$(PIP_BIN)))
PIP_BIN := pip
endif

ifeq (, $(call find_exec,$(PYTHON_BIN)))
$(error "Makefile: no python detected - it is needed to build the project.")
endif

ifeq (, $(call find_exec,jq))
$(error "Makefile: no jq detected - it is needed to read the build environment.")
endif

OS := $(shell uname)

ifeq ($(OS),Linux)
SHELL := /bin/bash
GREP := /bin/grep
else
SHELL := /bin/sh
GREP := /usr/bin/grep
endif

ifdef MAKE_DEBUG
SHELL += -x
endif

ifndef MAKE_VERBOSE
QUIET := @
endif

MAKEARG_1 := $(word 1, $(MAKECMDGOALS))
MAKEARG_2 := $(word 2, $(MAKECMDGOALS))
MAKEARG_3 := $(word 3, $(MAKECMDGOALS))
MAKEARG_4 := $(word 4, $(MAKECMDGOALS))

PROJECT_ROOT_PATH := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

##############
# Builder env
##############

BUILD_TOOLS := $(PROJECT_ROOT_PATH)/site_scons
SBT_PATH := $(BUILD_TOOLS)/sbt

SBT_CLI := $(SBT_PATH)/scripts/cli_helper.py

ifeq ($(zig),1)
override compiler := zig
export compiler
endif

SBT_ENV_PATH := $(shell machine=$(machine) mode=$(mode) platform=$(platform) compiler=$(compiler) libc=$(libc) static=$(static) $(PYTHON_BIN) $(SBT_CLI) dump)

jq_get = $(shell jq -r '.$(1)' $(SBT_ENV_PATH))
jq_path = $(BUILD_PATH)/$(call jq_get,paths.$(1))

PLATFORM := $(call jq_get,build.platform)
ifeq ($(PLATFORM),)
$(error "Makefile: platform not found - cannot find build path")
endif

MACHINE := $(call jq_get,build.machine)
ifeq ($(MACHINE),)
$(error "Makefile: machine not found - cannot find build path")
endif

COMPILE_MODE := $(call jq_get,build.mode)
ifeq ($(COMPILE_MODE),)
$(error "Makefile: compilation mode not found - cannot find build path")
endif

COMPILER := $(call jq_get,build.compiler)
GNU_TRIPLET := $(call jq_get,build.triplet)
BUILD_PATH := $(call jq_get,build_path)
APP_NAME := $(call jq_get,app_name)
MODULES_DIR := $(call jq_get,modules_path)

# Cross-test runner (qemu-user/wine) and test binary suffix; empty string means none
TEST_RUNNER := $(call jq_get,test.runner)
TEST_BIN_EXT := $(call jq_get,test.bin_ext)

##########
# Paths
##########

BUILD_ENTRY_PATH := $(PROJECT_ROOT_PATH)/build
EXTLIB_PATH := $(call jq_path,extlib)
EXTLIB_LIB_PATH := $(call jq_path,extlib_lib)
LIB_PATH := $(call jq_path,lib)
INCLUDE_PATH := $(call jq_path,include)
TEST_PATH := $(call jq_path,test)
TEST_BIN_PATH := $(call jq_path,test_bin)
BIN_PATH := $(call jq_path,bin)
OBJ_PATH := $(call jq_path,obj)
ETC_PATH := $(call jq_path,etc)
DEMO_PATH := $(call jq_path,demo)
SHARE_PATH := $(call jq_path,share)
DIST_PATH := $(BUILD_PATH)/dist

####################
# Makefile includes
####################

MAKEFILE_TOOLS := $(SBT_PATH)/makefile

include $(MAKEFILE_TOOLS)/logger.mk
include $(MAKEFILE_TOOLS)/utils.mk
include $(MAKEFILE_TOOLS)/templates.mk

BUILD_TOOLS_ADDON := $(BUILD_TOOLS)/addon
MAKEFILE_TOOLS_ADDON := $(BUILD_TOOLS_ADDON)/makefile

ifneq ($(wildcard $(MAKEFILE_TOOLS_ADDON)/addon.mk),)
include $(MAKEFILE_TOOLS_ADDON)/addon.mk
endif

############
# Venv
############

VENV_PATH := $(PROJECT_ROOT_PATH)/.venv

############
# Scons env
############

ifeq ($(j),)
	j := $$[ $(UTILS_LOGICAL_CORE_NUMBER) - 1 ]
endif
SCONS_BUILD_CMD = $(SCONS_PREFIX) scons -Q -j$(j) $(SCONS_ARGS)

############
# VCPKG
############

# VCPKG_ROOT env var allows sharing a vcpkg installation across SBT projects
ifdef VCPKG_ROOT
VCPKG_PATH := $(VCPKG_ROOT)
else
VCPKG_PATH := $(PROJECT_ROOT_PATH)/.vcpkg
endif
VCPKG_BIN := $(VCPKG_PATH)/vcpkg
VCPKG_SCRIPT_PATH := $(SBT_PATH)/vcpkg/install.py
VCPKG_ACTION := fetch

VCPKG_SCRIPT = $(PYTHON_BIN) $(VCPKG_SCRIPT_PATH) $(VCPKG_ACTION)

#########
# Exports
#########

export APP_NAME
export MODULES_DIR
export TEST_PATH
export BUILD_PATH
export LIB_PATH
export BIN_PATH
export ETC_PATH
export SHARE_PATH
export EXTLIB_PATH
export EXTLIB_LIB_PATH

##########
# Targets
##########

.PHONY: all help

all: build

help:
	$(call mk_log_info,makefile,list all targets: make targets)
	$(call mk_log_info,makefile,build modules: make)
	$(call mk_log_info,makefile,get dependencies: make dep)
	$(call mk_log_info,makefile,build and run tests: make test)
	$(call mk_log_info,makefile,build specific modules: modules=<comma_separated_modules>)
	$(call mk_log_info,makefile,build with address sanitizer: asan=1)
	$(call mk_log_info,makefile,build with undefined behavior sanitizer: ubsan=1)
	$(call mk_log_info,makefile,build with thread sanitizer: tsan=1)
	$(call mk_log_info,makefile,build with leak sanitizer: lsan=1)
	$(call mk_log_info,makefile,build with memory sanitizer (clang only): msan=1)
	$(call mk_log_info,makefile,build with hwaddress sanitizer (arm64 only): hwasan=1)
	$(call mk_log_info,makefile,build with code coverage instrumentation: coverage=1)
	$(call mk_log_info,makefile,run cppcheck static analysis: make cppcheck [m=modules])
	$(call mk_log_info,makefile,run tests with coverage and emit cobertura xml: make covtest [m=modules])
	$(call mk_log_info,makefile,build with static libs: static=1)
	$(call mk_log_info,makefile,build specific release: mode=debug|release)
	$(call mk_log_info,makefile,cross build for windows: platform=win)
	$(call mk_log_info,makefile,distribute app: dist=tar|apt|pacman)
	$(call mk_log_info,makefile,build with clang: compiler=clang)
	$(call mk_log_info,makefile,build with emscripten: compiler=em)
	$(call mk_log_info,makefile,target cpu: cpu=<value> e.g. cpu=x86-64-v3 cpu=cortex-a72)
	$(QUIET) echo > /dev/null

######################
# Build infos
######################

.PHONY: info # print build infos

info:
	$(call mk_log_info,makefile,project: $(APP_NAME))
	$(call mk_log_info,makefile,platform = $(PLATFORM))
	$(call mk_log_info,makefile,compiler = $(COMPILER))
	$(call mk_log_info,makefile,machine = $(MACHINE))
	$(call mk_log_info,makefile,gnu_triplet = $(GNU_TRIPLET))
	$(call mk_log_info,makefile,mode = $(COMPILE_MODE))
	$(call mk_log_info,makefile,logical cores = $(UTILS_LOGICAL_CORE_NUMBER) ($(j) used))
	$(call mk_log_info,makefile,build: $(BUILD_PATH))
	$(QUIET) echo > /dev/null

.PHONY: conf # print modules configurations selected for this build ([m=modules])

conf:
	$(QUIET) machine=$(machine) mode=$(mode) platform=$(platform) compiler=$(compiler) libc=$(libc) static=$(static) $(PYTHON_BIN) $(SBT_CLI) conf $(m)

######################
# List Makefile rules
######################

.PHONY: targets # Generate list of targets with descriptions

targets:
	$(QUIET) echo "Makefile targets"
	$(QUIET) - $(foreach MAKEFILE_PATH, $(MAKEFILE_LIST), \
		echo ""; \
		echo "$(MAKEFILE_PATH):"; \
		grep '^.PHONY: .* \#' $(MAKEFILE_PATH) | sed 's/\.PHONY: \(.*\) \# \(.*\)/  \1: \2/' | expand -t20; \
	)

##################
# Venv
##################

.PHONY: venv # Go into a python virtual environment

venv:
ifeq ($(VIRTUAL_ENV), )
	$(PYTHON_BIN) -m venv $(VENV_PATH)
	$(QUIET) echo "Start with:"
	$(QUIET) echo "$> source `basename $(VENV_PATH)`/bin/activate"
	$(QUIET) echo "End with:"
	$(QUIET) echo "$> deactivate"
endif

.PHONY: setup # Install scons in venv

setup: venv
	(source $(VENV_PATH)/bin/activate && $(PIP_BIN) install scons)

##################
# Scons (builder)
##################

.PHONY: build # Run scons builder ([mod <comma_separated_modules>])

build:
	$(QUIET) cd $(PROJECT_ROOT_PATH)
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
			pkgdep=$(pkgdep) \
			demo=$(demo) \
			libc=$(libc) \
			cpu=$(cpu) \
			docker_builder_image=$(docker_builder_image) \
			docker_runtime_image=$(docker_runtime_image) \
			docker_build_local=$(docker_build_local) \
	)
	$(QUIET) $(call echo_log_info,makefile,starting build with command: '$(SCONS_BUILD_CMD) $(BUILD_CMD_LINE)')
	$(QUIET) $(SCONS_BUILD_CMD) $(BUILD_CMD_LINE)

.PHONY: build_debug # Run scons builder with scons debug

build_debug: SCONS_ARGS = --debug=count,duplicate,explain,findlibs,includes,memoizer,memory,objects,prepare,presub,stacktrace,time
build_debug: SCONS_PREFIX = time
build_debug: build

.PHONY: build_dry # Run scons builder with expected build

build_dry: SCONS_ARGS = --dry-run
build_dry: build

# make mod MODULE
ifeq ($(MAKEARG_1), mod)
.PHONY: mod
MODULES_NAME := $(MAKEARG_2),$(m)
mod: modules = $(MODULES_NAME)
mod: build
endif # module

include $(MAKEFILE_TOOLS)/test.mk

include $(MAKEFILE_TOOLS)/lint.mk

include $(MAKEFILE_TOOLS)/vcpkg.mk

include $(MAKEFILE_TOOLS)/distribution.mk

include $(MAKEFILE_TOOLS)/install.mk

include $(MAKEFILE_TOOLS)/genesis.mk

include $(MAKEFILE_TOOLS)/android.mk


##########
# Serve
##########

.PHONY: serve_bin # Serve a python http.server on port $(PORT) (default: 8000)
.PHONY: serve_demo # Serve a python http.server on port $(PORT) (default: 8000) with CORS headers for WASM

PORT ?= 8000

serve_bin:
	$(PYTHON_BIN) $(SBT_PATH)/scripts/serve_wasm.py ${PORT} $(BIN_PATH)

serve_demo:
	$(PYTHON_BIN) $(SBT_PATH)/scripts/serve_wasm.py ${PORT} $(DEMO_PATH)

##########
# Cleanup
##########

.PHONY: clean # Remove triplet build
.PHONY: clean_dep # Remove triplet dependencies
.PHONY: cclean # Remove triplet build and cache
.PHONY: clean_dist # Remove distribution
.PHONY: clean_cache # Remove build cache
.PHONY: clean_build # Remove all builds and dependencies
.PHONY: fclean # Remove everything

clean:
	$(QUIET) $(call mk_log_info,makefile,removing compilation build)
	rm -rf $(OBJ_PATH)
	rm -rf $(INCLUDE_PATH)
	rm -rf $(LIB_PATH)
	rm -rf $(ETC_PATH)
	rm -rf $(SHARE_PATH)
	rm -rf $(BIN_PATH)
	rm -rf $(TEST_PATH)
	rm -rf $(DEMO_PATH)
	rm -f $(BUILD_PATH)/compile_commands.json

clean_dep:
	$(QUIET) $(call mk_log_info,makefile,removing dependencies)
	rm -rf $(BUILD_PATH)/vcpkg
	rm -f $(EXTLIB_PATH)
	rm -rf $(VCPKG_PATH)/packages

clean_dist:
	$(QUIET) $(call mk_log_info,makefile,removing distribution)
	rm -rf $(DIST_PATH)

clean_cache:
	$(QUIET) $(call mk_log_info,makefile,removing cache)
	rm -rf $(PROJECT_ROOT_PATH)/.scons_cache

cclean: clean_cache clean

clean_build:
	$(QUIET) $(call mk_log_info,makefile,removing build)
	rm -rf $(BUILD_ENTRY_PATH)

fclean: clean_build clean_dist clean_cache clean_dep
	$(QUIET) $(call mk_log_info,makefile,removing remaining files)
	$(QUIET) rm -f $(PROJECT_ROOT_PATH)/.sconsign.dblite
