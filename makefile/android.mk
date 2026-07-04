##########
# ADB
##########

.PHONY: adb # Install and launch an APK on a running device/emulator: make adb <path/to/apk>
.PHONY: android-emu-setup # Setup Android emulator AVD: make android-emu-setup
.PHONY: android-emu # Start Android emulator (visible window, EMU_WINDOW=0 for headless): make android-emu
.PHONY: android-emu-run # Start emulator (if down) then install+launch+logcat an APK: make android-emu-run <path/to/apk>
.PHONY: android-emu-stop # Stop Android emulator: make android-emu-stop

ANDROID_ADB_BIN    ?= $(ANDROID_SDK_PATH)/platform-tools/adb
ANDROID_EMU_BIN    ?= $(ANDROID_SDK_PATH)/emulator/emulator
ANDROID_SDKMANAGER ?= $(ANDROID_SDK_PATH)/cmdline-tools/latest/bin/sdkmanager
ANDROID_AVDMANAGER ?= $(ANDROID_SDK_PATH)/cmdline-tools/latest/bin/avdmanager

AVD_NAME ?= $(APP_NAME)_emulation
EMU_SYS_IMAGE ?= system-images;android-35;google_apis;x86_64
EMU_DEVICE ?= pixel_6
EMU_WINDOW ?= 1

ifeq ($(EMU_WINDOW),0)
EMU_FLAGS := -no-window -gpu swiftshader_indirect
else
EMU_FLAGS := -gpu auto
endif

ADB_APK := $(MAKEARG_2)

# Require ANDROID_SDK_PATH whenever an android target is requested
ifneq ($(filter adb android-emu android-emu-run android-emu-setup android-emu-stop,$(MAKECMDGOALS)),)
ifeq ($(ANDROID_SDK_PATH),)
$(error ANDROID_SDK_PATH not set -- export it to your Android SDK root (the dir holding platform-tools/, emulator/, cmdline-tools/))
endif
endif

# Prevent make from interpreting the APK path argument as a target
ifneq ($(filter adb android-emu-run,$(MAKECMDGOALS)),)
ifeq ($(ADB_APK),)
$(error Usage: make $(filter adb android-emu-run,$(MAKECMDGOALS)) <path/to/apk>)
endif
$(ADB_APK):
	@:
endif

adb:
	@[ -x "$(ANDROID_ADB_BIN)" ] || { printf 'Error: adb not found: %s\n  set ANDROID_SDK_PATH or override ANDROID_ADB_BIN=\n' "$(ANDROID_ADB_BIN)" >&2; exit 1; }
	@[ -f "$(ADB_APK)" ] || { printf 'Error: APK not found: %s\n' "$(ADB_APK)" >&2; exit 1; }
	$(ANDROID_ADB_BIN) install -r $(ADB_APK)
	@ADB_PKG=$$($(BUILD_TOOLS)/sbt/scripts/apk_info.sh package $(ADB_APK)) && \
		ADB_ACT=$$($(BUILD_TOOLS)/sbt/scripts/apk_info.sh activity $(ADB_APK)) && \
		echo "launching $${ADB_PKG}/$${ADB_ACT}" && \
		$(ANDROID_ADB_BIN) shell am start -n "$${ADB_PKG}/$${ADB_ACT}"
	@echo "showing logcat (Ctrl+C to stop)"
	$(ANDROID_ADB_BIN) logcat -c
	$(ANDROID_ADB_BIN) logcat -s $(APP_NAME):* AndroidRuntime:E ActivityManager:W

android-emu-setup:
	@[ -x "$(ANDROID_SDKMANAGER)" ] || { printf 'Error: sdkmanager not found: %s\n  set ANDROID_SDK_PATH or override ANDROID_SDKMANAGER=\n' "$(ANDROID_SDKMANAGER)" >&2; exit 1; }
	@[ -x "$(ANDROID_AVDMANAGER)" ] || { printf 'Error: avdmanager not found: %s\n  set ANDROID_SDK_PATH or override ANDROID_AVDMANAGER=\n' "$(ANDROID_AVDMANAGER)" >&2; exit 1; }
	$(ANDROID_SDKMANAGER) --install "$(EMU_SYS_IMAGE)" "emulator"
	$(ANDROID_AVDMANAGER) create avd -n $(AVD_NAME) -k "$(EMU_SYS_IMAGE)" -d $(EMU_DEVICE) --force
	@echo "AVD '$(AVD_NAME)' created. Start with: make android-emu"

android-emu:
	@[ -x "$(ANDROID_EMU_BIN)" ] || { printf 'Error: emulator not found: %s\n  set ANDROID_SDK_PATH or override ANDROID_EMU_BIN=\n' "$(ANDROID_EMU_BIN)" >&2; exit 1; }
	@[ -x "$(ANDROID_ADB_BIN)" ] || { printf 'Error: adb not found: %s\n  set ANDROID_SDK_PATH or override ANDROID_ADB_BIN=\n' "$(ANDROID_ADB_BIN)" >&2; exit 1; }
	@if $(ANDROID_ADB_BIN) devices 2>/dev/null | grep -q "emulator.*device"; then \
		echo "Emulator already running"; \
	else \
		echo "Starting emulator $(AVD_NAME)..."; \
		$(ANDROID_EMU_BIN) -avd $(AVD_NAME) -no-audio -no-boot-anim $(EMU_FLAGS) & \
		echo "Waiting for boot..."; \
		$(ANDROID_ADB_BIN) wait-for-device; \
		timeout 180 bash -c 'while [ "$$($(ANDROID_ADB_BIN) shell getprop sys.boot_completed 2>/dev/null)" != "1" ]; do sleep 3; done'; \
		echo "Waiting for package manager..."; \
		sleep 30; \
		echo "Emulator ready"; \
	fi

android-emu-run: android-emu
	@[ -f "$(ADB_APK)" ] || { printf 'Error: APK not found: %s\n' "$(ADB_APK)" >&2; exit 1; }
	$(MAKE) adb $(ADB_APK)

android-emu-stop:
	@[ -x "$(ANDROID_ADB_BIN)" ] || { printf 'Error: adb not found: %s\n  set ANDROID_SDK_PATH or override ANDROID_ADB_BIN=\n' "$(ANDROID_ADB_BIN)" >&2; exit 1; }
	@$(ANDROID_ADB_BIN) emu kill 2>/dev/null || echo "No emulator running"
