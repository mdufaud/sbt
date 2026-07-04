import os
import sys

from site_scons.sbt.core.utils import dedupe_keep_order
from sbt.core import conf

def is_external_depend(name):
    """A "<project>:<module>" depend refers to a module of an SBT dependency,
    not a local module."""
    return ":" in name

def _get_export_options(conf, key, modules_options):
    ret = conf.get(f"export-{key}", [])[:]
    for option in modules_options:
        ret.extend(conf.get(f"export-{option}-{key}", []))
    return ret

def _get_active_options(conf, key, modules_options):
    ret = conf.get(key, [])[:]
    for option in modules_options:
        ret.extend(conf.get(f"{option}-{key}", []))
    return ret

def fill_modlist_from_modules(modules, specific_modules, modlist):
    """ @brief Gets all modules to build from a single module to build
    """
    if not specific_modules:
        return
    for module_name in specific_modules:
        conf = modules.get(module_name, None)
        if conf is None:
            # "<project>:<module>" cross-project depend: not a local module
            if is_external_depend(module_name):
                continue
            raise RuntimeError("No such module: {}".format(module_name))
        modlist[module_name] = conf
        fill_modlist_from_modules(modules, conf.get('depends', []), modlist)
        #fill_modlist_from_modules(modules, conf.get('conditional-depends', []), modlist)

def __rec_fill_module_real_depends(modules, module_name, to_fill_module_conf):
    """ @brief Fill a single module real dependency tree into modules
    """
    conf = modules.get(module_name, None)
    if conf is None:
        # "<project>:<module>" cross-project depend: no local real-dependency tree
        if is_external_depend(module_name):
            return
        raise RuntimeError("Error in module's configuration, not a module: {}".format(module_name))
    curr_depends = to_fill_module_conf.setdefault("depends", [])
    depends = conf.get('depends', [])
    for dependancy in depends:
        if dependancy not in curr_depends:
            curr_depends.insert(0, dependancy)
    for depending_module_name in depends:
        __rec_fill_module_real_depends(modules, depending_module_name, to_fill_module_conf)

def __get_module_fill_order(modules):
    order = []
    iterations = 0
    # maximum is worst case scenario
    max_iterations = pow(len(modules), 2)
    while len(order) != len(modules):
        for modname, conf in modules.items():
            if modname in order:
                continue
            depends = conf.get("depends", [])
            # "<project>:<module>" cross-project depends are not local modules and
            # never join the local build order; ignore them for ordering.
            if all(dep in order for dep in depends if not is_external_depend(dep)):
                order.append(modname)
        iterations += 1
        if iterations > max_iterations:
            print("module order error", file = sys.stderr)
            print("maximum module order completion: {}".format(order), file = sys.stderr)
            for modname, conf in modules.items():
                print("module[{}] dependancies -> {}".format(modname, conf.get("depends", [])), file = sys.stderr)
            raise SystemExit("maximum iterations reached to get modules build order - check your app configuration")
    return order

def resolve_modules_dependencies(modules):
    """ @brief Fill all modules real dependency tree
        @param modules modules dict
    """
    order = __get_module_fill_order(modules)
    for name in order:
        conf = modules[name]
        conf["modname"] = name
        # depends is structural (build order + dep tree); default it when absent
        conf.setdefault("depends", [])
        conf["original-depends"] = conf["depends"][:]
        # Adds conditional dependencies if they are in the current build
        conditional_depends = conf.get("conditional-depends", [])
        if conditional_depends:
            conf['depends'].extend([cond_mod for cond_mod in conditional_depends if cond_mod in modules])
        conf["declared-depends"] = conf['depends'][:]
        # Get dependency tree
        __rec_fill_module_real_depends(modules, name, conf)

def resolve_modules_exports(modules, modules_options):
    order = __get_module_fill_order(modules)
    for name in order:
        conf = modules[name]
        if conf.get("external"):
            # synthetic cross-project module: exports already resolved at injection
            continue
        resolved_export_libs = []
        resolved_export_defines = []
        resolved_export_flags = []
        resolved_export_link = []
        if conf.get("export-all-libs", False):
            resolved_export_libs.extend(_get_active_options(conf, "libs", modules_options))
        if conf.get("export-all-defines", False):
            resolved_export_defines.extend(_get_active_options(conf, "defines", modules_options))
        if conf.get("export-all-flags", False):
            resolved_export_flags.extend(_get_active_options(conf, "flags", modules_options))
        if conf.get("export-all-link", False):
            resolved_export_link.extend(_get_active_options(conf, "link", modules_options))
        resolved_export_libs.extend(_get_export_options(conf, "libs", modules_options))
        resolved_export_defines.extend(_get_export_options(conf, "defines", modules_options))
        resolved_export_flags.extend(_get_export_options(conf, "flags", modules_options))
        resolved_export_link.extend(_get_export_options(conf, "link", modules_options))
        for dep in conf.get("declared-depends", []):
            dep_conf = modules.get(dep, {})
            resolved_export_libs.extend(dep_conf.get("_resolved_export_libs", []))
            resolved_export_defines.extend(dep_conf.get("_resolved_export_defines", []))
            resolved_export_flags.extend(dep_conf.get("_resolved_export_flags", []))
            resolved_export_link.extend(dep_conf.get("_resolved_export_link", []))
        conf["_resolved_export_libs"] = dedupe_keep_order(resolved_export_libs)
        conf["_resolved_export_defines"] = dedupe_keep_order(resolved_export_defines)
        conf["_resolved_export_flags"] = dedupe_keep_order(resolved_export_flags)
        conf["_resolved_export_link"] = dedupe_keep_order(resolved_export_link)

