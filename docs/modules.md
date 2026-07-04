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
        "depends": ['util', 'core'],
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
"usb": {
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

```python
"bt": {
    "allow-platforms": ["linux"],  # bluetooth only on linux
},
```

### Link mode restriction

| Key | Type | Description |
|-----|------|-------------|
| `allow-link-shared` | `bool` | Module dropped from static builds (`static=1`). |
| `allow-link-static` | `bool` | Module dropped from dynamic builds. |

```python
"imgui": {
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
"sys": {
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
| `inherit-depends-flags` | `bool` | Inherit CPPFLAGS from dependencies |
| `inherit-depends-generated-libs` | `bool` | Inherit generated library names from dependencies (default: `True`) |

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
"http": {
    "depends": ['net'],
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
| `env.module_name()` | Module name: `"core"` |
| `env.module_format_name()` | Formatted lib name: `"project_core"` |
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

## Conditional modules

Modules that are only built when explicitly requested.

> `conditional_modules` must be defined in `app.py` even if you have none — set
> `conditional_modules = {}`. The `modules=`/`m=` build filter reads it unconditionally.

```python
# app.py
conditional_modules = {
    "lua": {
        "conditional-env": "lua",           # activated by lua=1
        "depends": ['util', 'sys'],
        "conditional-depends": ['core'],    # depends on core only if core is being built
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
make lua=1

# Via explicit module selection (also works)
make m=lua
```

When built via `m=lua`, the module's full dependency tree (`util`, `sys`) is resolved automatically.

## Module dependencies

Dependencies are resolved recursively. If `http` depends on `net` which depends on `util`:

```bash
make m=http
# → builds util, sys, net, http (in dependency order)
```

Modules are sorted by dependency depth and built in order.

## Build output

```
build/<machine>-<platform>-<libc>/<compiler>-<version>/<mode>/<static|dynamic>/
├── lib/           # Libraries (.so/.a/.dll)
├── bin/           # Binaries
├── demo/          # Demo executables
├── include/       # Copied public headers
├── test/bin/      # Test binaries
├── obj/           # Intermediate object files
│   └── mymodule/
├── etc/           # Copied config files
├── share/         # Copied share files
└── extlib/        # Symlink → vcpkg installed packages
```

`build/last` symlinks to the most recent build.

## CLI reference

```bash
make                           # Build all modules
make m=util,core               # Build specific modules
make test=1                    # Build + compile tests
make demo=1                    # Build demos
make mode=debug                # Debug build
make mode=release              # Release build
make static=1                  # Static libraries
make v=1                       # Verbose output
make compiler=clang            # Use clang
make def=MY_DEFINE=1           # Add preprocessor define
```

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
make covtest m=util            # Build + run tests + emit coverage.xml (Cobertura) + coverage.html
```

Requires `gcovr` (`pip install gcovr`). Output files are written to `<build_path>/coverage/coverage.xml` and `<build_path>/coverage/index.html`.

#### Static analysis (cppcheck)

```bash
make cppcheck                  # Analyse all modules
make cppcheck m=util,core      # Analyse specific modules
make cppcheck util             # Short form (positional arg)
```

Requires `cppcheck` (install via package manager). Checks are run with `--std=c++20`, `--enable=warning,style,performance,portability`, and `--error-exitcode=1`. `unusedFunction` and `missingInclude` warnings are suppressed by default.

### Testing

```bash
make test m=core                    # Build + run tests
make itest                          # Non-interactive tests
make valtest                        # Tests with valgrind
make lvaltest                       # Tests with valgrind leak checking
make tracetest                      # Tests with strace
make asantest / make iasantest      # Tests with ASan (+ non-interactive)
make ubsantest / make iubsantest    # Tests with UBSan
make tsantest / make itsantest      # Tests with TSan
make lsantest / make ilsantest      # Tests with LSan (standalone)
make msantest / make imsantest      # Tests with MSan (clang only)
make hwasantest / make ihwasantest  # Tests with HWASan (arm64 only)
make covtest                        # Tests + Cobertura coverage report
```
