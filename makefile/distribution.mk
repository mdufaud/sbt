###############
# Distribution
###############

.PHONY: dist  # Compile and package build (tar/apt/pacman)

# make dist
ifeq ($(MAKEARG_1), dist)

MODULES_NAME := $(m)

# make dist mod MODULE type
ifeq ($(MAKEARG_2), mod)
.PHONY: mod
MODULES_NAME := $(MAKEARG_3),$(m)
DIST_TYPE := $(MAKEARG_4)
mod:
	$(QUIET) echo > /dev/null
else
# make dist type
DIST_TYPE = $(MAKEARG_2)
endif

dist: dist = $(DIST_TYPE)
dist: mode = release
dist: modules = $(MODULES_NAME)
dist: build
ifeq ($(DIST_TYPE), docker)
	$(QUIET) $(call echo_log_info,makefile,Dockerfile generated — to build and run:)
	$(QUIET) echo "  docker build -t $(APP_NAME) $(BUILD_ENTRY_PATH)/last/dist/docker/"
	$(QUIET) echo "  docker run --rm $(APP_NAME) <binary>"
endif

$(MODULES_NAME):
	$(QUIET) echo > /dev/null

$(DIST_TYPE):
	$(QUIET) echo > /dev/null

endif # dist
