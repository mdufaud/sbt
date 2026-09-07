##########
# Project
##########

# tar-pipe instead of cp -r: exclude build outputs and bytecode caches so a
# scaffold never ships stale artefacts from this working tree (sbtnewfs also
# skips .git). The sbt copy keeps its build/ directory: it is the sbt.build
# python package, not build output.
GENESIS_COPY_EXCLUDES := --exclude=__pycache__ --exclude='*.pyc' --exclude=build
SBT_COPY_EXCLUDES := --exclude=__pycache__ --exclude='*.pyc' --exclude=.git

ifeq ($(MAKEARG_1), sbtnewfs)

PROJECT_PATH := $(MAKEARG_2)

sbtnewfs:
ifeq ($(PROJECT_PATH),)
	$(error Usage: make sbtnewfs <project_path>)
endif
	if [ -d "$(PROJECT_PATH)" ]; then echo "Error: directory already exists: $(PROJECT_PATH)"; exit 1; fi
	mkdir -p $(PROJECT_PATH)/site_scons/sbt
	tar -C $(SBT_PATH)/genesis_fs $(GENESIS_COPY_EXCLUDES) -cf - . | tar -C $(PROJECT_PATH) -xf -
	tar -C $(SBT_PATH) $(SBT_COPY_EXCLUDES) -cf - . | tar -C $(PROJECT_PATH)/site_scons/sbt -xf -
	echo "New SBT project created in: $(PROJECT_PATH)"

endif # sbtnewfs

ifeq ($(MAKEARG_1), sbtnewgit)

PROJECT_PATH := $(MAKEARG_2)

sbtnewgit:
ifeq ($(PROJECT_PATH),)
	$(error Usage: make sbtnewgit <project_path>)
endif
	if [ -d "$(PROJECT_PATH)" ]; then echo "Error: directory already exists: $(PROJECT_PATH)"; exit 1; fi
	mkdir -p $(PROJECT_PATH)
	tar -C $(SBT_PATH)/genesis_fs $(GENESIS_COPY_EXCLUDES) -cf - . | tar -C $(PROJECT_PATH) -xf -
	git init -q $(PROJECT_PATH)
	git -c protocol.file.allow=always -C $(PROJECT_PATH) submodule add $(SBT_PATH) site_scons/sbt
	echo "New SBT project created in: $(PROJECT_PATH) (site_scons/sbt is a git submodule)"

endif # sbtnewgit
