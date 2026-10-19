# Modules Guide

## What is a module?

A module is a self-contained build unit (library, binary, tests, demos) with this layout:

```
mymodule/
├── scons.py                    # Build script (required)
├── include/project/mymodule/   # Public headers
├── src/                        # Source files
├── test/                       # Unit tests
│   └── main.cpp
└── demo/                       # Demo programs (optional)
    └── etc/                    # Demo resources (optional)
```

## Minimal scons.py

```python
Import('env')

lib = env.build_lib(Glob('src/*.cpp'))
test = env.build_test(Glob('test/*.cpp'), libs=[env.module_format_name()])

Return('lib')
```

`Return('lib')` is required — it returns the library node to the build system.

## Declaring a module

Modules are declared in `app.py`. A minimal module with no dependencies:

```python
modules = {
    "mymodule": {},
}
```

A module depending on others:

```python
modules = {
    "mymodule": {
        "depends": ['base', 'io'],
        "libs": ['pthread'],
    },
}
```

SBT auto-fills missing keys (`depends`, `libs`, `link`, `flags`) as empty lists.

## Module configuration keys

### Core keys

| Key | Type | Description |
|-----|------|-------------|
| `depends` | `list[str]` | Internal module dependencies (built before this module) |
| `libs` | `list[str]` | System/external libraries to link (`-l<name>`) |
| `flags` | `list[str]` | Compiler flags, C and C++ (`CPPFLAGS`) |
| `c-flags` | `list[str]` | C-only compiler flags (`CFLAGS`) |
| `cxx-flags` | `list[str]` | C++-only compiler flags (`CXXFLAGS`) |
| `defines` | `list[str]` | Preprocessor defines (`-D<name>`) |
| `link` | `list[str]` | Linker flags (`LINKFLAGS`) |
| `bin-link` | `list[str]` | Linker flags for binaries/tests/demos only (`BIN_LINKFLAGS`) |
| `extlibs` | `list[str]` | External library names (vcpkg), see [dependencies.md](dependencies.md) |

### Discovery keys

| Key | Type | Description |
|-----|------|-------------|
| `pkg-configs` | `list[str]` | pkg-config packages to query (native builds only) |
| `parse-configs` | `list[str]` | Shell commands for config tools (native builds only) |

Both are **skipped in cross-compilation** to avoid host header pollution. In cross builds, headers/libs come from vcpkg's `extlib/` directory instead.

```python
"device": {
    "parse-configs": ["pkg-config libusb-1.0 --cflags --libs"],
    # ^ only runs on native builds
    "cross-libs": ['usb-1.0'],
    # ^ used when cross-compiling (vcpkg provides the lib)
},
```

### Platform restriction

| Key | Type | Description |
|-----|------|-------------|
| `allow-platforms` | `list[str]` | Whitelist of platforms (`linux`, `windows`, `web`, `android`). Omit = all platforms. |
| `exclude-platforms` | `list[str]` | Drop the module when any build selector matches (for example `web`, `static`, `mode-release`, `gcc`, or `arm64`). |

```python
"bluetooth": {
    "allow-platforms": ["linux"],  # bluetooth only on linux
},
```

### Link mode restriction

| Key | Type | Description |
|-----|------|-------------|
| `allow-link-shared` | `bool` | Module dropped from static builds (`static=1`). |
| `allow-link-static` | `bool` | Module dropped from dynamic builds. |
| `<platform>-allow-link-shared` | `bool` | Platform-specific override of `allow-link-shared`. |
| `<platform>-allow-link-static` | `bool` | Platform-specific override of `allow-link-static`. |

```python
"gui": {
    # GUI pulls system-only dynamic libs (libGL/libGLEW) with no static
    # archive + dlopen GL loader: cannot link fully static
    "allow-link-shared": True,
},
```

### Module-level env defaults

| Key | Type | Description |
|-----|------|-------------|
| `env` | `dict[str, any]` | Default values for CLI/env variables |

```python
"ui": {
    "env": {
        "x11": 0,      # default off, enable with x11=1
        "wayland": 0,   # default off, enable with wayland=1
    },
},
```

These values are set in `os.environ` at load time. The module's `scons.py` reads them with `env.is_opt("x11")`.

### Inheritance keys

