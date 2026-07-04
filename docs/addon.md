# Addon Guide

## What is addon?

`site_scons/addon/` is the **project-specific extension point** for the SBT build system.

SBT (`site_scons/sbt/`) is a generic, reusable build framework. `addon/` contains project-specific configuration that SBT loads automatically.

```
site_scons/
├── sbt/           # Generic build system
│   ├── scons.py
│   ├── core/      # foundations (builder, loader, architectures, logger, utils)
│   ├── vcpkg/
│   └── ...
└── addon/         # Project-specific extensions (stays in your repo)
    ├── distribution.py
    ├── makefile/
    └── vcpkg/
```

## Structure

```
site_scons/addon/
├── distribution.py          # Package manager metadata
├── makefile/
│   └── Makefile.custom      # Extra Make targets
└── vcpkg/
    ├── config.py            # Per-port cmake options, vcpkg flags
    ├── overlay-ports/       # Patched vcpkg ports
    └── triplets/            # Custom vcpkg triplet .cmake files (optional)
```

## How addon files are loaded

### Via app.py includes

```python
# app.py
includes = [
    "addon/vcpkg/config.py",
    "addon/distribution.py",
]
```

Paths are relative to `site_scons/`. The loader processes includes in two phases:

1. **Merge** — All public attributes (not `_`-prefixed) from the included file are copied into the `app` module
2. **Configure** — If the include defines `configure(app)`, it's called with the merged `app`

This means any variable you define in `addon/vcpkg/config.py` becomes accessible as `app.vcpkg_cflags`, `app.vcpkg_cmake_configure_options`, etc.

### Via automatic discovery

SBT detects addon directories automatically:

- **Overlay ports**: `addon/vcpkg/overlay-ports/` is passed to vcpkg as `--overlay-ports=...`
- **Custom triplets**: `addon/vcpkg/triplets/` is scanned for `.cmake` files and passed as `--overlay-triplets=...`
- **Custom Makefile**: `addon/makefile/Makefile.custom` is included by the main Makefile if it exists

## vcpkg/config.py

Per-port cmake options and vcpkg compiler flags. This is where you handle library build quirks.

### Compiler flags

Injected into **all** vcpkg port compilations via the overlay triplet:

```python
vcpkg_cflags = [
    "-Wno-error=discarded-qualifiers",       # Fix lib X with GCC 14
]
vcpkg_cxxflags = []
```

### Per-port cmake options

Base config (restrictive by default, safe for cross-compilation):

```python
vcpkg_cmake_configure_options = {
    "sdl3": ["-DSDL_X11=OFF", "-DSDL_WAYLAND=OFF"],
    "glfw3": ["-DGLFW_BUILD_X11=OFF"],
}
```

Platform overrides (re-enable features):

```python
# Native linux: empty list removes restrictions
vcpkg_cmake_configure_options_linux = {
    "sdl3": [],
    "glfw3": [],
}

# Cross-linux: selective re-enable (X11/Wayland from vcpkg)
vcpkg_cmake_configure_options_cross_linux = {
    "sdl3": ["-DSDL_IBUS=OFF", "-DSDL_JACK=OFF"],
    "glfw3": [],
}

# Windows (mingw)
vcpkg_cmake_configure_options_windows = {
    "curl": ["-DHAVE_IOCTLSOCKET_FIONBIO=ON"],
}

# Emscripten
vcpkg_cmake_configure_options_web = {
    "sdl3": ["-DSDL_OPENGLES=ON"],
}
```

Naming convention for variants:
- `vcpkg_cmake_configure_options` — base (always applied)
- `vcpkg_cmake_configure_options_{platform}` — platform-specific (native only)
- `vcpkg_cmake_configure_options_cross_{platform}` — cross-compilation for that platform

### Default features control

```python
vcpkg_no_default_features = [
    "dbus",    # systemd default breaks on musl
    "libusb",  # udev default needs system headers
]
```

These libs get `"default-features": false` in the vcpkg manifest during cross-builds.

### Cross-linux display packages

Extra packages to build from source when cross-compiling for linux (X11/Wayland):

```python
vcpkg_cross_linux_extlibs = {
    "libx11": "",
    "libxext": "",
    "libxkbcommon": "",
    "wayland": "",
    "wayland-protocols": "",
}

vcpkg_cross_linux_extlibs_features = {
    "wayland": ["force-build"],
    "wayland-protocols": ["force-build"],
}
```

These are installed in a 2-phase process for cross-linux builds (see [cross-compilation.md](cross-compilation.md)).

## vcpkg/overlay-ports/

Patched vcpkg ports that override the official ones. Each subdirectory is a complete vcpkg port:

```
addon/vcpkg/overlay-ports/
└── libxcursor/
    ├── portfile.cmake
    └── vcpkg.json
```

Only `libxcursor` stays a manual overlay (no stock port in vcpkg). All other port edits
(dbus, libwebsockets, libcap, ncurses, python3, lua) are declared via `vcpkg_ports` below.

Passed to vcpkg as `--overlay-ports=site_scons/addon/vcpkg/overlay-ports`. Typical reasons to patch:
- Remove a dependency that doesn't build on a target (e.g., dbus without systemd)
- Fix cross-compilation variables (e.g., libcap OBJCOPY)
- Fix dependency resolution bugs

