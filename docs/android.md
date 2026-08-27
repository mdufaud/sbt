# Android APK Build Guide

Build Android APKs from any sbt module's demo or binary.

## Prerequisites

### 1. Java Development Kit (JDK 17+)

AGP (Android Gradle Plugin) requires JDK 17 or higher.

```bash
# Arch Linux
sudo pacman -S jdk17-openjdk

# Ubuntu / Debian
sudo apt install openjdk-17-jdk

# Fedora
sudo dnf install java-17-openjdk-devel
```

Set `JAVA_HOME` if multiple JDKs are installed:
```bash
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
```

### 2. Android SDK

Install the Android command-line tools from https://developer.android.com/studio#command-line-tools-only

```bash
mkdir -p /path/to/android-sdk/cmdline-tools
unzip commandlinetools-linux-*.zip -d /path/to/android-sdk/cmdline-tools/
mv /path/to/android-sdk/cmdline-tools/cmdline-tools /path/to/android-sdk/cmdline-tools/latest
```

Install required SDK components:
```bash
/path/to/android-sdk/cmdline-tools/latest/bin/sdkmanager \
    "platform-tools" \
    "platforms;android-36" \
    "build-tools;36.0.0" \
    "ndk;28.0.13004108"
```

Accept licenses:
```bash
/path/to/android-sdk/cmdline-tools/latest/bin/sdkmanager --licenses
```

### 3. Gradle (system-wide, no wrapper)

sbt uses Gradle directly — no `gradlew` wrapper is embedded in templates.

```bash
# Arch Linux
sudo pacman -S gradle

# Or install manually from https://gradle.org/releases/
```

### 4. Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ANDROID_NDK_PATH` | _(none)_ | **yes** | Path to NDK (e.g. `/path/to/android-sdk/ndk/28.0.13004108`) |
| `ANDROID_SDK_PATH` | `/path/to/android-sdk` | recommended | Path to SDK root |
| `JAVA_HOME` | _(auto-detected)_ | if multiple JDKs | JDK 17+ for Gradle |
| `ANDROID_API` | `24` | no | Minimum Android API level |

```bash
# Add to .bashrc / .zshrc
export ANDROID_NDK_PATH=/path/to/android-sdk/ndk/28.0.13004108
export ANDROID_SDK_PATH=/path/to/android-sdk
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
```

## Tested Versions

These are the versions known to work together:

| Component | Version |
|-----------|---------|
| Gradle | 9.3.1 |
| Android Gradle Plugin (AGP) | 9.1.0 |
| Android NDK | 28.0.13004108 (r28) |
| compileSdk | 36 |
| minSdk | 24 (Android 7.0) |
| targetSdk | 36 |
| JDK | 17+ (tested with 17 and 25) |
| Kotlin | bundled with AGP 9.x (no separate plugin) |

## Building

### Install dependencies (vcpkg)

```bash
make dep m=imgui demo=1 platform=android machine=arm64 static=1
```

### Build APK

```bash
make m=imgui platform=android machine=arm64 static=1 demo=1
```

Output: `build/arm64-android-bionic/ndk-28/fast/demo/<name>.apk`

### Other architectures

| `machine=` | Android ABI | Notes |
|------------|------------|-------|
| `arm64` / `aarch64` | arm64-v8a | Most common (default) |
| `arm32` | armeabi-v7a | Legacy 32-bit ARM |
| `x86_64` | x86_64 | Emulator / ChromeOS |
| `x86` | x86 | Legacy emulator |

```bash
make m=imgui platform=android machine=arm32 static=1 demo=1
```

### Install on device

```bash
adb install build/arm64-android-bionic/ndk-28/fast/demo/imgui_opengl3_android_demo.apk
# or via build/last symlink:
adb install build/last/demo/imgui_opengl3_android_demo.apk
```

## Running in an emulator

sbt ships makefile targets that drive the Android emulator end-to-end: create an
AVD, start a **visible** emulator window, install an APK, launch it, and stream
logcat. Terminal-mode demos render their `stdout`/`stderr` in a scrollable view on a
fake phone — no physical device needed.

### Required tools

| Tool | Location under `ANDROID_SDK_PATH` | Used by |
|------|-----------------------------------|---------|
| `adb` | `platform-tools/adb` | `adb`, `android-emu*` |
| `emulator` | `emulator/emulator` | `android-emu`, `android-emu-run` |
| `sdkmanager` | `cmdline-tools/latest/bin/sdkmanager` | `android-emu-setup` |
| `avdmanager` | `cmdline-tools/latest/bin/avdmanager` | `android-emu-setup` |

