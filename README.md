# SBT — SCons Build Tools

SBT is a generic, reusable C/C++ build framework built on top of [SCons](https://scons.org/) and GNU Make. It sits in a project as `site_scons/sbt/` and drives module discovery, cross-compilation, vcpkg dependency management, testing, and packaging through a single `Makefile` CLI.

Project-specific configuration lives outside SBT, in `app.py` and an `addon/` directory — see [docs/addon.md](docs/addon.md).

## Repository layout

```
.
├── scons.py            # SCons entry point (SConstruct), loads app.py and orchestrates the build
├── core/                # Foundations: builder, loader, architectures, logger, utils
├── build/                # Module graph resolution, C++20 modules, distribution, sbt-to-sbt deps
├── scons/                # SCons environment factory, compiler backends, Android/context helpers
├── vcpkg/                # vcpkg manifest generation, triplets, cross toolchains, patches, licenses
├── makefile/             # Make targets included by the top-level Makefile (build, test, dep, dist, ...)
├── android/              # Default Gradle project templates for Android APK builds
├── scripts/              # CLI helper, cppcheck runner, WASM dev server
├── genesis_fs/           # Template scaffolded by `make newsbt <path>` for new projects
└── docs/                 # Reference guides (see below)
```

## Creating a new project

```bash
make sbtnewfs <project_path>   # vendor this repo as plain files
make sbtnewgit <project_path>  # vendor this repo as a git submodule
```

Both copy `genesis_fs/` into `<project_path>` (a starter `app.py`, `Makefile`, `SConstruct.py`, and an example module). `sbtnewfs` copies this repository into `<project_path>/site_scons/sbt/` as plain files. `sbtnewgit` git-inits `<project_path>` and adds this repository as a submodule at `<project_path>/site_scons/sbt` — this repo must have at least one commit first, and the submodule URL will point at this local clone until you update it to point at wherever you push it.

## Quick start

```bash
cd <project_path>
make dep                      # install external dependencies via vcpkg
make                          # build all modules
make m=util,core              # build specific modules
make test=1                   # build + compile tests
make test m=core               # build + run tests
```

## Documentation

| Guide | Covers |
|-------|--------|
| [docs/modules.md](docs/modules.md) | Module layout, `app.py` module config keys, platform/compiler variants, `scons.py` API, CLI reference |
| [docs/dependencies.md](docs/dependencies.md) | Declaring and linking external libraries (vcpkg extlibs) |
| [docs/sbt-dependencies.md](docs/sbt-dependencies.md) | Using another SBT project as a build-time dependency |
| [docs/cross-compilation.md](docs/cross-compilation.md) | Supported targets, toolchains, musl, vcpkg cross builds, running tests under qemu/wine |
| [docs/android.md](docs/android.md) | Building Android APKs from modules, emulator targets, template overrides |
| [docs/addon.md](docs/addon.md) | `site_scons/addon/` extension point: vcpkg config, overlay ports, custom triplets, custom Make targets |
| [docs/distribution.md](docs/distribution.md) | `make install` and `make dist` (tar, apt, pacman, docker) |

## Requirements

- Python 3 and `jq` (checked by the Makefile)
- SCons
- A C/C++ toolchain (GCC or Clang); cross-compilation toolchains as needed per target (see [docs/cross-compilation.md](docs/cross-compilation.md))
- vcpkg is bootstrapped automatically by `make dep`
