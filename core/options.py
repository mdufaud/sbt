"""Declarative registry of the build options sbt understands.

The names here are exactly those the python side reads through
utils.get_opt()/utils.is_opt() — the single source of truth for validation:
- the builder warns once on any argv `name=value` option nobody reads
  (catches typos like `platfrm=linux`),
- `validate()` checks the value of every option that has a checker in
  _CHECKERS (None = free text); an option added here is checked by registering
  its checker,
- `makevars` emits the names to make (SBT_FWD_CORE), which forwards each one
  with its resolved make value — an option added here is forwarded without
  touching the makefiles.

Make-internal variables (j, repeat, INSTALL_DESTDIR, ...) are not listed in
KNOWN_OPTIONS: make consumes them itself, they never reach the builder. The
ones with a typed value are checked through _LOCAL_OPTIONS, never forwarded.
How an option resolves (argv first, then environment) lives in utils.get_opt —
this registry only decides what counts as an option and which values are valid.
"""

# argv tokens consumed by SCons itself on the same command line — never sbt
# options, so the unknown-option warning must stay silent on them.
_SCONS_OWNED_ARGS = frozenset(["def"])

from sbt.core import architectures
from sbt.core import logger
from sbt.core import utils

def _bool(value):
    return None if value.lower() in ("0", "1", "true", "false") else "0, 1, true or false"

def _integer(value, minimum, maximum=None):
    if value.isascii() and value.isdigit() and int(value) >= minimum:
        if maximum is None or int(value) <= maximum:
            return None
    return "an integer >= {}".format(minimum) + ("" if maximum is None else " and <= {}".format(maximum))

def _count(value):
    return _integer(value, 1)

def _seconds(value):
    return _integer(value, 0)

def _port(value):
    return _integer(value, 1, 65535)

def _choice(values, lower=False):
    def check(value):
        return None if (value.lower() if lower else value) in values else "one of " + ", ".join(values)
    return check

def _platform(value):
    if value.lower() in architectures.PLATFORMS or value.lower().startswith("win"):
        return None
    return "one of " + ", ".join(architectures.PLATFORMS)

def _machine(value):
    if architectures.normalize_machine(value) in architectures.architectures:
        return None
    return "one of {} or an alias ({})".format(
        ", ".join(architectures.architectures), ", ".join(architectures.machine_aliases))

_BOOL_OPTIONS = (
    "asan", "combined", "compile_commands", "compile_time", "coverage", "demo",
    "docker_build_local", "fgit", "hwasan", "lsan", "msan", "nocache", "static",
    "test", "tsan", "ubsan", "v", "verbose",
)

_FREE_OPTIONS = (
    "cpu", "cross_sysroot", "docker_builder_image", "docker_runtime_image", "env",
    "fmod", "m", "mode", "modules", "pkgdep", "t", "triplet", "with-system-packages",
    # toolchain / sdk locations
    "ANDROID_API", "ANDROID_NDK_HOST_TAG", "ANDROID_NDK_PATH",
    "ANDROID_SDK_PATH", "FILC_PATH", "JAVA_HOME",
)

_CHECKERS = {
    **dict.fromkeys(_BOOL_OPTIONS, _bool),
    **dict.fromkeys(_FREE_OPTIONS, None),
    "compiler": _choice(architectures.COMPILERS, lower=True),
    "dist": _choice(("tar", "apt", "pacman", "docker")),
    "libc": _choice(architectures.LIBCS, lower=True),
    "machine": _machine,
    "platform": _platform,
}

KNOWN_OPTIONS = frozenset(_CHECKERS)

_LOCAL_OPTIONS = {
    "brief": _bool,
    "j": _count,
    "jtest": _count,
    "repeat": _count,
    "PORT": _port,
    "SBT_LOCK_TIMEOUT": _seconds,
}

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

def validate():
    """Return one `name=value (expected ...)` message per invalid option value.

    Empty values count as unset. Call after the app is loaded: machines an app
    registers are valid values."""
    errors = []
    for name, check in {**_CHECKERS, **_LOCAL_OPTIONS}.items():
        value = utils.get_opt(name)
        expected = check(value) if check and value else None
        if expected:
            errors.append("{}={} (expected {})".format(name, value, expected))
    return sorted(errors)
