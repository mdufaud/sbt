# SBT Project Dependencies

Use another SBT-based project as a build-time dependency — its libraries, headers, and
binaries are installed into your project's `extlib/` directory, exactly like vcpkg packages.

## Quick start

In your `app.py`, declare a `sbt_dependencies` dict:

```python
sbt_dependencies = {
    "project": {
        "git": "https://github.com/owner/project.git",
        "ref": "main",
        "args": {
            "mode": "release",
            "m": "module1,module2",
        },
    }
}
```

Then run:

```bash
make dep        # clone + build + install sbt deps, then fetch vcpkg
make build      # build your project, linking against the installed deps
```

## Configuration keys

| Key | Required | Description |
|-----|----------|-------------|
| `git` | yes | Git URL to clone from |
| `ref` | no | Branch, tag, or commit (default: `main`) |
| `args` | no | Build arguments forwarded to the dependency's `make build` |
| `vcpkg` | no | Set to `"own"` to give the dep its own `.vcpkg/` (see below) |
| `recursive` | no | Pass `--recursive` to `git clone` (default: `false`) |

## Build arguments (`args`)

The `args` dict overrides build parameters for the dependency. Useful keys:

```python
"args": {
    "mode":   "release",       # build mode: debug / fast / release
    "m":      "module1,module2",     # which modules of the dep to build
    "static": "1",             # force static linking
}
```

**ABI-critical parameters** (`platform`, `compiler`, `machine`, `libc`) are always inherited
from your project's build config and cannot be overridden. This guarantees binary compatibility.

### Pin `m`/`modules`/`test` to stop them leaking in

Command-line build vars you pass to *your* project leak into the dependency's sub-`make` through
make's `MAKEOVERRIDES`. So `make modules=app,proto test=1` forwards `modules=app,proto` and `test=1`
to the dependency too. The dependency has no module named `app` or `proto`, so its build aborts.

Pin every such var explicitly in `args` so it overrides the leaked value:

```python
"args": {
    "mode":    "release",
    "modules": "util",     # build the dep's own module, not your filter
    "test":    "0",        # don't build the dep's tests as a side effect
}
```

> Note: some projects concatenate `modules` with `m` (`modules=$(modules)$(m)`). Pin the same key
> the dependency reads — pinning `modules` while the leak comes through `m` won't cancel it.

## Sharing vcpkg

By default, SBT dependencies share your project's `.vcpkg/` installation via the
`VCPKG_ROOT` environment variable. This means:

- vcpkg is only bootstrapped once
- packages common to both projects are compiled once
- each project still has its own `build/` and `extlib/` directories

If a dependency uses custom vcpkg overlay-ports (patches), it may need its own vcpkg:

```python
sbt_dependencies = {
    "patched-lib": {
        "git": "https://github.com/owner/patched-lib.git",
        "ref": "v2.0",
        "vcpkg": "own",   # use dep's own .vcpkg/, do not share
    }
}
```

## Installed artifacts

After `make dep`, the dependency's build artifacts appear in your project's
`build/<triplet>/<compiler>/<mode>/<static|dynamic>/extlib/`:

```
extlib/
├── include/     ← dependency's public headers
├── lib/         ← dependency's compiled libraries (.a / .so)
└── bin/         ← dependency's executables (if any)
```

Both the dependency's own libraries **and** its transitive vcpkg packages are installed here.
Your modules can then link against them via the standard `libs` key:

```python
modules = {
    "myapp": {
        "depends": ["util"],
        "libs": ["project_module1", "project_module2"],   # from the installed dep
    }
}
```

## `make dep` is per build config

`extlib/` lives under the build directory: `build/<triplet>/<compiler>/<mode>/<static|dynamic>/extlib/`. Every
distinct combination of `mode`, `libc`, and `static` gets its own. Run `make dep` once **per build
config** — a release build does not inherit the debug build's installed headers and libraries:

```bash
make dep                                    # debug, glibc, dynamic
make dep static=1 libc=musl mode=release    # separate extlib/ for the static-musl build
```

## Linking an SBT dependency statically

A static archive (`.a`) records no dependencies — unlike a shared object's `DT_NEEDED`. So when you
link your project statically, **every transitive external library must appear on the final link
line**, in the right order. Two things to get right:

1. **Export the transitive libs.** In the module that consumes the dependency, set
   `export-all-libs: True` (or list them in `export-libs`) so a static-linked dependent inherits them.
   See [modules.md](modules.md) `export-*` keys.
2. **Order them consumer-before-provider.** The linker resolves left-to-right and SBT does not wrap
   libs in `--start-group`. List a library *before* the libraries it needs:

   ```python
   # sihd's util uses sihd::json, which uses simdjson:
   "libs": ['sihd_util', 'sihd_json', 'simdjson', 'qrencode', 'zstd', 'fmt'],
   "export-all-libs": True,
   ```

   Symptom of wrong order or a missing export: `undefined reference to ...` at the final link, even
   though `make dep` succeeded.

### Static + musl: clean stale `.so`

If you ran a dynamic `make dep` first, `extlib/lib/` holds `.so` files. scons resolves those in
preference to the `.a`, breaking the static link (`Implicit dependency libfoo.so not found`, or a
binary that is not actually static). Before a static build, remove every `*.so*` that has a sibling
`*.a` in `extlib/lib/`, or wipe and re-`make dep` that build config.

> The dependency must also build *its* vcpkg ports statically under musl. SBT's musl triplet honors
> `static=1` (emits `VCPKG_LIBRARY_LINKAGE static`); a dependency on an older SBT that hardcoded
> `dynamic` will hand you `.so` ports — update its `site_scons/sbt`.

## Recursive dependencies

If a dependency itself declares `sbt_dependencies`, those are resolved automatically.
All projects are cloned into `.sbt-deps/` at the root of your project (flat layout),
and built in topological order (deepest dependency first).

```
your-project/
└── .sbt-deps/
    ├── libA/         ← direct dep
    └── libB/         ← transitive dep of libA (also used here, cloned once)
```

Conflict detection: if two deps require the same name with different git URLs, the build
aborts with an error message.

## Clone location and caching

Clones are stored in `.sbt-deps/<name>/` at your project root and reused across builds.
They are not re-cloned unless you pass `fgit=1`:

```bash
make dep fgit=1         # force re-clone of all SBT deps
```

`.sbt-deps/` is excluded from version control (`.gitignore`).

## Full example

```python
# app.py

sbt_dependencies = {
    "project": {
        "git": "https://github.com/owner/project.git",
        "ref": "v1.2.3",
        "args": {
            "mode": "release",
            "m": "module1,module2,module3",
        },
    }
}

modules = {
    "myapp": {
        "depends": [],
        "libs": ["module1", "module2", "module3"],
    }
}
```

```bash
make dep m=myapp          # fetch owner/project + vcpkg deps for module myapp
make m=myapp              # build module myapp
```