| Key | Type | Description |
|-----|------|-------------|
| `export-libs` | `list[str]` | Export module libraries to dependent modules |
| `export-defines` | `list[str]` | Export preprocessor defines to dependent modules |
| `export-flags` | `list[str]` | Export compiler flags to dependent modules |
| `export-all-libs` | `bool` | Export all active direct `libs` and variant `*-libs` of the module |
| `export-all-defines` | `bool` | Export all active direct `defines` and variant `*-defines` of the module |
| `export-all-flags` | `bool` | Export all active direct `flags` and variant `*-flags` of the module |
| `export-all-link` | `bool` | Export all active direct `link` and variant `*-link` of the module |
| `export-<variant>-libs` | `list[str]` | Export variant-specific libraries such as `export-windows-libs` |
| `export-<variant>-defines` | `list[str]` | Export variant-specific defines |
| `export-<variant>-flags` | `list[str]` | Export variant-specific compiler flags such as `export-web-flags` |
| `inherit-depends-defines` | `bool` | Inherit CPPDEFINES from dependencies |
| `inherit-depends-links` | `bool` | Inherit LINKFLAGS from dependencies |
| `inherit-depends-libs` | `bool` | Inherit system libraries from dependencies |
| `inherit-depends-flags` | `bool` | Inherit CPPFLAGS from dependencies |
| `inherit-depends-generated-libs` | `bool` | Inherit generated library names from dependencies (default: `True`) |

## Project build configuration

`modules_path` selects the project-relative directory containing module sources; it defaults to the project root. The loader checks that the configured directory exists.

`architectures` (or `extra_machines`) can add machine entries to the built-in architecture table. The same entries can be registered by calling `architectures.register_machines({...})` from project configuration.

```python
modules_path = "src"

architectures = {
    "custom64": {
        "gcc": {"gnu": "custom64-linux-gnu-"},
        "vcpkg": "custom64",
        "meson": {"cpu_family": "custom64", "cpu": "custom64", "endian": "little"},
    },
}
```

After a non-dry build, SBT calls optional `on_build_success(build_modules, builder)` or `on_build_fail(build_modules, builder)` hooks from `app.py`.

### Android keys

| Key | Type | Description |
|-----|------|-------------|
| `android-permissions` | `list[str]` | Android manifest permissions |

## Platform/compiler variant keys

Any core key can be prefixed with a variant selector:

```
{variant}-{key}
```

Where `{variant}` is one or a combination of:

| Variant | Values | Example |
|---------|--------|---------|
| Platform | `linux`, `windows`, `web`, `android` | `linux-libs` |
| Compiler | `gcc`, `clang`, `mingw`, `em`, `ndk`, `zig` | `em-flags` |
| Lib type | `static`, `shared` | `static-defines` |
| Mode | `mode-debug`, `mode-fast`, `mode-size`, `mode-release` | `mode-debug-flags` |
| Libc | `gnu`, `musl` | `musl-flags` |
| Cross | `native`, `cross` | `native-libs`, `cross-libs` |

**Combinations** — two variants can be combined:

```python
"linux-static-libs": ['z'],          # linux + static
"linux-native-libs": ['udev'],       # linux + native build
"linux-cross-libs": ['usb-1.0'],     # linux + cross build
"mode-debug-flags": ['-Og'],         # debug mode (bare "debug-flags" WARNS)
"mode-fast-static-flags": ['-O2'],   # fast mode + static
```

Modes are project-defined (`app.modes`) and always `mode-` prefixed. SBT generates each base selector plus its `{selector}-{libtype}` pairing and the `{platform}-cross`/`{platform}-native` pairs; it iterates over all of them at build time.

### Example: full module

```python
"client": {
    "depends": ['io'],
    "extlibs": ['libwebsockets', 'curl', 'zlib', 'libuv'],
    "linux-extlibs": ["libcap"],
    "linux-libs": ["websockets", "curl", "z", "uv", "cap", "ssl", "crypto"],
    # static build: full ordered closure, ssl/crypto last (GNU ld order)
    "windows-static-libs": [
        'websockets_static', 'curl', 'uv', 'zlib',
        'winmm', 'iphlpapi', 'userenv', 'advapi32', 'user32', 'dbghelp',
        'ole32', 'uuid', 'ssl', 'crypto', 'crypt32', 'bcrypt',
    ],
    # dynamic build (default): import libs only
    "windows-shared-libs": ['websockets', 'curl'],
},
```

## Environment methods available in scons.py

### Build methods

