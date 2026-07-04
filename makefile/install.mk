##########
# Install
##########

ifeq ($(MAKEARG_1), install)

ifeq ($(INSTALL_PREFIX),)
    INSTALL_PREFIX := /usr/local
endif

INSTALLED_FILES_DESTINATION := $(PROJECT_ROOT_PATH)/.installed
INSTALL_LIB_DEST := $(INSTALL_DESTDIR)$(INSTALL_PREFIX)/lib$(INSTALL_LIBSUFFIX)
INSTALL_BIN_DEST := $(INSTALL_DESTDIR)$(INSTALL_PREFIX)/bin$(INSTALL_BINSUFFIX)
INSTALL_ETC_DEST := $(INSTALL_DESTDIR)/etc$(INSTALL_ETCSUFFIX)
INSTALL_INCLUDE_DEST := $(INSTALL_DESTDIR)$(INSTALL_PREFIX)/include$(INSTALL_INCLUDESUFFIX)
INSTALL_SHARE_DEST := $(INSTALL_DESTDIR)$(INSTALL_PREFIX)/share$(INSTALL_SHARESUFFIX)

.PHONY: confirm_install # List dirs to install and ask confirmation

confirm_install:
	$(QUIET) $(call mk_log_info,makefile,will install in: $(INSTALL_DESTDIR)$(INSTALL_PREFIX))
	$(QUIET) $(call mk_log_info,makefile,change install directory with: INSTALL_DESTDIR)
	$(QUIET) $(call mk_log_info,makefile,change default /usr/local with: INSTALL_PREFIX)
ifeq ($(INSTALL_NOCONFIRM),)
	$(QUIET) echo -n "Please confirm installation directory [y/N] " && read answer && [ $${answer:-N} = y ]
else
	$(QUIET) $(call mk_log_info,makefile,INSTALL_NOCONFIRM set — skipping confirmation)
endif

.PHONY: install # List dirs to install, ask confirmation and install on system and creates a file with path of all installed files

install: confirm_install
	$(QUIET) $(call mk_log_info,makefile,installed files can be found in: $(INSTALLED_FILES_DESTINATION))
	$(QUIET) echo "# install date: `date "+%Y-%m-%d %H:%M:%S"`" > $(INSTALLED_FILES_DESTINATION)
# install lib
	$(QUIET) $(call echo_log_info,makefile,installing librairies: ${LIB_PATH} -> $(INSTALL_LIB_DEST))
	$(QUIET) for path in `ls -A $(LIB_PATH) 2>/dev/null`; do \
		dest=$(INSTALL_LIB_DEST)/$$path; \
		install -D --compare --mode=755 "$(LIB_PATH)/$$path" "$$dest"; \
		echo "$$dest" >> $(INSTALLED_FILES_DESTINATION); \
	done
ifeq ($(INSTALL_NO_EXTLIBS),)
# install extlibs (vcpkg-built shared libraries) - installed binaries resolve
# them via their $ORIGIN/../lib RUNPATH; opt out with INSTALL_NO_EXTLIBS=1
	$(QUIET) $(call echo_log_info,makefile,installing extlibs: ${EXTLIB_LIB_PATH} -> $(INSTALL_LIB_DEST))
	$(QUIET) for path in `ls -A $(EXTLIB_LIB_PATH) 2>/dev/null | grep '\.so'`; do \
		dest=$(INSTALL_LIB_DEST)/$$path; \
		install -D --compare --mode=755 "$(EXTLIB_LIB_PATH)/$$path" "$$dest"; \
		echo "$$dest" >> $(INSTALLED_FILES_DESTINATION); \
	done
endif
# install bin
	$(QUIET) $(call echo_log_info,makefile,installing binaries: ${BIN_PATH} -> $(INSTALL_BIN_DEST))
	$(QUIET) for path in `ls -A $(BIN_PATH) 2>/dev/null`; do \
		dest=$(INSTALL_BIN_DEST)/$$path; \
		install -D --compare --mode=755 "$(BIN_PATH)/$$path" "$$dest"; \
		echo "$$dest" >> $(INSTALLED_FILES_DESTINATION); \
	done