def get_module_libs(modules, modname):
    conf = modules[modname]
    return conf.get('libs', [])[:]

def get_extlibs_versions(app, modules_extlibs):
    extlibs = getattr(app, "extlibs", {})
    ret = {}
    # matching with extlibs
    for extlibname in modules_extlibs:
        for libname, version in extlibs.items():
            if libname == extlibname:
                ret[libname] = version
    return ret

def get_modules_extlibs(app, modules, platform):
    """ Gets all libs versions needed by selected modules
        @param app the application configuration module
        @return dict as dict[libname] = version
    """
    modules_extlibs = set()
    # getting used libs for every modules
    for _, module in modules.items():
        modules_extlibs.update(module.get('extlibs', []))
        modules_extlibs.update(module.get('{}-extlibs'.format(platform), []))
    return get_extlibs_versions(app, modules_extlibs)

def get_modules_packages(app, packet_manager_name, modules_extlibs):
    pkg_manager_conf_name = "{}_packages".format(packet_manager_name)
    pkg_manager_conf = getattr(app, pkg_manager_conf_name, None)
    if pkg_manager_conf is None:
        raise RuntimeError("app configuration does not have a package manager '{}' conf named: '{}'".format(packet_manager_name, pkg_manager_conf_name))
    ret = {}
    missing = []
    for libname, version in modules_extlibs.items():
        package_libname = pkg_manager_conf.get(libname, None)
        if package_libname is None:
            missing.append(libname)
            continue
        ret[package_libname] = version
    return ret, missing

def add_conditional_module(conditional_modules, modules, modname):
    """ @brief check if a conditional module is in modules list
        @param conditional_modules modules dictionnary from application's conf
        @param modules modules dict to add to
        @param modname the module to be added from conditional_modules
    """
    conditional_module = conditional_modules.get(modname, None)
    if conditional_module is None:
        raise RuntimeError("App does not have conditional module named: " + modname)
    modules[modname] = conditional_module

def has_conditional_in_modules_list(conditional_modules, modules):
    """ @brief check if a conditional module is in modules list
        @param conditional_modules modules dictionnary from application's conf
        @param modules modules dict to check
        @return bool
    """
    ret = False
    for modname in modules:
        if modname in conditional_modules:
            ret = True
            break
    return ret

def check_conditional_modules(app):
    """ @brief check if application conf has conditional modules and check if names are unique
        @param app the application configuration module
        @return bool
    """
    has_conditionals = hasattr(app, "conditional_modules")
    if has_conditionals is True:
        for modname, _ in app.conditional_modules.items():
            if modname in app.modules:
                raise RuntimeError("App's conditional module share a name with a module: " + modname)
    return has_conditionals

def remove_module(app, modname):
    """ @brief removes a module from application conf
        @param app the application configuration module
        @param modname the module to be removed
    """
    if hasattr(app, "modules") and modname in app.modules:
        del app.modules[modname]
    if hasattr(app, "conditional_modules") and modname in app.conditional_modules:
        del app.conditional_modules[modname]

def get_module_merged_with_conditionals(app):
    """ @brief merge app.modules and app.conditional_modules
        @param app the application configuration module
        @return dict of complete modules
    """
    ret = {}
    if hasattr(app, "modules"):
        for key, value in app.modules.items():
            ret[key] = value
    if hasattr(app, "conditional_modules"):
        for key, value in app.conditional_modules.items():
            ret[key] = value
    return ret

def get_conditionals_from_env(app):
    """ @brief gets conditional modules based on their presence in env
        @param app the application configuration module
        @return list of module names
    """
    ret = []
    if hasattr(app, "conditional_modules"):
        for key, conf in app.conditional_modules.items():
            cond_env = conf.get("conditional-env", None)
            if cond_env is not None and os.getenv(cond_env, None) == "1":
                ret.append(key)
    return ret

def check_platform(modules, platform, modules_options=None):
    """ @brief sanatize modules based on platform and build selectors
        @param platform current build platform (allowlist check)
        @param modules_options selector tokens (libtype/platform/mode/compiler/libc/
               machine/...) used by the generic "exclude-platforms" blocklist
        @return modules to remove
    """
    to_remove = []
    for name, conf in modules.items():
        module_platforms = conf.get("allow-platforms", None)
        if module_platforms is not None and platform not in module_platforms:
            to_remove.append(name)
            continue
        if modules_options is not None:
            excluded = conf.get("exclude-platforms", [])
            if any(opt in modules_options for opt in excluded):
                to_remove.append(name)
    for name in to_remove:
        del modules[name]
    return to_remove