| Method | Description |
|--------|-------------|
| `env.build_lib(sources, name=, static=, static_libs=[])` | Build shared/static library. Returns lib node. `static_libs=[...]` whole-archives static-only vcpkg `.a` (owning a process-global) into the module DLL on the windows dynamic build — PE has no symbol interposition. |
| `env.build_bin(sources, name=, libs=[], static_libs=)` | Build executable binary. `static_libs=True\|[...]` wraps libs in `-Bstatic/-Bdynamic`. |
| `env.build_test(sources, libs=[])` | Build test binary (only if `test=1`) |
| `env.build_demo(source, name=, libs=[], android_dir=None)` | Build demo (only if `demo=1`) |
| `env.build_demos(sources)` | Build multiple demos (one per source file) |
| `env.build_cpp_modules(sources, module_name=, imports=[])` | Build C++20 module interfaces and register them for later imports |
| `env.export_test(includes=[], resources=[])` | Register include paths for dependent test builds; when `test=1`, copy resources into `EXPORT_PATH/<module>/`. |

When a target imports named modules, pass them explicitly with `cpp_modules=[...]`:

```python
cpp_modules = env.build_cpp_modules('test/modules/TestGreeting.cppm')

env.build_test(
    Glob('test/*.cpp') + cpp_modules,
    libs=[env.module_format_name()],
    cpp_modules=['mymodule.test.greeting'],
)
```

This does three things:

1. enables the active compiler backend for module consumption,
2. wires SCons dependencies so imported interfaces are compiled first,
3. links the interface object together with the importer target.

### Compiler support for `build_cpp_modules`

Current SBT support matrix:

| Compiler | Support | Notes |
|----------|---------|-------|
| GCC 15+ native Linux | supported | uses `gcm.cache/` + GCC mapper file |
| Clang 21+ native Linux | supported | uses one-phase `.pcm` emission via `-fmodule-output=` and consumption through `-fprebuilt-module-path=` |
| Cross builds / mingw / emscripten / Android NDK | unsupported | backend intentionally disabled for now |

The public SBT API is the same for GCC and Clang. The backend is selected automatically from the active compiler.

### Module info

| Method | Returns |
|--------|---------|
| `env.module_name()` | Module name: `"app"` |
| `env.module_format_name()` | Formatted lib name: `"project_app"` |
| `env.module_conf()` | Module config dict from app.py |
| `env.module_dir()` | Absolute path to module directory |
| `env.modules_to_build()` | List of all modules being built |
| `env.builder()` | Access to builder object (platform, paths, etc.) |
| `env.app()` | Access to app.py module |

### Configuration queries

| Method | Returns |
|--------|---------|
| `env.is_opt(name)` | `True` if CLI arg / env var is `"1"` or `"true"` |
| `env.get_opt(name, default="")` | Get CLI arg / env var value |

### Dynamic library discovery

| Method | Description |
|--------|-------------|
| `env.pkg_config(name)` | Run pkg-config for a package (native only) |
| `env.parse_config(cmd)` | Parse config tool output (native only) |

### File operations

| Method | Description |
|--------|-------------|
| `env.copy_into_build(src, dst)` | Copy files into build directory |
| `env.git_clone(url, branch, dest)` | Clone a git repo |
| `env.build_replace(patterns, replacements)` | Replace strings in build files |
| `env.file_replace(path, replacements)` | Replace strings in a file |
| `env.find_in_file(path, string)` | Search for string in file |
| `env.file_basename(path)` | Extract filename without extension |
| `env.filter_files(files, filter_list)` | Filter out files by name |
| `env.create_module_env(**kwargs)` | Create a sub-environment from current module config |

### Builder object

```python
builder = env.builder()

builder.build_platform     # "linux", "windows", "web", "android"
builder.build_machine      # "x86_64", "arm64", "arm32", ...
builder.build_compiler     # "gcc", "clang", "mingw", "em", "ndk", "zig"
builder.build_mode         # "debug", "fast", "size", "release"
builder.build_static_libs  # True/False
builder.libc               # "gnu", "musl"
builder.build_tests        # True/False
builder.build_demo         # True/False
builder.build_path         # Full build path
builder.build_lib_path     # lib/ directory
builder.build_bin_path     # bin/ directory

builder.is_cross_building()   # True if host != target
builder.get_gnu_triplet()     # e.g. "aarch64-linux-gnu"
```

## scons.py patterns

### Platform-conditional sources

```python
Import('env')

builder = env.builder()

srcs = ["src/Common.cpp"]

if builder.build_platform == "android":
    srcs.append("src/AndroidBackend.cpp")
elif builder.build_platform == "windows":
    srcs.append("src/WindowsBackend.cpp")
elif builder.build_platform != "web":
    srcs.append("src/LinuxBackend.cpp")

lib = env.build_lib(srcs)
Return('lib')
```

