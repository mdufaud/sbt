# Precompiled headers (PCH)

A dedicated module compiles a header once; every module that lists it in its
own `depends` consumes it. Nothing is inherited implicitly.

## Usage

The header module's `scons.py` compiles the anchor header:

```python
env.build_header('src/pch.hpp')
```

The anchor lives in the module's `src/` (a build input, not part of the public
api) and should hold only stable, heavy headers — std and extlibs. Never put
the project's own headers in it: a PCH rebuild invalidates every consuming
object, so any header edit would rebuild the whole tree.

```cpp
// src/pch.hpp
#include <string>
#include <vector>
#include <fmt/core.h>
```

A consumer lists the header module in `depends`:

```python
"app": {"depends": ["std", "base"]},   # "std" owns env.build_header(...)
```

The header module produces no library. Only a **direct** `depends` entry
consumes the header: a module depending on `app` does not receive it and must
list `std` itself. A module that must not use the header (feature-macro hostile
dependency trees, e.g. python's pyconfig.h redefining glibc feature macros)
simply does not list it. A module can list one header module at most.

A module that keeps the header module in `depends` can skip the header with the
`pch` conf key, on every build or on some selectors only:

```python
"gui": {
    "depends": ["std", "base"],
    # android-only define: the flags differ from the header module's there
    "android-defines": ["GUI_GLES3"],
    "android-pch": False,
},
```

`pch` defaults to `True`. Its selector forms (`android-pch`, `arm64-pch`,
`clang-pch`, `mode-release-pch`, ...) are resolved like other selector keys,
the last matching one wins.

No source change is needed: the compiler injects the header ahead of every C++
translation unit of the consumer (`-include`, or `-include-pch` with clang).
Plain `#include`s of the same headers in sources stay valid and become cheap.

## Test header

The same header module can compile a second header for test binaries, with the
test framework and other test-only headers on top of the main one:

```python
env.build_header('src/pch.hpp')
env.build_header('src/pch_test.hpp', test=True)
```

```cpp
// src/pch_test.hpp
#include "pch.hpp"
#include <gtest/gtest.h>
```

It is compiled only when tests are built (`test=1`), with the test app conf
applied (`test_flags`, ...). The test binaries of every consumer then preload it
instead of the main header; libraries, binaries and demos keep the main one.
Anchors are copied side by side under their own file names, so the test anchor
includes the main one by name. Without a test header, tests use the main one.

## Flag compatibility

The header is built with the header module's own flags. A consumer must compile
with the same C++ flags and defines, otherwise gcc silently drops the PCH and
clang hard-errors on macro conflicts. The module env is checked when it is
created, and again for tests and demos once their app-level flags are applied;
a difference stops the configure step and lists the diverging tokens.

Warnings (`-W*`) and include paths (`-I`, `-isystem`) are ignored by the check.
Defines, `-std`, `-f*` / `-m*` flags and the compiler itself must match. To
keep a module out, drop the header module from its `depends`, set `pch: False`
(or a selector form such as `android-pch: False`), or align its flags.

## Artifacts and rebuilds

Artifacts live under `build/<config>/pch/<module>/<compiler hash>/` (anchor copy
plus `.gch` or `.pch`); a compiler update selects a new directory.

The instance depends on every header the previous compile read, system headers
included, through the compiler depfile (`<artifact>.d`), so an extlib bump or a
libstdc++ update rebuilds it. clang records mtime and size of each included
file; the instance is created and consumed with `-fpch-validate-input-files-content`
so a header whose mtime was refreshed without a content change stays valid.

## Compiler support

gcc and clang (including cross gcc, llvm-mingw wrappers, ndk and filc) are
supported, classified by one `$CXX --version` probe — a `ccache` prefix is
stripped first since ccache answers `--version` itself. `zig` and `emscripten`
have no PCH support: `build_header` logs an info line and the build proceeds
without it.

C++ module interface units (`.cppm`) skip the PCH, and so do the sources of a
bin, test or demo passing `cpp_modules=` that hold an `import` line; the
target's other sources keep it. `-fmodules` and the PCH preload are not
combined on one translation unit.

ccache gets `CCACHE_SLOPPINESS=pch_defines,time_macros` appended on consumers.

## Migrating from `build_pch`

`env.build_pch(src)` is removed, together with the module conf key `pch: False`
and the implicit consumption by every module depending on the owner.

1. Move the anchor header and the `env.build_pch(...)` call into a dedicated
   module whose `scons.py` calls `env.build_header('src/pch.hpp')`. Give that
   module the `extlibs` its header includes.
2. List the new module in the `depends` of every module that consumed the
   header, direct dependents only.
3. Drop `pch: False` where it only meant "no implicit PCH": a module opts out by
   not listing the header module. `pch: False` is still accepted and now skips
   a header module the module lists in `depends` (see Usage).

A consumer whose C++ flags or defines differ from the header module's now fails
at configure time (see Flag compatibility) instead of silently losing the PCH.
