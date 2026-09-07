"""Declarative registry of the build options sbt understands.

The names here are exactly those the python side reads through
utils.get_opt()/utils.is_opt() — the single source of truth for validation:
- the builder warns once on any argv `name=value` option nobody reads
  (catches typos like `platfrm=linux`),
- `makevars` emits the names to make (SBT_FWD_CORE), which forwards each one
  with its resolved make value — an option added here is forwarded without
  touching the makefiles.

Make-internal variables (j, repeat, INSTALL_DESTDIR, ...) are not listed:
make consumes them itself, they never reach the builder. How an option
resolves (argv first, then environment) lives in utils.get_opt — this
registry only decides what counts as an option.
"""

# argv tokens consumed by SCons itself on the same command line — never sbt
# options, so the unknown-option warning must stay silent on them.
_SCONS_OWNED_ARGS = frozenset(["def"])

from sbt.core import logger

KNOWN_OPTIONS = frozenset([
    "asan", "combined", "compile_commands", "compiler", "coverage", "cpu",
    "cross_sysroot", "demo", "dist", "docker_builder_image",
    "docker_build_local", "docker_runtime_image", "env", "fgit", "fmod",
    "hwasan", "libc", "lsan", "m", "machine", "mode", "modules", "msan",
    "nocache", "pkgdep", "platform", "static", "t", "test", "triplet",
    "tsan", "ubsan", "v", "verbose", "with-system-packages",
    # toolchain / sdk locations
    "ANDROID_API", "ANDROID_NDK_HOST_TAG", "ANDROID_NDK_PATH",
    "ANDROID_SDK_PATH", "FILC_PATH", "JAVA_HOME",
])

_warned_names = set()

def warn_unknown_argv_options(argv):
    """Warn once per unknown `name=value` token found in *argv*."""
    for arg in argv:
        if arg.startswith("-") or "=" not in arg:
            continue
        name = arg.split("=", 1)[0]
        if name in KNOWN_OPTIONS or name in _SCONS_OWNED_ARGS or name in _warned_names:
            continue
        _warned_names.add(name)
        logger.warning("unknown build option '{}' - ignored (see core/options.py)".format(name))