### Optional features via env vars

```python
Import('env')

if env.is_opt("x11"):
    env.Append(LIBS=["X11"])
    env.Append(CPPDEFINES=["COMPILE_WITH_X11"])

lib = env.build_lib(Glob('src/*.cpp'))
Return('lib')
```

### Multiple demos from a directory

```python
Import('env')

lib = env.build_lib(Glob('src/*.cpp'))

for src in Glob('demo/*.cpp'):
    name = env.file_basename(src)
    env.build_demo(src, name=name, libs=[env.module_format_name()])

test = env.build_test(Glob('test/*.cpp'), libs=[env.module_format_name()])
Return('lib')
```

### Conditional compilation by modules present

```python
Import('env')

modules = env.modules_to_build()

srcs = [Dir("src").File("Base.cpp")]
tests = [Dir("test").File("main.cpp")]

for module in modules:
    if module == "mymodule":
        continue
    srcs += Glob(f"src/{module}/*.cpp")
    tests += Glob(f"test/{module}/*.cpp")

lib = env.build_lib(srcs)
test = env.build_test(tests, libs=[env.module_format_name()])
Return('lib')
```

Such a module is **adaptive**: it binds/compiles a sibling module only when that sibling is
in the build. Its own `depends` must therefore stay minimal — anything listed in `depends` is
*forced* into every build, which defeats the adaptation. Declare the optional siblings in
`conditional-depends` instead: they are linked only if they are already in the build for some
other reason.

### `m=` vs `fmod=`

`m=` (alias `modules=`) selects **what to build**, and for `make test` it *also* selects
**whose tests are run**. `fmod=` only **adds modules to the build** — their test suites are
not run.

This is what lets you compile a module purely so an adaptive module can bind it:

```bash
make test m=script              # build script (lean), run script's tests
make test m=script fmod=client  # ALSO build client so script binds it - but do NOT run client's tests
make test m=script fmod=all     # build everything, still only run script's tests
```

Without `fmod`, `make test m=script,client` would run client's entire test suite too.

## Conditional modules

Modules that are only built when explicitly requested.

> `conditional_modules` must be defined in `app.py` even if you have none — set
> `conditional_modules = {}`. The `modules=`/`m=` build filter reads it unconditionally.

```python
# app.py
conditional_modules = {
    "script": {
        "conditional-env": "script",        # activated by script=1
        "depends": ['base', 'io'],
        "conditional-depends": ['app'],     # depends on app only if app is being built
        "extlibs": ['lua', 'luabridge3'],
        "libs": ["lua"],
    },
}
```

| Key | Description |
|-----|-------------|
| `conditional-env` | Env var name that activates this module when set to `1` |
| `conditional-depends` | Dependencies that apply only if those modules are in the build |

### Activation

```bash
# Via env var
make script=1

# Via explicit module selection (also works)
make m=script
```

When built via `m=script`, the module's full dependency tree (`base`, `io`) is resolved automatically.

Dependencies are resolved recursively: if `client` depends on `io` which depends on `base`,
`make m=client` builds `base`, `io`, `client` in dependency order. Modules are sorted by
dependency depth and built in order.

## Build output

```
build/<machine>-<platform>-<libc>/<compiler>-<version>/<mode>/<static|dynamic>/
├── lib/           # Libraries (.so/.a/.dll)
├── bin/           # Binaries
├── demo/          # Demo executables
├── include/       # Copied public headers
├── test/bin/      # Test binaries
├── export/        # Test resources grouped by provider module
├── obj/           # Intermediate object files
│   └── mymodule/
├── etc/           # Copied config files
├── share/         # Copied share files
└── extlib/        # Symlink → vcpkg installed packages
```

`build/last` symlinks to the most recent build.

Resources in `etc/`, `include/` and `share/` are copied incrementally: after deleting a source file, run `make clean` to drop its stale copy from `build/`.

## CLI reference

```bash
make                           # Build all modules
make m=base,app                # Build specific modules
make test=1                    # Build + compile tests
make demo=1                    # Build demos
make mode=debug                # Debug build
make mode=release              # Release build
make static=1                  # Static libraries
make v=1                       # Verbose output
make compiler=clang            # Use clang
make def=MY_DEFINE=1           # Add preprocessor define
```

Every build ends with `module build times`: per module, the span from its first compile
to its last link (`up to date` when nothing ran, `not finished` when the build stopped
first). With `-j`, module spans overlap; the total `build succeeded (took ...)` also
counts configuration time.

#### Make targets