# install demo bins
	$(QUIET) $(call echo_log_info,makefile,installing demos: ${DEMO_PATH} -> $(INSTALL_BIN_DEST))
	$(QUIET) for path in `ls -A $(DEMO_PATH) 2>/dev/null`; do \
		dest=$(INSTALL_BIN_DEST)/$$path; \
		install -D --compare --mode=755 "$(DEMO_PATH)/$$path" "$$dest"; \
		echo "$$dest" >> $(INSTALLED_FILES_DESTINATION); \
	done
# getting all root directories of built resources for future removal
	$(QUIET) for path in `ls -A $(ETC_PATH) 2>/dev/null`; do \
		dest="$(INSTALL_ETC_DEST)/$$path"; \
		echo "$$dest" >> $(INSTALLED_FILES_DESTINATION); \
	done
# install etc
	$(QUIET) $(call echo_log_info,makefile,installing resources: ${ETC_PATH} -> $(INSTALL_ETC_DEST))
	$(QUIET) for path in `find $(ETC_PATH) -type f 2>/dev/null | sed "s|${ETC_PATH}/||g"`; do \
		dest="$(INSTALL_ETC_DEST)/$$path"; \
		install -D --compare --mode=744 "$(ETC_PATH)/$$path" "$$dest"; \
	done
# getting all root directories of built includes for future removal
	$(QUIET) for path in `ls -A $(INCLUDE_PATH) 2>/dev/null`; do \
		dest="$(INSTALL_INCLUDE_DEST)/$$path"; \
		echo "$$dest" >> $(INSTALLED_FILES_DESTINATION); \
	done
# install headers
	$(QUIET) $(call echo_log_info,makefile,installing headers: ${INCLUDE_PATH} -> $(INSTALL_INCLUDE_DEST))
	$(QUIET) for path in `find $(INCLUDE_PATH) -type f 2>/dev/null | sed "s|${INCLUDE_PATH}/||g"`; do \
		dest=$(INSTALL_INCLUDE_DEST)/$$path; \
		install -D --compare --mode=744 "$(INCLUDE_PATH)/$$path" "$$dest"; \
	done
# getting all root directories of built share for future removal
	$(QUIET) for path in `ls -A $(SHARE_PATH) 2>/dev/null`; do \
		dest="$(INSTALL_SHARE_DEST)/$$path"; \
		echo "$$dest" >> $(INSTALLED_FILES_DESTINATION); \
	done
# install shared
	$(QUIET) $(call echo_log_info,makefile,installing shared: ${SHARE_PATH} -> $(INSTALL_SHARE_DEST))
	$(QUIET) for path in `find $(SHARE_PATH) -type f 2>/dev/null | sed "s|${SHARE_PATH}/||g"`; do \
		dest=$(INSTALL_SHARE_DEST)/$$path; \
		install -D --compare --mode=744 "$(SHARE_PATH)/$$path" "$$dest"; \
	done

endif # install

ifeq ($(MAKEARG_1), uninstall)

.PHONY: uninstall # Read file with path of all installed files, asks for confirmation and removes every files

uninstall:
	$(QUIET) $(call mk_log_info,makefile,reading files to remove from: $(INSTALLED_FILES_DESTINATION))
	$(eval INSTALLED_FILES = $(shell cat $(INSTALLED_FILES_DESTINATION) | tail -n +2))
	$(QUIET) echo $(INSTALLED_FILES) | tr ' ' '\n'
	$(QUIET) $(call echo_log_warning,makefile,those files will be removed)
	$(QUIET) echo -n "Please confirm files removal [y/N] " && read answer && [ $${answer:-N} = y ]
	rm -rf $(INSTALLED_FILES)
	rm -f $(INSTALLED_FILES_DESTINATION)

endif # uninstall
