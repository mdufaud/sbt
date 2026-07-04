# Dependencies (extlibs) Guide

## Overview

External C/C++ libraries are managed through **vcpkg**. The flow:

```
app.py (declare)  →  make dep (install)  →  extlib/ (use)
```

1. Declare dependencies and versions in `app.py`
2. Run `make dep` to install them via vcpkg
3. SBT auto-links `extlib/include` and `extlib/lib` into every module build

## Declaring dependencies

### Library versions

In `app.py`:

```python
extlibs = {
    "fmt": "12.1.0",
    "openssl": "3.1.0",
    "libwebsockets": "4.5.2",
    "gtest": "1.17.0#2",       # port revision via #N
    "opengl": "",              # empty = latest from baseline
}
```

### Assigning extlibs to modules

```python
modules = {
    "net": {
        "extlibs": ['openssl'],
        "libs": ['ssl', 'crypto'],
    },
    "http": {
        "extlibs": ['libwebsockets', 'curl'],
        "linux-libs": ['websockets', 'curl'],
        "windows-libs": ['websockets_static', 'curl'],
    },
}
```

`extlibs` declares **what vcpkg installs**. `libs` declares **what to link** (`-l<name>`). These are separate because:
- vcpkg package names differ from library filenames
- Link names vary across platforms (e.g., `websockets` vs `websockets_static`)
- Some vcpkg packages install headers only (e.g., `nlohmann-json`)

### Platform-specific extlibs

```python
"sys": {
    "linux-extlibs": ['libuuid'],
    "android-extlibs": ['libuuid'],
    # libuuid not needed on windows (rpcrt4 provides UUID)
},
```

### vcpkg baseline

```python
vcpkg_baseline = "3a3285c4878c7f5a957202201ba41e6fdeba8db4"
```

Pin all packages to a specific vcpkg commit. Update this to get newer port versions.

## vcpkg features

### Global features

```python
extlibs_features = {
    "imgui": ["glfw-binding", "opengl3-binding", "sdl3-binding"],
}
```

### Platform-specific features

```python
extlibs_features_linux = {
    "libusb": ["udev"],              # udev is linux-only
}
extlibs_features_windows = {
    "imgui": ["win32-binding", "dx11-binding"],
}
extlibs_features_android = {
    "imgui": ["android-binding", "opengl3-binding"],
}
extlibs_features_web = {
    "imgui": ["sdl3-binding", "opengl3-binding"],
}
```

Platform features (`extlibs_features_{platform}`) are applied on native builds only. In cross-compilation, only global `extlibs_features` are used.

### Disabling default features

Declared in `addon/vcpkg/config.py`:

```python
vcpkg_no_default_features = [
    "dbus",    # systemd default doesn't build on musl
    "libusb",  # udev default requires system headers
]
```

Applied only in cross-builds. These libs get `"default-features": false` in the vcpkg manifest.

## Skipping libraries per platform

```python
extlibs_skip_windows = ["libwebsockets", "libssh", "libcap"]
extlibs_skip_web = ["openssl", "libwebsockets", "curl", "libssh"]
extlibs_skip_android = ["dbus", "libcap", "libwebsockets", "curl"]
```

Skipped libraries are excluded from the vcpkg manifest for that platform.

## Test & demo dependencies

```python
test_extlibs = ['gtest']
test_libs = ['gtest']

demo_extlibs = ['cli11']
demo_libs = ['CLI11']
```

Installed only when `test=1` or `demo=1` is passed to `make dep`.

## Installing dependencies

```bash
make dep                       # Install for current build config
make dep m=util,core           # Only deps needed by util, core
make dep test=1                # Include test deps (gtest)
make dep demo=1                # Include demo deps (cli11)
make dep test=1 demo=1         # Both
```

### Cross-compilation

```bash
make dep machine=aarch64              # aarch64 linux
make dep libc=musl                    # musl libc
make dep platform=windows             # windows via mingw
make dep compiler=em m=util,core      # emscripten
make dep platform=android m=imgui     # android NDK
```

Each target has its own vcpkg triplet and installed packages in a separate build directory.

### Useful vcpkg commands

```bash
make dep list                  # List installed packages
make dep tree                  # Dependency tree
make dep search <name>         # Search for a package
make dep update                # Update vcpkg itself
make dep install <name>        # Install a package manually
```

## How it works internally

### Manifest generation

`make dep` generates a `vcpkg.json` dynamically based on selected modules:

```json
{
  "builtin-baseline": "3a3285c4878c7f5a957202201ba41e6fdeba8db4",
  "dependencies": [
    "fmt",
    {"name": "imgui", "features": ["glfw-binding", "opengl3-binding"]},
    {"name": "dbus", "default-features": false}
  ],
  "overrides": [
    {"name": "fmt", "version": "12.1.0"}
  ]
}
```