| Target | Purpose |
|--------|---------|
| `info`, `conf [m=modules]` | Print active build settings or selected module configuration. |
| `dump`, `jdump` | Print the `app.py` configuration as text or JSON. |
| `path`, `targets` | Print the build path or list Make targets. |
| `venv`, `setup` | Create `.venv/` or install SCons (>= 4.11) into it. |
| `build_debug`, `build_dry` | Run SCons with diagnostics or as a dry run. |
| `mod <module> [m=modules]` | Build the requested module and any additional modules from `m=` with their dependencies. |
| `serve_bin`, `serve_demo` | Serve WebAssembly binaries or demos on `PORT` (default `8000`). |
| `clean`, `clean_dep`, `clean_dist`, `clean_cache` | Remove the current build, dependencies, distribution, or cache. |
| `cclean` | Remove current configuration outputs and the SCons cache. |
| `clean_build` | Remove the entire `build/` tree, including all configurations and build-local dependency state. |
| `fclean` | Remove build outputs, distributions, dependency installs, caches, and `.sconsign.dblite`. |
| `dep licenses` | Print installed vcpkg port licenses and write the JSON report. |
| `dep sbom` | Write the CycloneDX SBOM of installed vcpkg ports to `security/sbom.cdx.json`. |

The `scripts/cli_helper.py` command-line helper also supports `keys`, `dump`, `compiler`,
`platform`, `machine`, `mode`, `termux`, `path`, `modules_path`, `static`, `triplet`,
`runner`, and `runner_env`. Its `conf`, `dump-config [--json]`, and `makevars` commands are
used by Make to resolve configuration and paths.

#### Build options reference