def check_linkage(modules, linkage):
    """ @brief sanatize modules based on link mode ("static"|"shared")
        @return modules to remove

        "allow-link-shared": dropped from static builds (e.g. GUI modules
        needing system-only dynamic libs like libGL). "allow-link-static": inverse.
    """
    to_remove = []
    for name, conf in modules.items():
        if conf.get("allow-link-shared", False) and linkage != "shared":
            to_remove.append(name)
        elif conf.get("allow-link-static", False) and linkage != "static":
            to_remove.append(name)
    for name in to_remove:
        del modules[name]
    return to_remove

def _external_module_closure(dep_modules, dep_app_name, modname):
    """Ordered static link closure for an external project module.

    Mirrors create_module_env's LIBS assembly: the module's own archive first,
    then its transitive dependency archives (deepest first), then the module's
    resolved export libs (extlibs). MinGW-safe consumer-before-provider order.
    """
    conf = dep_modules[modname]
    depends = conf.get("depends", [])
    ordered = sorted(
        depends,
        key=lambda d: len(dep_modules.get(d, {}).get("depends", [])),
        reverse=True,
    )
    libs = [f"{dep_app_name}_{modname}"]
    libs += [f"{dep_app_name}_{d}" for d in ordered]
    libs += conf.get("libs", [])
    libs += conf.get("_resolved_export_libs", [])
    return dedupe_keep_order(libs)

def _load_external_app(deps_dir, project):
    from site_scons.sbt.build import sbt_deps
    app_path = os.path.join(deps_dir, project, "app.py")
    if not os.path.isfile(app_path):
        raise RuntimeError(
            "external dependency '{}' not found at {} - run 'make dep'".format(project, app_path))
    try:
        return sbt_deps._import_app_from_path(app_path)
    except Exception as e:
        raise RuntimeError(
            "could not load external dependency '{}' app.py: {}".format(project, e))

def resolve_external_modules(app, deps_dir, modules_options):
    """Resolve `project:module` depends into synthetic local module entries.

    Scans every (conditional) module's depends for `project:module` refs, loads
    each referenced dependency's app.py from deps_dir/<project>/app.py, resolves
    that project's module export graph, and injects a synthetic entry keyed
    `project:module` into app.modules carrying the full ordered link closure.
    """
    if not hasattr(app, "modules"):
        return
    universe = get_module_merged_with_conditionals(app)
    refs = {}
    for conf in universe.values():
        for dep in conf.get("depends", []) + conf.get("conditional-depends", []):
            if not is_external_depend(dep):
                continue
            project, _, mod = dep.partition(":")
            refs.setdefault(project, set()).add(mod)
    if not refs:
        return
    for project, wanted in refs.items():
        dep_app = _load_external_app(deps_dir, project)
        dep_modules = build_modules_conf(dep_app)
        resolve_modules_exports(dep_modules, modules_options)
        for mod in wanted:
            if mod not in dep_modules:
                raise RuntimeError(
                    "external module '{}:{}' does not exist in dependency '{}'".format(project, mod, project))
            closure = _external_module_closure(dep_modules, dep_app.name, mod)
            mconf = dep_modules[mod]
            app.modules["{}:{}".format(project, mod)] = {
                "external": True,
                "depends": [],
                "libs": [],
                "_resolved_export_libs": closure,
                "_resolved_export_defines": mconf.get("_resolved_export_defines", [])[:],
                "_resolved_export_flags": mconf.get("_resolved_export_flags", [])[:],
                "_resolved_export_link": mconf.get("_resolved_export_link", [])[:],
            }

def build_modules_conf(app, specific_modules=None, conditionals=None):
    """ @brief build modules from application configuration
        @param app the application configuration module
        @param specific_modules_list build specific modules instead of all
        @param conditionals list of conditional modules to be added to the build
        @return list
    """
    specific_modules = list(specific_modules or [])
    conditionals = list(conditionals or [])
    if not hasattr(app, "modules"):
        raise RuntimeError("App's configuration file should have modules")
    modes = conf.get_app_modes(app)
    conf.check_unknown_app_conf_keys(app, modes)
    conf.check_unknown_conf_keys(get_module_merged_with_conditionals(app), modes)
    conditionals.extend(get_conditionals_from_env(app))
    modules = {}
    if specific_modules and specific_modules[0] != '':
        app_modules = app.modules
        # if a conditional is in specific module list, add conditionals to list of modules
        if has_conditional_in_modules_list(app.conditional_modules, specific_modules):
            app_modules = get_module_merged_with_conditionals(app)
        fill_modlist_from_modules(app_modules, specific_modules, modules)
    else:
        modules = app.modules
    # Add specific conditional modules
    all_modules = get_module_merged_with_conditionals(app)
    for modname in conditionals:
        fill_modlist_from_modules(all_modules, [modname], modules)
    # Get every dependencies configuration for modules
    resolve_modules_dependencies(modules)
    return modules
