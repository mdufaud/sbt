# Precompiled headers (PCH)

A module can own a precompiled header and every module depending on it
(transitively) consumes it automatically — consumers declare nothing.

## Usage

In the owner module's `scons.py`, before `build_lib`:

```python
env.build_pch('src/pch.hpp')
```

The anchor header lives in the module's `src/` (a build input, not part of the
public api). It should hold only stable, heavy headers — std and extlibs.
Never put the project's own headers in it: a PCH rebuild invalidates every
consuming object, so any header edit would rebuild the whole tree.

```cpp
// src/pch.hpp
#include <string>
#include <vector>
#include <fmt/core.h>
```

## Inheritance

`build_pch` records the owner module; the module env factory then preloads the
PCH into every module env that transitively depends on the owner, exactly like
an exported lib. Bins, tests and demos clone the module env and inherit the
consumption. Modules outside the dependency chain (e.g. a base module the
owner depends on) compile without it.

C++ module interface units (`.cppm`) and builds that pass `cpp_modules=` skip
the PCH: `-fmodules` and the PCH preload are not combined on one translation
unit.

A module opts out with the conf key `"pch": False` in `app.py` — for
dependency trees whose headers are feature-macro hostile (python's pyconfig.h
redefines the glibc feature macros the PCH preloads, fatal under `-Werror`).

## Instances

One PCH instance is compiled per environment fingerprint — CXX, CXXFLAGS,
CPPFLAGS and CPPDEFINES. gcc rejects a PCH whose creation saw macros the
consumer lacks (silent full-parse fallback) and clang hard-errors on macro
conflicts, so defines must match exactly; instances are always created from a
clone of a consuming env, which guarantees it. Both compilers accept differing
`-I` lists and consumer-extra defines, so include paths are deliberately not
part of the fingerprint and modules sharing the same flags share one instance
(in practice one or two per build config).

Artifacts live under `build/<config>/pch/<fingerprint>/` (anchor copy plus
`.gch` or `.pch`). The C scanner tracks the anchor's includes, so an extlib
header change rebuilds the instance.

## Compiler support

gcc and clang (including cross gcc, llvm-mingw wrappers, ndk and filc) are
supported, classified by one `$CXX --version` probe — a `ccache` prefix is
stripped first since ccache answers `--version` itself. `zig` and
`emscripten` have no PCH support: `build_pch` logs an info line and the build
proceeds without it.

ccache gets `CCACHE_SLOPPINESS=pch_defines,time_macros` appended when a PCH is
active.

## Ordering

Call `build_pch` before `build_lib` in the owner's scons.py: flags and the
object dependency are attached to the env at call time.
