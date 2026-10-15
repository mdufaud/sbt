# Distribution & Install Guide

## Overview

Two orthogonal workflows:

| Goal | Command |
|------|---------|
| Install files directly on the host system | `make install` |
| Package the build for redistribution | `make dist <type>` |

Both operate on the current build. Build first before running either.

---

## `make install` — Install on the host

Copies the build output (`lib/`, `bin/`, `include/`, `etc/`, `share/`) into the system prefix. Records every installed path in `.installed` for clean removal later.

```bash
# Default: /usr/local
make install

# Custom prefix
make install INSTALL_PREFIX=/opt/myapp

# Into a staging root (e.g. for packaging scripts)
make install INSTALL_DESTDIR=/tmp/staging INSTALL_PREFIX=/usr

# Skip the confirmation prompt
make install INSTALL_NOCONFIRM=1

# Do not install vcpkg-built shared libraries alongside the app
make install INSTALL_NO_EXTLIBS=1
```

### Installed layout

| Source | Destination |
|--------|-------------|
| `build/.../lib/` | `$DESTDIR/$PREFIX/lib/` |
| `build/.../bin/` | `$DESTDIR/$PREFIX/bin/` |
| `build/.../include/` | `$DESTDIR/$PREFIX/include/` |
| `build/.../etc/` | `$DESTDIR/etc/` |
| `build/.../share/` | `$DESTDIR/$PREFIX/share/` |

Note: `etc/` is always placed under `INSTALL_DESTDIR` without prefix (FHS convention).

### Suffix overrides

Each path accepts a suffix variable for non-standard layouts:

| Variable | Applies to |
|----------|-----------|
| `INSTALL_LIBSUFFIX` | `lib/` |
| `INSTALL_BINSUFFIX` | `bin/` |
| `INSTALL_ETCSUFFIX` | `etc/` |
| `INSTALL_INCLUDESUFFIX` | `include/` |
| `INSTALL_SHARESUFFIX` | `share/` |

### Uninstall

```bash
make uninstall
```

Reads `.installed`, lists all paths, asks for confirmation, then removes them.

---

## `make dist` — Package for redistribution

Always builds in `mode=release`. Output goes to `dist/`.

```bash
make dist <type> [m=modules]
# or with explicit modules:
make dist mod <modules> <type>
```

### Types

#### `tar` — Tarball

```bash
make dist tar
make dist tar m=app,base
```

Produces `dist/<name>-<version>.tar.gz` containing `include/`, `lib/`, `bin/`, `etc/`, `share/`. Extlib headers/libs/bins are merged into the corresponding top-level directories.

#### `apt` — Debian package

```bash
make dist apt
make dist apt m=app,base
```

Requires: `dpkg-deb`, `fakeroot` (warning if missing — files will have wrong ownership).

Produces `dist/apt/<name>-<version>.deb`.

Layout inside the `.deb`:

| Source | Destination |
|--------|-------------|
| `bin/` | `/usr/bin/` |
| `include/` | `/usr/include/` |
| `lib/` | `/usr/lib/<multiarch-triplet>/` |
| `share/` | `/usr/share/` |
| `etc/` | `/etc/` |

The `DEBIAN/control` file is generated from `app.py` fields: `name`, `version`, `description`, `maintainers`, `architecture`, and optionally `priority`, `url`, `section`, `multi_architecture`. Package dependencies are resolved from the module extlib configuration mapped via `app.apt_packages`.

Unmapped extlibs are listed in a warning and omitted from the generated package dependencies; map each runtime dependency in `apt_packages`.

#### `pacman` — Arch Linux package

```bash
make dist pacman
make dist pacman m=app,base
```

Does **not** call `makepkg` — generates a ready-to-use `PKGBUILD` in `dist/pacman/<name>-<version>/`. Run `makepkg` manually from that directory.

```bash
cd dist/pacman/<name>-<version>
makepkg -si
```

The `PKGBUILD` embeds the current build options (`platform`, `compiler`, `machine`, `libc`, `mode`) so the package is reproducible. Additional env vars (`script=`, `gui=`, `x11=`, etc.) are auto-deduced from the module configuration. Package dependencies are resolved via `app.pacman_packages`.

Unmapped extlibs are listed in a warning and omitted from `depends`; map each runtime dependency in `pacman_packages`.

If `makepkg` is available on the host, `.SRCINFO` is generated automatically alongside the `PKGBUILD` (required for AUR submission). Otherwise a warning is printed:

```bash
cd dist/pacman/<name>-<version> && makepkg --printsrcinfo > .SRCINFO
```

#### `docker` — Container image (Dockerfile)

Does **not** call `docker build` — generates `dist/docker/Dockerfile` and `dist/docker/.dockerignore`. The file is overwritten on each run. Build the image manually:

```bash
docker build -t my-app dist/docker/
docker run --rm my-app <binary>
```

The Dockerfile is **multi-stage**:

1. **Builder** (default `debian:trixie-slim`) — installs apt `-dev` packages, clones the repo via `git_url` (or `COPY`es it with `docker_build_local=1`), runs `make dep` then `make` in release mode, installs artefacts to `/dist` via `make install`
2. **Runtime** (default `debian:trixie-slim`) — installs only the runtime packages, copies `/dist/usr/bin/` → `/usr/bin/`, `/dist/usr/lib/` → `/usr/lib/<name>/`, sets `LD_LIBRARY_PATH`

Images and package managers are configurable in `app.py` (`docker_builder_image`, `docker_runtime_image`, `docker_builder_pkg_manager`, `docker_runtime_pkg_manager` — pkg managers are auto-detected from the image name otherwise) or overridden on the command line (`docker_builder_image=... docker_runtime_image=... docker_build_local=1`).

Like the `PKGBUILD`, the `make dep` / `make` lines embed the conditional env options
(`script=`, `gui=`, `x11=`, `wayland=`, ...) auto-deduced from the module configuration, so
the generated image builds the same feature set as the command that generated it. Note
that system packages for those features are only included when the module/package
mapping knows them — unmapped ones (e.g. x11/wayland display libs) are provided by
vcpkg during `make dep` (`INSTALL_EXTLIBS=1` then carries the `.so` into the runtime
stage when not static).

Runtime library paths require `app.apk_packages` (Alpine package name mapping):

```python
apk_packages = {"openssl": "openssl", "curl": "libcurl", "zlib": "zlib", ...}
```

---

## `app.py` fields used by packaging

```python
name        = "myapp"
version     = "1.0.0"
description = "My application"
maintainers = ["Name <email>"]          # first = Maintainer, rest = Uploaders
contributors = ["Name <email>"]         # PKGBUILD # Contributor lines
architecture = "amd64"                  # or "any", "all", etc.
url         = "https://..."             # optional
section     = "libs"                    # optional (apt Section / pacman groups)
priority    = "optional"                # optional, apt only, default: optional
multi_architecture = "same"             # optional, apt only

# Optional: hardcode extra make vars in PKGBUILD build()
additional_build_env = ["script", "gui"]    # if absent, auto-deduced from module configs

# Package manager → system package name mapping
apt_packages    = {"libfmt": "libfmt-dev", ...}
pacman_packages = {"libfmt": "fmt", ...}
apk_packages    = {"libfmt": "fmt", ...}     # Alpine runtime packages (docker dist)

# optional: pacman source= line
pacman_source = "https://github.com/org/repo/archive/v${pkgver}.tar.gz"
```
