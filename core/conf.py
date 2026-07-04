"""
SBT configuration-key vocabulary and validation.

Single source of truth for which keys/selector tokens are legal in app.py and
module conf dicts, plus reporting of unknown keys.
"""

from sbt.core import architectures
from sbt.core import logger

# Canonical flag-key → SCons env var map. Single source for every flag-key list:
# module conf keys use the dash base name ("cxx-flags"), app.py top-level vars use
# the underscore form ("cxx_flags"); both derive from this map.
CONF_FLAG_ENV = {
    "libs": "LIBS",
    "c-flags": "CFLAGS",
    "cxx-flags": "CXXFLAGS",
    "flags": "CPPFLAGS",
    "defines": "CPPDEFINES",
    "link": "LINKFLAGS",
    "bin-link": "BIN_LINKFLAGS",
}

# Every token usable as a conf-key selector prefix (e.g. "linux-libs", "gcc-flags").
# Modes are excluded — handled by the "mode-" prefix special case in validation.
SELECTOR_TOKENS = frozenset(
    architectures.PLATFORMS + architectures.COMPILERS + architectures.LIBTYPES
    + architectures.LIBCS + (architectures.ANDROID_LIBC,)
    + architectures.CROSS_STATES + architectures.MACHINES
)

_NON_FLAG_CONF_KEYS = frozenset([
    "depends", "extlibs", "pkg-configs", "parse-configs",
    "inherit-depends-libs", "inherit-depends-defines",
    "inherit-depends-links", "inherit-depends-generated-libs",
    "platforms", "env", "android-permissions",
    "conditional-env", "conditional-depends",
    "allow-platforms", "exclude-platforms",
    "allow-link-shared", "allow-link-static",
])

_BASE_CONF_KEYS = _NON_FLAG_CONF_KEYS | frozenset(CONF_FLAG_ENV)

_EXPORT_ALL_KEYS = frozenset([
    "export-all-libs", "export-all-defines", "export-all-flags", "export-all-link",
])

def _is_known_conf_key(key, modes):
    if key in _BASE_CONF_KEYS or key in _EXPORT_ALL_KEYS:
        return True
    k = key[len("export-"):] if key.startswith("export-") else key
    if k in _BASE_CONF_KEYS:
        return True
    parts = k.split("-")
    while parts:
        if parts[0] in SELECTOR_TOKENS:
            parts.pop(0)
        elif parts[0] == "mode" and len(parts) > 1 and parts[1] in modes:
            parts.pop(0)
            parts.pop(0)
        else:
            break
    return "-".join(parts) in _BASE_CONF_KEYS

def get_app_modes(app):
    """ @brief project-defined mode allowlist (from app.py + its includes) """
    return frozenset(getattr(app, "modes", []))

def get_conf_vocabulary(app):
    return {
        "base_keys": sorted(_BASE_CONF_KEYS),
        "export_all_keys": sorted(_EXPORT_ALL_KEYS),
        "selector_tokens": sorted(SELECTOR_TOKENS),
        "modes": sorted(get_app_modes(app)),
        "app_conf_scopes": sorted(_APP_CONF_SCOPES),
    }

def check_unknown_conf_keys(modules, modes):
    for modname, conf in modules.items():
        if not isinstance(conf, dict):
            continue
        for key in conf:
            if key.startswith("_"):
                continue
            if not _is_known_conf_key(key, modes):
                logger.warning("module '{}': unknown conf key '{}'".format(modname, key))

_APP_FLAG_SUFFIXES = tuple("_" + name.replace("-", "_") for name in CONF_FLAG_ENV)
# app-only build-phase scopes prepended to flag attrs (e.g. test_libs, demo_web_link)
_APP_CONF_SCOPES = frozenset(["test", "demo"])

def _is_known_app_conf_attr(attr, modes):
    dash = attr.replace("_", "-")
    parts = dash.split("-")
    while parts and parts[0] in _APP_CONF_SCOPES:
        parts.pop(0)
    return _is_known_conf_key("-".join(parts), modes)

def check_unknown_app_conf_keys(app, modes):
    for attr in dir(app):
        if attr.startswith("_"):
            continue
        if not attr.endswith(_APP_FLAG_SUFFIXES):
            continue
        if not _is_known_app_conf_attr(attr, modes):
            logger.warning("app.py: unknown configuration attribute '{}'".format(attr))
