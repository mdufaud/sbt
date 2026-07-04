##########
# Project
##########

ifeq ($(MAKEARG_1), sbtnewfs)

PROJECT_PATH := $(MAKEARG_2)

sbtnewfs:
ifeq ($(PROJECT_PATH),)
	$(error Usage: make sbtnewfs <project_path>)
endif
	if [ -d "$(PROJECT_PATH)" ]; then echo "Error: directory already exists: $(PROJECT_PATH)"; exit 1; fi
	mkdir -p $(PROJECT_PATH)/site_scons
	cp -r $(SBT_PATH)/genesis_fs/* $(PROJECT_PATH)
	cp -r $(SBT_PATH)/ $(PROJECT_PATH)/site_scons/sbt
	rm -rf $(PROJECT_PATH)/site_scons/sbt/.git
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
	cp -r $(SBT_PATH)/genesis_fs/* $(PROJECT_PATH)
	git init -q $(PROJECT_PATH)
	git -c protocol.file.allow=always -C $(PROJECT_PATH) submodule add $(SBT_PATH) site_scons/sbt
	echo "New SBT project created in: $(PROJECT_PATH) (site_scons/sbt is a git submodule)"

endif # sbtnewgit