`ANDROID_SDK_PATH` **must** be set for any of these targets — they fail fast
otherwise. Each target also checks the specific binary it needs and reports the
missing path. If your tools live under **different** roots (e.g. the emulator was
installed via Android Studio in `~/Android/Sdk` while command-line tools are in
`/opt/android-sdk`), point `ANDROID_SDK_PATH` at the root holding most of them and
override the rest:

```bash
make android-emu ANDROID_EMU_BIN=~/Android/Sdk/emulator/emulator
```

AVDs live in `~/.android/avd` regardless of which SDK root is used.

### Targets

```bash
make android-emu-setup    # create the AVD (one-time)
make android-emu          # start the visible emulator window
make android-emu-run <path/to/apk>   # start emulator if down, then install+launch+logcat
make android-emu-stop     # kill the running emulator
make adb <path/to/apk>    # install+launch+logcat on an already-running device/emulator
```

`android-emu-setup` creates an **x86_64** `google_apis` AVD. An x86_64 AVD runs an
**arm64-v8a** APK via the image's built-in ARM-to-x86 translation (API 30+
`google_apis` images) — no separate arm64 AVD is needed.

Typical run-only flow (assumes the APK is already built):

```bash
make demo m=sys platform=android   # build -> build/.../demo/sys_demo.apk
make android-emu-run build/arm64-android-bionic/ndk-28/fast/dynamic/demo/sys_demo.apk
```

`android-emu-run` takes an **explicit APK path**, so it works for any APK whether it
came from `demo/` or `bin/`. `android-emu` is idempotent — if an emulator is already
up it is reused, no second instance starts.

### Tunable variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANDROID_SDK_PATH` | _(none)_ | SDK root; required |
| `ANDROID_ADB_BIN` | `$(ANDROID_SDK_PATH)/platform-tools/adb` | adb binary |
| `ANDROID_EMU_BIN` | `$(ANDROID_SDK_PATH)/emulator/emulator` | emulator binary |
| `AVD_NAME` | `<app-name>_emulation` | AVD name |
| `EMU_SYS_IMAGE` | `system-images;android-35;google_apis;x86_64` | system image |
| `EMU_DEVICE` | `pixel_6` | device profile |
| `EMU_WINDOW` | `1` | `0` = headless (`-no-window`, swiftshader), for CI |

## How It Works

### Template system

sbt provides default Android project templates in `site_scons/sbt/android/`. When building a demo or binary for `platform=android`, sbt:

