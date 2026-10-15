# AGENTS.md — sbt (SCons Build Tools)

Living rules for agents in this repository. On conflict, this file wins over
habits imported from other projects.

## The idea

sbt is a generic, reusable C/C++ build framework, vendored into consumer
projects as `site_scons/sbt/`. Project-specific configuration stays outside,
in the consumer's `app.py` and `site_scons/addon/` (docs/addon.md). That
separation is the architecture: everything here is generic — a change that
only makes sense for one project belongs in that project's addon/, not in
this repo.

Two consequences govern every change:

- **Consumer compatibility is the contract.** Every commit lands in pinned
  consumer projects (their test suite is the separate sbt-test repo).
  Removing/renaming a conf key, an `app.py` attribute, an env method, a make
  target or a CLI arg breaks them: never without an explicit user order,
  and the migration goes into docs/ in the same change.
- **Docs are part of the API.** docs/ is the consumer reference (modules,
  addon, dependencies, sbt-dependencies, cross-compilation, android,
  distribution). A doc line for a dead target, or a live target without its
  doc line, is a bug. This file maps features and traps only — the docs own
  the details; read the relevant one before touching its feature.

## Consumers

Two projects vendor this repo as a git submodule at `site_scons/sbt`; a
consumer `Makefile` is one line (`include site_scons/sbt/makefile/sbt.mk`),
so every makefile/ goal and variable is public surface.

- `~/workspace/sihd` — heavy surface: 19 modules exercising the variant-key
  families (`windows-static-libs` transitive chains, `export-*`, `android-*`,
  `web-*`), `conditional_modules`, the `on_build_success` hook, and a full
  addon/ (vcpkg patches/files/overlay-ports, custom makefile templates +
  scripts, includes).
- `~/workspace/lightbringer` — `sbt_dependencies` consumer (depends on sihd
  through `project:module` depends), top-level flag attrs (`flags`,
  `cxx_flags`, `gcc_link`, ...), a `vcpkg_ports` patch, minimal addon.

Both submodule pins lag local main: a change reaches them only at their
next bump — that is when compat matters.

The repo itself has no build: `GNUmakefile` only scaffolds consumer projects
(`make sbtnewfs|sbtnewgit <path>`, via `genesis.mk` → `genesis_fs/`).
Build behavior is developed against a scaffolded `/tmp` project.

## Feature map — context and traps

- `scons.py` — the `SConstruct` every consumer project loads at startup; an
  import error kills all of them. Keep imports stdlib-only and cheap.
- `core/conf.py` — the conf-key whitelist, single source of truth. A new
  module conf key or `app.py` attribute must enter `CONF_FLAG_ENV` /
  `_NON_FLAG_CONF_KEYS` (or the `export-`/selector-token logic), else
  consumers only get a silent warning. Both spellings derive from
  `CONF_FLAG_ENV`: dash form for module keys (`cxx-flags`), underscore form
  for app attrs (`cxx_flags`) — derive them, never hardcode. Modes are
  always `mode-`-prefixed; a bare `debug-flags` only warns, never selects.
- `core/architectures.py` — platform/compiler/libc/machine vocabularies;
  feeds `SELECTOR_TOKENS`, gcc prefixes, musl/zig dynamic triplets and
  runner packages. Adding a machine/platform means touching conf.py
  selectors, `scons/compilers/` and `vcpkg/triplets.py` together.
- `build/` — module graph incl. conditional/adaptive modules
  (`modules.py`; adaptive modules keep `depends` minimal, optional siblings
  go in `conditional-depends`), sbt-to-sbt deps (`sbt_deps.py`;
  `depends: ['project:module']` resolves into synthetic modules carrying
  the ordered link closure, ABI params inherited from the consumer;
  command-line vars leak into dep sub-makes through `MAKEOVERRIDES` —
  args must pin `m`/`test`, see docs/sbt-dependencies.md), C++20 modules
  parse, distribution.
