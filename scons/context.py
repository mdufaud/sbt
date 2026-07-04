"""Build context passed to every env method and factory function.

A single BuildContext is created in sbt/scons.py after the base environment
is set up and is injected into all registered env methods via closures in
env_methods.register_methods().  This replaces ad-hoc closure over ~10
module-level variables in the old monolithic sbt/scons.py.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class BuildContext:
    # Application config loaded from app.py
    app: Any

    # Shared mutable build registries (see state.BuildState)
    state: Any

    # The SCons base environment that all module envs are cloned from
    base_env: Any

    # Dict of all module configurations being built this run
    build_modules: dict

    # List of option-prefix strings used to look up platform/mode/compiler
    # specific keys in module conf dicts (e.g. "linux-libs", "gcc-flags")
    modules_options: list

    # Tuple of configuration dimension names in priority order:
    # (build_platform, libtype, build_mode, compiler, libc)
    default_app_conf_to_get: tuple

    # Resolved build identifiers
    build_platform: str
    modules_lst: list       # empty list means "all modules"
    is_dry_run: bool
    bin_ext: str            # "" / ".exe" / ".html"
    verbose: bool
    distribution: bool