Options are passed as `make <option>=<value>` (environment variables work too). Cross-compilation options (`machine=`, `platform=`, `libc=`, `compiler=`) are detailed in [cross-compilation.md](cross-compilation.md), `test=`/`demo=` targets in the [Testing](#testing) section below.

Values are checked before anything runs (`make` stops with `invalid option values: ...`): flags (`static`, `asan`, `test`, `demo`, `brief`, ...) accept `0`, `1`, `true` or `false`; `j`, `jtest` and `repeat` an integer >= 1; `SBT_LOCK_TIMEOUT` an integer >= 0; `PORT` 1-65535; `compiler`, `platform`, `machine`, `libc` and `dist` the values of [cross-compilation.md](cross-compilation.md) and of this table. Empty means unset.

| Option | Default | Effect |
|--------|---------|--------|
| `m=` / `modules=` | all | Build only the listed modules (plus their dependencies). See [`m=` vs `fmod=`](#m-vs-fmod). |
| `fmod=` | | Build only the listed modules, **without** their dependencies. |
| `mode=` | `default` | Build variant (`default`, `debug`, `release`, or project-defined modes). |
| `static=1` | off | Build static libraries (`.a`) instead of shared. |
| `combined=1` | off | Also produce a **single final library** `<app.name>` in `build/<...>/lib/` containing the objects of **all** built modules. Static (`.a`) when `static=1`, shared otherwise. Module-internal libs are absorbed; external libs (vcpkg/system) remain link-time dependencies for the consumer. Handy for distributing a one-file SDK. |
| `test=1` / `t=1` | off | Build test binaries. |
| `demo=1` | off | Build demo executables. |
| `compile_commands=1` | **on** | Generate `compile_commands.json` (clangd) in the build directory. `compile_commands=0` to disable. |
| `nocache=1` | off | Disable ccache for this build. |
| `compile_time=1` | off | Report per compile unit at the end of the build: clang wall time and top headers (inclusive, from `-ftime-trace`), line count after preprocessing. Needs `compile_commands=1`. Adds `-ftime-trace` (clang, ndk, emscripten, filc) or `-ftime-report` (gcc, mingw, zig; output inline, no per-unit time). Toggling it rebuilds every unit once. ccache hits report no time. |
| `v=1` / `verbose=1` | off | Verbose output. |
| `cpu=` | `$CPU` | Target CPU for `-march=`/`-mcpu=` (e.g. `cortex-a72`, `x86-64-v3`). |
| `triplet=` | auto | Override the vcpkg triplet used by `make dep`. |
| `cross_sysroot=` | | Path to a cross sysroot; sets `PKG_CONFIG_SYSROOT_DIR` and pkg-config search paths for cross builds. |
| `with-system-packages=<pm>` | off | `make dep`: skip extlibs mapped in `<pm>_packages`; supported values are `apt`, `pacman`, `apk`, and `yum`. |
| `fgit=1` | off | `make dep`: force re-clone of git dependencies. |
| `SBT_LOCK_TIMEOUT=seconds` | `7200` | Wait up to this many seconds for the lock of the build variant (`<build_path>/.sbt.lock`; other machine, platform, libc, compiler, mode or linkage run in parallel); `0` disables it. Read-only goals do not take the lock. |
| `j=number` | logical cores - 1 | SCons parallel jobs. |
| `repeat=number` | | Repeat each test the requested number of times. |
| `jtest=number` | off | Run each test binary as `number` concurrent gtest shards (`GTEST_TOTAL_SHARDS` / `GTEST_SHARD_INDEX`, like `ctest -j`); modules stay sequential. Output is shown per module once all its shards finished. Ignored under gdb and on web/android. Tests sharing a fixed port or file must tolerate concurrent runs. |
| `brief=1` | off | Keep passing test output in logs and show failures in the console. |
| `env=path` | `env.py` | Load the named environment module instead of the default project `env.py`. |
| `dist=type` | | Select a distribution type (`tar`, `apt`, `pacman`, or `docker`). |
| `pkgdep=manager` | | Select the system package manager for `make pkgdep` (or `auto`). |
| `asan=1`, `ubsan=1`, ... | off | Sanitizers — see below. |
| `coverage=1` | off | gcovr coverage instrumentation — see below. |
| `docker_builder_image=...` | `debian:trixie-slim` | Docker distribution builder image. |
| `docker_runtime_image=...` | `debian:trixie-slim` | Docker distribution runtime image. |
| `docker_build_local=1` | off | Build the Docker image from the local project tree. |
| `PORT=number` | `8000` | Port used by `serve_bin` and `serve_demo`. |
| `ANDROID_API=number` | `24` | Android NDK target API level. |
| `ANDROID_NDK_PATH=path` | | Android NDK root. |
| `ANDROID_NDK_HOST_TAG=tag` | detected | Override the NDK prebuilt host tag. |
| `ANDROID_SDK_PATH=path` | | Android SDK root. |
| `JAVA_HOME=path` | | JDK root used for Android builds. |
| `FILC_PATH=path` | | Fil-C toolchain root. |

#### Sanitizers (build flags)

| Flag | Sanitizer | Compiler | Notes |
|------|-----------|----------|-------|
| `asan=1` | AddressSanitizer (`-fsanitize=address`) | gcc, clang | Detects buffer overflows, use-after-free, heap/stack/global overflows. Includes LSan on Linux. |
| `ubsan=1` | UndefinedBehaviorSanitizer (`-fsanitize=undefined`) | gcc, clang | Signed overflow, null deref, misaligned access. Mutually exclusive with other primary sanitizers. |
| `tsan=1` | ThreadSanitizer (`-fsanitize=thread`) | gcc, clang | Data races and deadlocks. Mutually exclusive with ASan/MSan/LSan/HWASan. |
| `lsan=1` | LeakSanitizer (`-fsanitize=leak`) | gcc, clang | Standalone memory leak detection (integrated in ASan by default on Linux). |
| `msan=1` | MemorySanitizer (`-fsanitize=memory`) | **clang only** | Reads from uninitialized memory. Mutually exclusive with other primary sanitizers. |
| `hwasan=1` | HWAddressSanitizer (`-fsanitize=hwaddress`) | gcc, clang | Like ASan but via ARM MTE hardware tagging. **arm64 only**. |

Primary sanitizers (asan, tsan, msan, hwasan, lsan) are **mutually exclusive** — enable only one at a time. UBSan and coverage can be combined with them freely.

#### Code coverage (gcovr / Cobertura)

```bash
make coverage=1                # Build with --coverage instrumentation
make covtest m=base            # Build + run tests + emit coverage.xml (Cobertura) + coverage.html
```

Requires `gcovr` (`pip install gcovr`). Output files are written to `<build_path>/coverage/coverage.xml`, `<build_path>/coverage/index.html` and `<build_path>/coverage/summary.json` (gcovr `--json-summary`: line, branch and function totals and percents).

Coverage gates, in `app.py` (unset = no gate):

```python
gcov_fail_under = 80          # minimum line coverage percent (gcovr --fail-under-line)
gcov_fail_under_branch = 60   # minimum branch coverage percent (gcovr --fail-under-branch)
```

Below a threshold, `make covtest` exits non-zero after writing every report. When
`GITHUB_STEP_SUMMARY` is set (GitHub Actions), a coverage table is appended to it.

#### Static analysis (cppcheck)

```bash
make cppcheck                  # Analyse all modules
make cppcheck m=base,app       # Analyse specific modules
make cppcheck base             # Short form (positional arg)
```

Requires `cppcheck` (install via package manager). Default checks: `--enable=warning,style,performance,portability`, `--inline-suppr`, `--error-exitcode=1`. No C/C++ standard or language is forced — cppcheck picks the language from file extensions and its own default standard, so modules written for older standards (or plain C) are analysed correctly.

Configuration lives in `app.py`, in two layers with the same keys: a top-level `cppcheck` dict for the whole project, and `cppcheck-*` keys in a module's conf for per-subproject overrides. Module keys win over global ones; `enable` replaces the check set at each layer, list keys accumulate, and raw `args` are appended last so they can override anything (cppcheck keeps the last occurrence of value flags like `--std`, `--language`, `--platform`, `--error-exitcode`, `-j`).

```python
cppcheck = {
    "std":        "c++17",     # --std= (none by default)
    "language":   "c++",       # --language= (none by default)
    "enable":     ["all"],     # replaces the default check set
    "suppresses": ["uninitvar"],
    "defines":    ["FOO=1"],   # -D prefix optional
    "undefines":  ["BAR"],     # -U prefix optional
    "includes":   ["/usr/include/python3.12"],
    "args":       ["--addon=misra;misc.config"],  # verbatim, final override
}

modules = {
    "my-module": {
        "cppcheck-std": "c++23",          # per-module override of "std"
        "cppcheck-suppresses": ["unusedFunction"],
        "cppcheck-skip": False,           # True excludes the module entirely
    },
}
```

`unusedFunction` and `missingInclude` warnings are suppressed by default. Reports land in `<build_path>/cppcheck/<module>/` (`report.xml`, `stdout.txt`, `html/` when `cppcheck-htmlreport` is installed) plus a merged errors-only `<build_path>/cppcheck/errors.xml` and `<build_path>/cppcheck/summary.json` (`{ "modules": { <module>: { "errors", "issues", "rc", "report" } }, "errors", "issues", "threshold", "status" }`; `errors` counts `severity="error"` findings, `issues` every finding).

By default `make cppcheck` fails on any finding (`--error-exitcode=1`). To gate on errors only:

```python
cppcheck_fail_under = 0   # max severity="error" findings tolerated; warnings/style no longer fail
```

When `GITHUB_STEP_SUMMARY` is set (GitHub Actions), a per-module table is appended to it.

### Testing

```bash
make test m=app                     # Build + run tests
make itest                          # Non-interactive tests
make test m=script fmod=client      # Build client too, but run ONLY script's tests
make test m=script fmod=all         # Build every module, run ONLY script's tests
make valtest                        # Tests with valgrind
make lvaltest                       # Tests with valgrind leak checking
make ttest                          # Tests with strace
make asantest / make iasantest      # Tests with ASan (+ non-interactive)
make ubsantest / make iubsantest    # Tests with UBSan
make tsantest / make itsantest      # Tests with TSan
make lsantest / make ilsantest      # Tests with LSan (standalone)
make msantest / make imsantest      # Tests with MSan (clang only)
make hwasantest / make ihwasantest  # Tests with HWASan (arm64 only)
make covtest                        # Tests + Cobertura coverage report
make perftest m=app                   # perf record each test binary + the slowest tests
make iperftest                       # Same, non-interactive
make test repeat=3 brief=1           # Repeat tests and keep passing output in logs
make test jtest=8                    # Run each test binary as 8 concurrent shards
```

#### What the tests get (self-contained run environment)

`make test` regenerates `<build_path>/test/.env` from the build description before each
run; `execute_tests.sh` sources it and runs each module's test binary from that module's
own source directory (so relative fixture paths resolve), with logs per module under
`<build_path>/test/logs/<module>/`.

The default test profile is `gtest`, selected with `TEST_PROFILE`; profiles live in
`makefile/scripts/tests/profiles/`. `repeat=N` substitutes `N` into the profile's repeat
flags, `brief=1` enables its brief-output flags, and `jtest=N` exports the profile's
`TEST_SHARD_ENV` (`@TOTAL@` = N, `@INDEX@` = 0..N-1) to N concurrent runs of each binary; a
profile without it does not shard. Set `TEST_PROFILE_DIR` to use a
different profile directory.

The `.env` exports, in order (later wins — a project `app.generate_test_env` / addon can
override any engine value):

1. **Engine paths and Python**: `APP_NAME`, `PROJECT_ROOT_PATH`, `MODULES_PATH`, `BUILD_PATH`,
   `LIB_PATH`, `BIN_PATH`, `ETC_PATH`, `SHARE_PATH`, `EXTLIB_PATH`, `EXTLIB_LIB_PATH`,
   `TEST_PATH`, `TEST_BIN_PATH`, `EXPORT_PATH`, `TEST_RUNNER`, `TEST_BIN_EXT`, `PYTHON_BIN`
   (the interpreter used for the test run).
2. **Engine platform facts**: `SBT_PLATFORM`, `SBT_MACHINE`, `SBT_LIBC`, `SBT_MODE`,
   `SBT_COMPILER`, `SBT_TRIPLET`, `SBT_LIBS_TYPE`, `SBT_CROSS` (`1`/`0`) — what the test
   process would otherwise have to guess from `uname`.
3. **App/addon test env**: whatever `app.generate_test_env(builder)` returns, then
   `TEST_RUN_FLAGS`-style overrides from `app.generate_test_command(builder)`.

The same facts are available to Make as `$(PLATFORM)`, `$(MACHINE)`, `$(LIBC)`,
`$(COMPILE_MODE)`, `$(COMPILER)`, `$(GNU_TRIPLET)`, `$(CROSS)`.

#### Machine-readable reports

Each run ends with a `TEST RESULTS` recap, printed after the failure details: one line per
module (tests, failures, duration) followed by its `FAILED` and `SKIPPED` tests with their
duration, then the totals and the lists of failed and skipped tests (colored on a terminal only).
`v=1` / `verbose=1` also lists the passed tests (`OK`). It is read from the gtest
XML reports, so it needs them (see `TEST_REPORT_FLAGS` below); a module without a report
shows its exit code. With `repeat=N`, gtest reports the last iteration only.

Each run also writes, even when tests fail:

- `<build_path>/test/reports/<app>_<module>.xml` — one gtest XML per module
  (`--gtest_output=xml:$REPORT_DIR/`, the engine default assigned through
  `TEST_REPORT_FLAGS`; set it empty to disable or to another flag — from the env, an
  app/addon `.env` export, or a custom profile — to change it). `test_module_reports =
  False` in `app.py` deletes them once merged.
- `<build_path>/test/report.xml` — all module reports merged into one JUnit-style
  `<testsuites>` (suites prefixed with `<module>.`), for CI test-report viewers.
- `<build_path>/test/summary.json` — `{ "app", "status", "report", "tests": { "total",
  "passed", "failed", "skipped", "time" }, "failed_tests": [ { "module", "test" } ],
  "skipped_tests": [ { "module", "test" } ], "modules": { <module>: { "exit_code", "status", "report", "log", "tests",
  "failed_tests" } } }`. `tests` is `null` for a module without a report. Post-process it
  (upload, gate, badge) from an [addon](addon.md) `addon/makefile/addon.mk` target.

When `GITHUB_STEP_SUMMARY` is set (GitHub Actions), a markdown table of modules and the
failed and skipped tests is appended to it.

#### Profiling the tests (perf)

`make perftest` (`iperftest` for the non-interactive variant) runs the tests like `make test`
with every test binary under `perf record` (`--call-graph dwarf` at 499 Hz, user space only,
so it works with `kernel.perf_event_paranoid=2`) and lists the 10 slowest tests in the recap
and as `slowest` in `summary.json`. Per module it writes, in `<build_path>/test/reports/perf/`:

- `<module>.data` — the raw recording, for `perf report -i` / `perf annotate` / `perf script`.
- `<module>.perf.txt` — `perf report --stdio` text, symbols above 1%.

`make perftest` empties `perf/` before recording; the other test goals leave it alone.

Needs `perf` (not installed by `make dep`). An optimized build is advised
(`mode=release`): a `-O0` profile is misleading.

With `jtest=N` each shard is recorded on its own (`<module>.<shard>.data` / `.perf.txt`,
`perf` cannot merge them) and test durations include the contention between shards:
use `jtest=1` for numbers to compare.

The recorded process starts with default signal dispositions and an empty signal mask (`perf`
blocks `SIGWINCH` and ignores `SIGUSR2` in its workload, which breaks tests of signal handling).

Under a runner (wine, qemu-user, node) `perf` would profile the emulator, not the test:
the profile is skipped with a warning and only the timings stay. A web build has no timings
unless the gtest XML reaches the host disk.

`make test ls` lists the tests of each module and exits non-zero when no test binary was
built.