A full manual overlay is rarely needed. For most port edits — adding/removing patches,
changing the manifest, splicing build options, pinning a SHA — prefer `vcpkg_ports` below,
which declares the edits in `app.py` and lets SBT generate the overlay.

## vcpkg_ports (declarative port overlays)

Declare per-port edits in `app.py` instead of hand-writing a manual overlay. SBT copies the
stock port from `.vcpkg/ports/<port>/` into a generated overlay
(`build/<target>/vcpkg/gen-overlay-ports/<port>/`), applies the declared edits, and passes the
generated dir as a second `--overlay-ports`.

```python
vcpkg_ports = {
    "dbus": {
        "remove_patches": ["session-socket-dir.diff"],
        "manifest": {"port-version": 2, "default-features": []},
        "recipe_patches": ["patches/dbus/recipe.patch"],
    },
    "libwebsockets": {
        "patches": ["patches/libwebsockets/mingw-pthreads.patch"],
        "manifest": {"version-semver": "4.5.2"},
        "recipe_patches": ["patches/libwebsockets/recipe.patch"],
    },
}
```

Per-port keys (all optional):
- `patches`: `[<path>, ...]` — patch files (rel to `addon/vcpkg/`) copied beside the portfile
  and **merged** into the source-extract call's `PATCHES` argument (canonical vcpkg mechanism;
  works for `vcpkg_from_github/gitlab/git`, `vcpkg_extract_source_archive[_ex]`). These patch
  the extracted **upstream source**.
- `remove_patches`: `[<name>, ...]` — stock patch basenames dropped from `PATCHES` (and the
  `.patch` file removed).
- `manifest`: `{<key>: <val>}` — shallow merge into the port's `vcpkg.json` (e.g.
  `default-features`, `port-version`, `version-semver`). Scalar-key only; structural changes
  (array-element removals) go in a `recipe_patch`.
- `files`: `{<src>: <dst>}` — whole files (src rel to `addon/vcpkg/`) copied into the generated
  port (local build inputs: wrapper `.cmake.in`, an extra `.patch`, `CONTROL`, …).
- `recipe_patches`: `[<path>, ...]` — `.patch` files (rel to `addon/vcpkg/`) applied with
  `git apply` to the **generated port dir** (`portfile.cmake` / `vcpkg.json` edits: SHA pin,
  option splice, guard change, block deletion, structural manifest change). Applied **last**.
  Distinct from `patches`, which patch the upstream source, not the port recipe.

Order of operations per port: `remove_patches` → `patches` → `manifest` → `files` →
`recipe_patches`.

Rules:
- A port may appear in `vcpkg_ports` **or** have a manual `overlay-ports/<port>/` — not both
  (SBT errors).
- A `patches` entry needs a source-extract call producing `SOURCE_PATH`; if absent, SBT errors
  (use a `recipe_patch` instead).
- A missing `recipe_patch` file, or one that fails to apply, errors loud.
- If the working-tree portfile differs from the pinned baseline, SBT warns (generated overlay
  copies the working tree).

## vcpkg/triplets/

Custom triplet `.cmake` files for targets not covered by vcpkg built-in or SBT:

```
addon/vcpkg/triplets/
└── my-custom-triplet.cmake
```

Passed to vcpkg as `--overlay-triplets=site_scons/addon/vcpkg/triplets`. SBT statically scans this directory to discover available triplets.

Priority order for triplet resolution:
1. **SBT custom** (`sbt/vcpkg/triplets/`)
2. **vcpkg built-in** (`.vcpkg/triplets/`)
3. **vcpkg community** (`.vcpkg/triplets/community/`)
4. **Addon custom** (`addon/vcpkg/triplets/`)
5. **Dynamic** (generated from `architectures.py` for musl/zig)

## makefile/Makefile.custom

Extra Make targets included by the main Makefile:

```makefile
# addon/makefile/Makefile.custom

.PHONY: my-custom-target
my-custom-target:
	@echo "Running custom target"
	# your commands here
```

## Creating a new addon file

### Adding a new include

1. Create your file in `addon/`:

```python
# addon/my_config.py
my_setting = "value"

def configure(app):
    # Called after all includes are merged
    # Access app.name, app.version, etc.
    pass
```

2. Register it in `app.py`:

```python
includes = [
    "addon/vcpkg/config.py",
    "addon/distribution.py",
    "addon/my_config.py",        # new
]
```

### Patching a port

1. Write the `.patch` under `addon/vcpkg/` (e.g. `addon/vcpkg/patches/<name>.patch`)
2. Add `vcpkg_ports = {"<port>": {"patches": ["patches/<name>.patch"]}}` to `app.py`
3. `make dep m=<module>` — SBT generates the overlay and merges the patch (see vcpkg_ports above)

### Adding a custom overlay port (structural)

Only when you must inject local build files or change build options:

1. Copy the port from `.vcpkg/ports/<name>/` to `addon/vcpkg/overlay-ports/<name>/`
2. Edit `portfile.cmake` or `vcpkg.json` as needed
3. vcpkg automatically picks it up via `--overlay-ports`

### Adding a custom triplet

1. Create `addon/vcpkg/triplets/<triplet-name>.cmake`
2. SBT discovers it automatically through filesystem scan
