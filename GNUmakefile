SBT_PATH := $(CURDIR)

MAKEARG_1 := $(word 1, $(MAKECMDGOALS))
MAKEARG_2 := $(word 2, $(MAKECMDGOALS))

.PHONY: help
help:
	@echo "This repository is the SBT build framework itself, not a buildable project."
	@echo "Usage: make sbtnewfs <project_path>   # scaffold a new project, vendoring this repo as plain files"
	@echo "       make sbtnewgit <project_path>  # scaffold a new project, vendoring this repo as a git submodule"

include makefile/genesis.mk