1. Copies the default Gradle project templates to a staging directory
2. If the module provides an override at `<module>/android/`, overlays those files on top
3. Replaces `__SBT_*__` placeholders in all text files
4. Compiles C++ sources into a `.so` (SharedLibrary via NDK clang)
5. Copies the `.so` into the staged project's `jniLibs/<abi>/`
6. Runs `gradle assemble<BuildType>` (see [Build type mapping](#build-type-mapping); debug by default, `assembleRelease` for a "release-like" mode)
7. Copies the resulting APK to the build output directory

The Gradle caches live under a **single directory per build configuration** — a
sibling of `lib/` and `demo/`: `build/<triplet>/<mode>/<liblink>/gradle/`. It is
removed by the `clean` rule (`rm -rf $(BUILD_PATH)/gradle`) and survives the
staging dir, which is re-created on every build. Inside it:

- **`build-cache/`** — the **shared** local build cache, one per configuration,
  shared by every APK of that configuration. Gradle's build cache is safe to
  share across concurrent builds.
- **`<apk>/.gradle/`** — a **per-APK** Gradle project cache. Each APK is a
  separate Gradle project, so it gets its own `.gradle` (and its own
  configuration cache). This avoids Gradle's single-writer lock contention
  (notably on the configuration cache) when several APKs are assembled in
  parallel (e.g. under `-j`); the heavier build/dependency caches stay shared.

### Build-type mapping

Whether an sbt compile **mode** produces the stripped APK is a **project
decision**, declared in the project's `app.py` via the `android_release_modes`
list. Every mode listed builds `assembleRelease`; any unlisted mode builds
`assembleDebug`. There is **no** built-in mapping in sbt, so a `release` build
only happens for modes you opt in:

```python
# app.py
android_release_modes = ["release"]            # mode=release -> assembleRelease
# android_release_modes = ["release", "superReleaseToto2"]
```

```bash
make m=imgui platform=android machine=arm64 static=1 mode=release demo=1
```

The release build type sets `ndk { debugSymbolLevel = 'NONE' }` and the
`ndkVersion` is pinned to the installed NDK, which fixes AGP's
`Unable to strip ... packaging them as they are` warning.

### Optional APK signing

By default `assembleRelease` produces an **unsigned** APK
(`app-release-unsigned.apk`). To sign it, point `android_sign_config` at a
gitignored `keystore.properties` file (relative to the project root, or
absolute). sbt then injects a keystore loader + `signingConfigs { release { ... } }`
block into the staged `app/build.gradle` and references it from the release build
type, so the release APK is signed — **without ever writing the passwords into a
generated file or committing them**:

```python
# app.py  (no secrets here)
android_sign_config = "keystore.properties"
```

Copy the template and fill in the real values, then **gitignore the file**:

```ini
# keystore.properties   (do NOT commit this)
storeFile=keystores/release.keystore   # resolved relative to this file's dir
storePassword=CHANGE_ME
keyAlias=release
keyPassword=CHANGE_ME
```

A ready-to-copy template lives at `android/keystore.properties.example`. If
`android_sign_config` is unset/empty, the placeholders resolve to empty strings
and the release APK stays unsigned (the default). If the config points to a file
that is missing or lacks a required key (`storeFile`, `storePassword`,
`keyAlias`, `keyPassword`), sbt fails the build with a clear error rather than
silently producing an unsigned APK.

> **Note:** keystores and passwords are project-controlled build config. On
> debug builds the debug APK is auto-signed by AGP; this setting only affects
> the release build type.

### Two modes

**Terminal mode** (default): For non-graphical programs. The app displays a scrollable monospace terminal view showing captured `stdout` and `stderr` output. The user's `main()` runs in a background thread.

**NativeActivity mode** (override): For graphical apps (e.g. ImGui). Uses `android_native_app_glue` and `android_main()` entry point. The module provides a custom `AndroidManifest.xml` and `MainActivity.kt`.

### Placeholders

| Placeholder | Replaced with |
|------------|---------------|
| `__SBT_PROJECT_NAME__` | Demo/binary name |
| `__SBT_NAMESPACE__` | Java namespace (defaults to `<app-name>.android.terminal`) |
| `__SBT_APP_ID__` | Application ID (namespace + sanitized name) |
| `__SBT_APP_LABEL__` | Display name in launcher |
| `__SBT_LIB_NAME__` | Shared library name (without lib prefix / .so suffix) |
| `__SBT_ABI__` | NDK ABI string (e.g. `arm64-v8a`) |
| `__SBT_NDK_VERSION__` | Installed NDK version (e.g. `28.0.13004108`), pinned as `ndkVersion` |
| `__SBT_KEYSTORE_LOADER__` | Groovy loader that reads the keystore.properties file, or empty when unsigned |
| `__SBT_SIGN_DECL__` | `signingConfigs { release { ... } }` block, or empty when unsigned |
| `__SBT_SIGN_REF__` | `signingConfig signingConfigs.release`, or empty when unsigned |

## Module Override

To customize the Android packaging for your module, create a `<module>/android/` directory with:

### config.py (required for override)

```python
namespace = "com.example.myapp"   # Java package namespace
native_activity = True            # True for NativeActivity, False for terminal mode
```

### Override files

Any file placed in `<module>/android/` (except `config.py`) is copied on top of the default templates. Typical overrides:

```
mymodule/android/
├── config.py
└── app/src/main/
    ├── AndroidManifest.xml       # Custom manifest
    └── java/com/example/myapp/
        └── MainActivity.kt       # Custom Activity
```

### Example: imgui override

```
mymodule/android/
├── config.py                     # namespace="com.example.imgui", native_activity=True
└── app/src/main/
    ├── AndroidManifest.xml       # NativeActivity with configChanges
    └── java/com/example/imgui/
        └── MainActivity.kt       # NativeActivity + keyboard/unicode JNI
```

## Troubleshooting

### "SDK location not found"

Set `ANDROID_SDK_PATH`:
```bash
export ANDROID_SDK_PATH=/path/to/android-sdk
```

### Gradle version mismatch

AGP 9.1.0 requires Gradle 9.x. Check with `gradle --version`.

### Missing NDK

```bash
export ANDROID_NDK_PATH=/path/to/android-sdk/ndk/28.0.13004108
```

### APK crashes on launch

Check logcat for native crash details:
```bash
adb logcat -s <app-name>:* AndroidRuntime:* DEBUG:*
```

The terminal bridge wraps `main()` in a try/catch and reports uncaught exceptions. For signal crashes (SIGSEGV, etc.), check the `DEBUG` tag in logcat.
