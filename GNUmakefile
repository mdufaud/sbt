SBT_PATH := $(CURDIR)

include $(SBT_PATH)/makefile/args.mk

.PHONY: help
help:
	@echo "This repository is the SBT build framework itself, not a buildable project."
	@echo "Usage: make sbtnewfs <project_path>   # scaffold a new project, vendoring this repo as plain files"
	@echo "       make sbtnewgit <project_path>  # scaffold a new project, vendoring this repo as a git submodule"

include makefile/genesis.mk
