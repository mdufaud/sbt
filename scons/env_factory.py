"""Module environment factory.

Provides helpers to:
- Compute the ordered list of option-prefix strings used for platform/mode/
  compiler-specific conf key lookups (e.g. "linux-libs", "gcc-flags").
- Apply combinatorial app-level configuration to a SCons environment.
- Create a fully configured per-module SCons environment (clone of base_env)
  enriched with the module's libraries, flags, includes, and defines.
"""

from os import path as os_path

from sbt.core import builder
from sbt.core import architectures
from sbt.core import conf as sbt_conf
from site_scons.sbt.build import modules as build_modules_util
from site_scons.sbt.scons import utils as scons_utils
from site_scons.sbt.scons import cpp_modules as scons_cpp_modules


###############################################################################
# modules_options computation
###############################################################################

def compute_modules_options(build_platform, libtype, build_mode, compiler, _builder):
    """Return the ordered list of option prefixes for conf key lookups.

    These prefixes are used to find platform/mode/compiler specific values in a
    module's conf dict, e.g. conf.get("linux-libs", []) or conf.get("gcc-flags", []).
    """
    libc = _builder.libc
    options = [
        libtype,
        build_platform,
        f"mode-{build_mode}",
        compiler,
        libc,
        _builder.build_machine,
    ]
    if _builder.is_cross_building():
        options.append("cross")
        options.append(f"{build_platform}-cross")
    else:
        options.append("native")
        options.append(f"{build_platform}-native")

    # Add libtype- and libc-suffixed variants: e.g. "linux-static", "gcc-shared",
    # "gcc-gnu", "clang-musl", "linux-musl" — lets modules tune libs/flags per libc.
    to_append = [f"{opt}-{libtype}" for opt in options if opt != libtype]
    to_append += [f"{opt}-{libc}" for opt in options if opt != libc]
    options += to_append
    return options


def get_compilation_options(conf, key, modules_options):
    """Collect per-option values from *conf* for *key*.

    Iterates over *modules_options* and concatenates any matching list found
    under key "{option}-{key}" in *conf*.
    """
    ret = []
    for option in modules_options:
        ret += conf.get(f"{option}-{key}", [])
    return ret


###############################################################################
# App configuration application
###############################################################################

def add_combination_app_conf_to_env(env, app, default_app_conf_to_get):
    """Apply combinatorial app configuration to *env*.

    For each configuration dimension (platform, libtype, mode, compiler, libc)
    and each combination of subsequent dimensions, call add_env_app_conf.
    This allows app.py to declare e.g. linux_static_libs = [...].
    """
    for idx, app_config in enumerate(default_app_conf_to_get, start=1):
        keys = [app_config]
        scons_utils.add_env_app_conf(app, env, *keys)
        for sub_app_config in default_app_conf_to_get[idx:]:
            keys.append(sub_app_config)
            scons_utils.add_env_app_conf(app, env, *keys)


###############################################################################
# Module environment factory
###############################################################################