- `scons/` — env factory; `env_methods.py` is the consumer-facing API
  (`build_lib`, `build_test`, `build_cpp_modules`, ...): a new helper lands
  there, not in the file under hand. `compilers/` backends stay parallel
  (gcc prefix, clang `--target`, mingw dynamic by default, em forces
  web+static, ndk static no-RPATH, zig and filc force musl): a flag added
  to one backend gets its sibling, never unify on the lowest denominator.
  C++20 modules (`cpp_modules.py`): GCC 15+ / Clang 21+ native linux only,
  cross/mingw/em/ndk intentionally disabled, same public API for both
  supported compilers. Cross builds silently skip `pkg-configs` /
  `parse-configs` (host header protection) — transitive `.a` deps must be
  listed explicitly (docs/dependencies.md).
- `vcpkg/` — manifest generated per build config (a release/static/musl
  build needs its own `make dep`); triplet resolution priority: SBT custom
  > vcpkg builtin > community > addon custom > dynamic musl/zig;
  declarative port overlays via `vcpkg_ports` (edit order:
  remove_patches → patches → manifest → files → recipe_patches; a port is
  in `vcpkg_ports` XOR a manual `overlay-ports/` copy — SBT errors).
  vcpkg runs on consumer networks: install code must tolerate being re-run.
- `makefile/` — the CLI (reference: docs/modules.md CLI section).
  - A new test goal is declared in `TEST_GOALS` in `args.mk` **only**;
    `test.mk` derives its `.PHONY` from it. Positional-goal routing is
    `MAKEARG_COMMANDS`, same file.
  - Command-line vars reach python through the environment
    (`env $(MAKEOVERRIDES)`), never argv.
  - Mutating goals wait on `build/.sbt.lock` (shared mutable state:
    `.sconsign.dblite`, `build/last`, `makevars.mk`); read-only goals
    never wait.
  - Portability split at the top of `sbt.mk` (Linux = bash + `/bin/grep`,
    else sh): no bashisms outside the guarded paths.
  - On failure `scripts/cli_helper.py` emits a literal `$(error ...)` fired
    at include time — that is the failure channel, keep it working.
- `scripts/` — `run_cppcheck.py` (layered config: built-in defaults < app.py
  dict < module `cppcheck-*` keys; `enable` replaces, lists accumulate, raw
  `args` last, singleton value flags last-wins), `cli_helper.py`,
  `build_lock.py`, `runner.sh` + `apk_info.sh` (consumed by `test.mk`),
  `serve_wasm.py`.
- `genesis_fs/` — scaffold copied into every new consumer project: public
  API. Note `conditional_modules = {}` must exist in a consumer `app.py`
  (the `modules=` filter reads it unconditionally).
- `android/` — gradle templates with `__SBT_*__` placeholders; the module
  override surface is `<module>/android/`; the release build-type mapping
  is a project decision (`android_release_modes`) — sbt ships no built-in.
- `build/distribution.py` + `makefile/install.mk`, `distribution.mk` —
  `make install` (`.installed` manifest) and `make dist tar|apt|pacman|docker`
  (dist is always mode=release; pacman and docker *generate* PKGBUILD/
  Dockerfile, they never invoke makepkg/docker build).

## Standing code rules

- Nothing consumer-specific here: sbt is generic. Docs and code examples
  never name a consumer's modules (no `util`, `sys`, `net`, `http`, `lua`,
  `imgui`, ... — those are sihd's). Example modules are invented and neutral
  (`base`, `app`, `io`, `client`, `script`, `gui`); real third-party names
  are allowed only as ports/libs (`extlibs`, `libs`, link names).
- Comments: default is deletion. Only the trap the code cannot show
  survives, one line. No narration, no section headers, no change notes.
- No new pip dependency — the repo is vendored into consumers; python
  stdlib and make do it.
- Survey the tree before writing: extend the existing list/map/idiom, never
  invent a parallel mechanism beside it.
- Each platform/compiler keeps its best behavior.

## Verification

No test suite lives in this repo. Minimum gate for any change:

```bash
python3 -m compileall -q .
bash -n makefile/scripts/*.sh scripts/*.sh
make -n help
```

Build behavior → scaffold a project: `make sbtnewfs /tmp/e2e && cd /tmp/e2e
&& make dep && make`. Cross behavior → docs/cross-compilation.md: qemu/wine
runners are auto-selected, sanitizers and gdb are forced off under a runner,
and tests spawning child processes need binfmt_misc on Arch hosts.

## Skills

- `.agents/skills/ponytail/SKILL.md` — sbt layer over the global ponytail.
- `.agents/skills/judge/SKILL.md` — sbt layer over the global judge.