Only dependencies for the selected modules are included. The manifest changes based on platform, modules, and features.

### Triplet resolution

vcpkg triplet format: `<machine>-<platform>[-suffix][-linkage]`

| Build config | Triplet |
|-------------|---------|
| Native x86_64 linux | `x64-linux` |
| Cross aarch64 linux | `arm64-linux` |
| Cross arm32 linux | `arm-linux` |
| Cross riscv64 linux | `riscv64-linux` |
| Musl x86_64 | `x64-linux-musl` |
| Windows (mingw) | `x64-mingw-dynamic` |
| Emscripten | `wasm32-emscripten-threads` |
| Android arm64 | `arm64-android` |

Triplets are discovered automatically — from vcpkg built-in, SBT custom (`sbt/vcpkg/triplets/`), addon custom (`addon/vcpkg/triplets/`), or generated dynamically (musl, zig).

### Installed location

```
build/<path>/
├── vcpkg/
│   ├── vcpkg.json                    # Generated manifest
│   ├── overlay-triplets/             # Generated triplet wrappers
│   └── vcpkg_installed/<triplet>/
│       ├── include/                  # Headers
│       └── lib/                      # Libraries
└── extlib/  → vcpkg_installed/<triplet>/   # Symlink
```

SCons adds `extlib/include` to `CPPPATH` and `extlib/lib` to `LIBPATH` for every module automatically.

### Binary cache

vcpkg caches compiled packages in `.vcpkg/archives/`. After the first `make dep`, subsequent calls restore from cache (~1 second).

## Linking: native vs cross

### Native builds

On native linux, two mechanisms complement vcpkg:

1. **pkg-config** — `"pkg-configs": ["lua-5.3"]` runs `pkg-config --cflags --libs`
2. **parse-configs** — `"parse-configs": ["pcap-config --cflags --libs"]` runs the command

These auto-resolve include paths, lib paths, and transitive deps.

### Cross builds

Both mechanisms are **disabled** in cross-compilation (they return host paths = wrong). Instead:

- vcpkg provides all headers/libs in `extlib/`
- Transitive deps must be listed explicitly in the module config

### The transitive dependency problem

vcpkg often produces **static archives** (`.a`) for cross targets. When linking against `.a`, all transitive deps must be explicit.

Example: `libzip.a` depends on `libz.a`, `libbz2.a`, etc.
- **Native**: `pkg-config --libs libzip` resolves transitive deps automatically
- **Cross**: must list them manually

```python
"zip": {
    "extlibs": ['libzip'],
    "libs": ['zip'],
    # Native: pkg-config resolves these automatically, but needed because libzip.a is static
    "linux-native-libs": ['z', 'bz2', 'lzma', 'ssl', 'crypto'],
    # Cross: different set because vcpkg may provide dynamic libs
    "linux-cross-libs": ['z', 'bz2', 'ssl', 'crypto'],
},
```

### variant keys for link differences

```python
"usb": {
    "extlibs": ['libusb'],
    # native: udev is a system dep, parse-configs gives us libusb flags
    "native-libs": ['udev'],
    "parse-configs": ["pkg-config libusb-1.0 --cflags --libs"],
    # cross: vcpkg libusb built without udev, parse-configs skipped
    "cross-libs": ['usb-1.0'],
},
```

## Package manager integration

For native distribution without vcpkg, map extlib names to system packages:

```python
# addon/distribution.py
apt_packages = {
    "fmt": "libfmt-dev",
    "openssl": "libssl-dev",
    "curl": "libcurl4-openssl-dev",
}

pacman_packages = {
    "fmt": "fmt",
    "openssl": "openssl",
    "curl": "curl",
}

yum_packages = {
    "fmt": "fmt-devel",
    "openssl": "openssl-devel",
    "curl": "libcurl-devel",
}
```

List system package deps:

```bash
make pkgdep apt               # Debian/Ubuntu packages
make pkgdep pacman             # Arch packages
make pkgdep yum                # RHEL/Fedora packages
```

## Quick reference

| Task | Command / Config |
|------|-----------------|
| Add an extlib | `extlibs["mylib"] = "1.0.0"` in `app.py` |
| Assign to module | `"extlibs": ['mylib']` in module config |
| Link the lib | `"libs": ['mylib']` in module config |
| Platform-specific lib | `"linux-libs": ['mylib']` |
| Add feature | `extlibs_features["mylib"] = ["feature1"]` |
| Skip on platform | `extlibs_skip_windows = ["mylib"]` |
| Install | `make dep` |
| Install for cross | `make dep machine=aarch64` |