def create_module_env(conf, ctx,
                      depends=None,
                      do_inherit_depends_defines=False,
                      do_inherit_depends_links=False,
                      do_inherit_depends_flags=False,
                      do_inherit_depends_generated_libs=False):
    """Create a fully configured SCons environment for a specific module.

    Clones ctx.base_env and enriches it with the module's libraries, compiler
    flags, include paths, and preprocessor defines derived from *conf* and its
    resolved dependency tree.

    Args:
        conf: Module configuration dict (as built by build.modules).
        ctx: BuildContext with shared state, base_env, and build_modules.
        depends: List of dependency module names to inherit from.
        do_inherit_depends_defines: Inherit defines from direct dependencies.
        do_inherit_depends_links: Inherit link flags from direct dependencies.
        do_inherit_depends_flags: Inherit compiler flags from direct dependencies.
        do_inherit_depends_generated_libs: Link libs produced by dependencies.
    """
    if depends is None:
        depends = []

    modname = conf["modname"]
    modules_options = ctx.modules_options

    # Sort deps by their own dependency depth so deeper deps come first,
    # preserving correct static link order (most dependent → least).
    ordered_depends = sorted(
        depends,
        key=lambda dep: len(ctx.build_modules.get(dep, {}).get("depends", [])),
        reverse=True,
    )

    # --- Libraries (special: prepended, musl-filtered, dep-generated, deduped) ---
    # Keep module-local libraries before transitive exports so static link order
    # remains correct on platforms like MinGW.
    libs = build_modules_util.get_module_libs(ctx.build_modules, modname)
    libs += get_compilation_options(conf, "libs", modules_options)
    libs += conf.get("_resolved_export_libs", [])
    if builder.libc == "musl":
        libs = [lib for lib in libs if lib not in architectures.musl_excluded_libs]

    # --- Other flag-keys: map-driven from the canonical CONF_FLAG_ENV taxonomy ---
    # Only flags/link/defines carry resolved exports and inherited-from-deps values.
    _export_keys = ("flags", "link", "defines")
    append_values = {}
    for base, env_var in sbt_conf.CONF_FLAG_ENV.items():
        if base == "libs":
            continue
        values = []
        if base in _export_keys:
            values += conf.get(f"_resolved_export_{base}", [])
        values += conf.get(base, [])
        values += get_compilation_options(conf, base, modules_options)
        append_values[env_var] = values

    # --- Inherited values from dependency modules ---
    depends_generated_libs = []
    depends_defines = []
    depends_links = []
    depends_flags = []
    for dep_modname in ordered_depends:
        if do_inherit_depends_generated_libs:
            for lib_info in ctx.state.generated_libs.get(dep_modname, []):
                if lib_info["name"] not in depends_generated_libs:
                    depends_generated_libs.append(lib_info["name"])
        depend_conf = ctx.build_modules.get(dep_modname, {})
        if depend_conf:
            if do_inherit_depends_defines:
                depends_defines.extend(depend_conf.get("defines", []))
            if do_inherit_depends_links:
                depends_links.extend(depend_conf.get("link", []))
            if do_inherit_depends_flags:
                depends_flags.extend(depend_conf.get("flags", []))

    # each module sees exactly its declared dependencies' headers,
    # deterministically ordered, without leaking includes between unrelated modules.
    cpppath = [os_path.join(builder.build_modules_path, modname, "include")]
    cpppath += [
        os_path.join(builder.build_modules_path, dep, "include")
        for dep in ordered_depends
        if not build_modules_util.is_external_depend(dep)
    ]

    # --- Clone and configure environment ---
    env = ctx.base_env.Clone()
    env.PrependUnique(
        LIBS=depends_generated_libs + libs,
    )
    append_values["CPPFLAGS"] += depends_flags
    append_values["LINKFLAGS"] += depends_links
    append_values["CPPDEFINES"] += depends_defines
    append_values["CPPPATH"] = cpppath
    env.AppendUnique(**append_values)
    # Do NOT auto-enable C++ module flags here even if a dependency exported BMIs.
    # Modules flags (-fmodules / -fmodule-mapper) are injected on demand by
    # build_lib/build_test/build_demo/build_bin when the caller passes cpp_modules=.
    # Auto-propagation would pollute every source of every dependent module.

    env["APP_MODULE_NAME"] = modname
    env["APP_MODULE_FORMAT_NAME"] = f"{ctx.app.name}_{modname}"
    env["APP_MODULE_CONF"] = conf
    env["APP_MODULE_DIR"] = os_path.join(builder.build_modules_path, modname)

    # Apply pkg-config and binary-config
    package_configs = conf.get("pkg-configs", [])
    scons_utils.load_env_packages_config(env, *package_configs)
    parse_configs = conf.get("parse-configs", [])
    scons_utils.parse_config_command(env, *parse_configs)

    # Deduplicate LIBS preserving the last occurrence of each entry so that
    # transitive deps added by parse-configs don't break static link order.
    final_lib = env['LIBS']
    new_final_lib = []
    for el in reversed(final_lib):
        if el not in new_final_lib:
            new_final_lib.append(el)
    new_final_lib.reverse()
    env['LIBS'] = new_final_lib

    return env
