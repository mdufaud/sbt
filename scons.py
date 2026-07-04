from time import time
build_start_time = time()

# careful: Rewrites time module import
from SCons.Script import *

if GetOption("help"):
    Return()

# General utilities
from os import environ
from os import path as os_path
from shutil import which as shutil_which

# Pretty utility for verbose output
from pprint import PrettyPrinter
pp = PrettyPrinter(indent=2)

###############################################################################
# App settings
###############################################################################

from sbt.core import loader
from sbt.core import builder
from sbt.core import logger

from site_scons.sbt.build import modules
from site_scons.sbt.core import utils as build_utils

from site_scons.sbt.scons import utils as scons_utils
from site_scons.sbt.scons import state as scons_state
from site_scons.sbt.scons import context as scons_context
from site_scons.sbt.scons import env_factory
from site_scons.sbt.scons import env_methods

app = loader.load_app()

logger.info("building {}".format(app.name))
logger.info("building to: {}".format(builder.build_path))

if builder.verify_args(app) == False:
    Exit(1)

###############################################################################
# Modules setup
###############################################################################

modules_to_build = builder.get_modules()
modules_forced_to_build = builder.get_force_build_modules()

modules_lst = builder.get_modules_lst()
if modules_forced_to_build:
    modules_lst.extend(builder.get_force_build_modules_lst())

compiler = builder.build_compiler
build_platform = builder.build_platform

build_mode = builder.get_compile_mode()
distribution = builder.do_distribution()
verbose = builder.has_verbose()

libtype = builder.build_static_libs and "static" or "shared"
bin_ext = build_platform == "web" and ".html" or (build_platform == "windows" and ".exe" or "")

modules_options = env_factory.compute_modules_options(
    build_platform, libtype, build_mode, compiler, builder
)

compile_commands = build_utils.is_opt("compile_commands", "1")

if verbose:
    logger.info("modules: {}".format(modules_lst or "all"))
    logger.info("platform: " + build_platform)
    logger.info("compiler: " + builder.build_compiler_version)
    logger.info("machine: " + builder.build_machine)
    logger.info("mode: " + build_mode)
    logger.info("tests: " + (builder.build_tests and "yes" or "no"))
    logger.info("libraries: " + (builder.build_static_libs and "static" or "shared"))
    logger.info("address sanitizer: " + (builder.build_asan and "yes" or "no"))
    logger.info("undefined behavior sanitizer: " + (builder.build_ubsan and "yes" or "no"))
    logger.info("thread sanitizer: " + (builder.build_tsan and "yes" or "no"))
    logger.info("leak sanitizer: " + (builder.build_lsan and "yes" or "no"))
    logger.info("memory sanitizer: " + (builder.build_msan and "yes" or "no"))
    logger.info("hwaddress sanitizer: " + (builder.build_hwasan and "yes" or "no"))
    logger.info("coverage: " + (builder.build_coverage and "yes" or "no"))

# Resolve cross-project `project:module` depends into synthetic local modules
try:
    modules.resolve_external_modules(
        app, os_path.join(builder.build_root_path, ".sbt-deps"), modules_options
    )
except RuntimeError as e:
    logger.error(str(e))
    Exit(1)

# Get modules configuration for this build
try:
    build_modules = modules.build_modules_conf(app, specific_modules=modules_lst)
except RuntimeError as e:
    logger.error(str(e))
    Exit(1)

# Checking module availability on platforms and build selectors
deleted_modules = modules.check_platform(build_modules, build_platform, modules_options)
for mod in deleted_modules:
    logger.warning("module '{}' excluded from this build (platform/selector)".format(mod))

# Checking module availability for the requested link mode (static/dynamic)
deleted_modules = modules.check_linkage(build_modules, builder.liblink)
for mod in deleted_modules:
    logger.warning("module '{}' cannot compile in {} link mode".format(mod, builder.liblink))

if not build_modules:
    Exit(0)

# Some distribution types only generate metadata files (no compilation needed).
# Exit early so the user doesn't need local dev deps installed.
_NO_COMPILE_DIST_TYPES = {"docker", "pacman"}
_dist_type = build_utils.get_opt("dist", "")
if distribution and _dist_type in _NO_COMPILE_DIST_TYPES:
    builder.distribute_app(app, build_modules)
    Exit(0)

###############################################################################
# Package manager dependencies
###############################################################################

pkg_manager_name = builder.get_pkgdep()
if pkg_manager_name:
    def collect_packages(extlibs):
        packages, missing_packages = modules.get_modules_packages(app, pkg_manager_name, extlibs)
        for missing in missing_packages:
            logger.warning("external library '{}' not declared in packet manager '{}'".format(missing, pkg_manager_name))
        return packages
    try:
        modules_extlibs = modules.get_modules_extlibs(app, build_modules, build_platform)
        packages = collect_packages(modules_extlibs)
    except RuntimeError as e:
        logger.error(str(e))
        Exit(1)
    deps = set(packages.keys())
    if builder.build_tests:
        test_extlibs = modules.get_extlibs_versions(app, getattr(app, "test_extlibs", []))
        deps.update(collect_packages(test_extlibs).keys())
    if builder.build_demo:
        demo_extlibs = modules.get_extlibs_versions(app, getattr(app, "demo_extlibs", []))
        deps.update(collect_packages(demo_extlibs).keys())
    logger.info("dependencies:")
    print(" ".join(deps))
    Return()

###############################################################################
# Build environment
###############################################################################

global_libs = getattr(app, "libs", [])
if verbose:
    logger.debug("modules configuration:")
    pp.pprint(build_modules)
    if global_libs:
        logger.debug("libs:")
        pp.pprint(global_libs)
    print()

base_env = Environment(
    # binaries path
    ENV = environ,
    # c compile flags
    CFLAGS = getattr(app, 'c_flags', []),
    # c++ compile flags
    CXXFLAGS = getattr(app, 'cxx_flags', []),
    # c and c++ compile flags
    CPPFLAGS = getattr(app, 'flags', []),
    # extra #define for inside the code
    CPPDEFINES = getattr(app, 'defines', []),
    # link flags - explicitly add -L flags to ensure extlib paths are searched before system paths
    LINKFLAGS = [f"-L{builder.build_lib_path}", f"-L{builder.build_extlib_lib_path}"] + getattr(app, 'link', []),
    # link flags for binaries
    BIN_LINKFLAGS = getattr(app, 'bin_link', []),
    # headers path
    CPPPATH = [builder.build_extlib_hdr_path],
    # libraries path
    LIBPATH = [builder.build_lib_path, builder.build_extlib_lib_path],
    # libraries name
    LIBS = global_libs,
    # extra key for modules to build
    APP_MODULES_BUILD = build_modules.keys(),
    COMPILATIONDB_USE_ABSPATH = True,
    # scons tools
    tools = [
        # general utils
        'tar',
        'zip',
        'textfile',
        # linux c compiler
        'gcc',
        'cc',
        # linux c++ compiler
        'g++',
        'cxx',
        # linux assembly compiler
        'nasm',
        # linux linker
        'gnulink',
        # linux static archiver
        'ar'
    ]
)

# Add defines from command line arguments: def=NAME=VALUE
for key, value in ARGLIST:
    if key == "def":
        base_env.Append(CPPDEFINES=[value])

# Build output
if not verbose:
    base_env.Replace(
        SHCCCOMSTR = "compiling shared C: $SOURCE",
        SHCXXCOMSTR = "compiling shared C++: $SOURCE",
        SHLINKCOMSTR = "linking shared library: $TARGET",
        CCCOMSTR = "compiling C: $SOURCE",
        CXXCOMSTR = "compiling C++: $SOURCE",
        ARCOMSTR = "generating static lib: $TARGET",
        RANLIBCOMSTR = "indexing static lib: $TARGET",
        LINKCOMSTR = "linking object files into executable: $TARGET",
    )

# Absolute RUNPATH dirs outside the build tree ($ORIGIN-relative ones are computed
# per-artifact in env_methods, which consumes this via base_env["RPATH_EXTRA_DIRS"]).
rpath_extra_dirs = []
if not distribution \
    and not compiler in ("mingw", "em", "ndk"):
    # vcpkg extlibs need libstdc++.so.6; under musl the loader would grab the host's
    # glibc one and fail relocations, so point RPATH at the musl toolchain's libstdc++.
    if builder.libc == "musl" and not builder.build_static_libs:
        libstdcxx_dir = builder.probe_libstdcxx_dir()
        if libstdcxx_dir:
            rpath_extra_dirs.append(libstdcxx_dir)
    # Cross-compiling linkers (musl, aarch64...) don't resolve transitive shared
    # library dependencies via -L or -rpath. Adding -rpath-link lets the linker
    # find libs at link time (no runtime effect).
    if builder.is_cross_building():
        base_env.Append(
            LINKFLAGS = [
                '-Wl,-rpath-link=' + os_path.abspath(builder.build_lib_path),
                '-Wl,-rpath-link=' + os_path.abspath(builder.build_extlib_lib_path),
            ],
        )
base_env["RPATH_EXTRA_DIRS"] = rpath_extra_dirs

if build_platform == "windows":
    base_env.Append(
        LIBPATH = [builder.build_extlib_bin_path]
    )

###############################################################################
# Compiler settings
###############################################################################

compiler = builder.build_compiler

if compiler == "gcc":
    from site_scons.sbt.scons.compilers import gcc as compiler_gcc
    compiler_gcc.load_in_env(base_env)
elif compiler == "clang":
    from site_scons.sbt.scons.compilers import clang as compiler_clang
    compiler_clang.load_in_env(base_env)
elif compiler == "mingw":
    from site_scons.sbt.scons.compilers import mingw as compiler_mingw
    compiler_mingw.load_in_env(base_env)
elif compiler == "zig":
    from site_scons.sbt.scons.compilers import zig as compiler_zig
    compiler_zig.load_in_env(base_env)
elif compiler == "em":
    from site_scons.sbt.scons.compilers import emscripten as compiler_emscripten
    compiler_emscripten.load_in_env(base_env)
elif compiler == "ndk":
    from site_scons.sbt.scons.compilers import ndk as compiler_ndk
    compiler_ndk.load_in_env(base_env)

ccache = ""
if not build_utils.is_opt("nocache"):
    ccache = shutil_which("ccache") and "ccache " or ""
    if verbose and ccache:
        logger.info("using ccache at: {}".format(shutil_which("ccache")))

    if not ccache:
        # Cache compile build with md5
        scons_cache_path = os_path.join(builder.build_root_path, '.scons_cache')
        if verbose:
            logger.info("using scons cache at: {}".format(scons_cache_path))
        CacheDir(scons_cache_path)

base_env.Prepend(
    CC = ccache,
    CXX = ccache,
    AR = ccache,
    RANLIB = ccache,
)

if compiler != "mingw" and compiler != "ndk" and not builder.is_msys():
    base_env.Replace(SHLIBVERSION = app.version)

###############################################################################
# General app configurations
###############################################################################

# add $platform-[flags/defines/link/libs]
# add $libtype-[flags/defines/link/libs]
# add $mode-[flags/defines/link/libs]
# add $compiler-[flags/defines/link/libs]
# add $libc-[flags/defines/link/libs]
# and their pairwise combinations

if verbose:
    logger.debug(f"looking for app configurations:")

default_app_conf_to_get = (build_platform, libtype, f"mode_{build_mode}", compiler, builder.libc, builder.build_machine)
env_factory.add_combination_app_conf_to_env(base_env, app, default_app_conf_to_get)

###############################################################################
# Scons options
###############################################################################

is_dry_run = bool(GetOption("no_exec"))

num_jobs = GetOption("num_jobs")
if num_jobs <= 1:
    from multiprocessing import cpu_count
    num_jobs = cpu_count()
    if num_jobs > 3:
        num_jobs -= 2
    SetOption("num_jobs", num_jobs)

if compile_commands:
    compilation_db_path = os_path.join(builder.build_path, "compile_commands.json")
    try:
        base_env.Tool('compilation_db')
        # base_env["COMPILATIONDB_PATH_FILTER"] = f"*[!{builder.build_path}].*"
        base_env.CompilationDatabase(compilation_db_path)
    except Exception as e:
        logger.warning(e)
        pass

# Decides when to recompile - removing slow md5 in favor of timestamps
# Decider('timestamp-newer')
# Decider('MD5')
Decider('MD5-timestamp')

###############################################################################
# Build context
###############################################################################

build_state = scons_state.BuildState(verbose)

modules.resolve_modules_exports(build_modules, modules_options)

ctx = scons_context.BuildContext(
    app = app,
    state = build_state,
    base_env = base_env,
    build_modules = build_modules,
    modules_options = modules_options,
    default_app_conf_to_get = default_app_conf_to_get,
    build_platform = build_platform,
    modules_lst = modules_lst,
    is_dry_run = is_dry_run,
    bin_ext = bin_ext,
    verbose = verbose,
    distribution = distribution,
)

env_methods.register_methods(base_env, ctx)

###############################################################################
# Build
###############################################################################

# sorting build order by module dependencies size
modules_build_order = list(build_modules.values())
modules_build_order.sort(key=lambda obj: len(obj["depends"]))

# Configure env and call scons.py from every configured module
built = {}
for conf in modules_build_order:
    modname = conf["modname"]
    if conf.get("external"):
        # synthetic cross-project module: no scons.py to compile, link metadata only
        continue
    module_script_path = os_path.join(builder.build_modules_path, modname, "scons.py")
    if not os_path.isfile(module_script_path):
        logger.error("module '{}' declared but {} missing".format(modname, module_script_path))
        Exit(1)
    logger.info("building module: {}".format(modname))
    env = env_factory.create_module_env(conf, ctx,
        depends=conf.get("depends", []),
        do_inherit_depends_defines=conf.get("inherit-depends-defines", False),
        do_inherit_depends_links=conf.get("inherit-depends-links", False),
        do_inherit_depends_flags=conf.get("inherit-depends-flags", False),
        # it is quite obvious you might want the libs generated from your dependencies
        do_inherit_depends_generated_libs=conf.get("inherit-depends-generated-libs", True),
    )
    # some helpful debug when building
    if verbose:
        logger.debug("needed libraries:")
        pp.pprint([str(s) for s in env['LIBS']])
        logger.debug("needed headers:")
        pp.pprint([str(s) for s in env['CPPPATH']])
        package_configs = conf.get("pkg-configs", [])
        if package_configs:
            logger.debug("needed packages configs")
            pp.pprint(package_configs)
        parse_configs = conf.get("parse-configs", [])
        if parse_configs:
            logger.debug("needed specific packages configs")
            pp.pprint(parse_configs)
    # install module/[etc|include|share] to build/[etc|include|share] (build-time nodes)
    for resource_dir in ("etc", "include", "share"):
        scons_utils.install_module_res_into_build(env, modname, resource_dir, resource_dir, must_exist=False)
        if builder.build_demo:
            scons_utils.install_module_res_into_build(env, modname, f"demo/{resource_dir}", resource_dir, must_exist=False)
    # read module's scons script file
    module_format_name = env['APP_MODULE_FORMAT_NAME']
    built[modname] = SConscript(Dir(builder.build_modules_path).Dir(modname).File("scons.py"),
                                variant_dir=os_path.join(builder.build_obj_path, modname),
                                duplicate=0,
                                exports=['env'])
    # fill module configurations with what was actually used
    conf["libs"] = env['LIBS']
    conf["flags"] = env['CPPFLAGS']
    conf["link"] = env['LINKFLAGS']
    conf["defines"] = env["CPPDEFINES"]
    if verbose:
        logger.debug(f"Final configuration for module {modname}")
        pp.pprint(conf)
    if verbose and len(modules_build_order) > 1:
        print("")

###############################################################################
# Combined library
###############################################################################

if builder.build_combined and build_state.lib_objects:
    # collect all pre-compiled objects from all built modules
    combined_objects = []
    for conf in modules_build_order:
        combined_objects.extend(build_state.lib_objects.get(conf["modname"], []))

    if combined_objects:
        # collect external libs (exclude our own generated libs)
        internal_lib_names = set()
        for libs_info_list in build_state.generated_libs.values():
            for lib_info in libs_info_list:
                internal_lib_names.add(lib_info["name"])

        combined_external_libs = []
        seen_libs = set()
        for conf in modules_build_order:
            for lib in conf.get("libs", []):
                lib_str = str(lib)
                if lib_str not in seen_libs and lib_str not in internal_lib_names:
                    combined_external_libs.append(lib)
                    seen_libs.add(lib_str)

        combined_env = base_env.Clone()
        combined_env.Replace(LIBS=combined_external_libs)
        for conf in modules_build_order:
            combined_env.AppendUnique(
                CPPPATH=[os_path.join(builder.build_modules_path, conf["modname"], "include")]
            )

        combined_lib_path = os_path.join(builder.build_lib_path, app.name)
        if builder.build_static_libs:
            NoCache(combined_env.StaticLibrary(combined_lib_path, combined_objects))
        else:
            NoCache(combined_env.SharedLibrary(combined_lib_path, combined_objects))

        logger.info("combined library target registered: {}".format(app.name))

###############################################################################
# Windows transitive DLL collection
###############################################################################

# Shared Windows builds need the mingw runtime + extlib DLLs copied next to the
# binaries. Model it as a graph node depending on the built binaries (instead of
# the former atexit side effect) so it honors --dry-run/clean and only re-runs
# when a binary changes.
if builder.build_platform == "windows" and not builder.build_static_libs:
    dll_dependency_bins = [
        artefact["path"]
        for registry in (build_state.generated_bins, build_state.generated_tests, build_state.generated_demos)
        for artefacts in registry.values()
        for artefact in artefacts
    ]
    if dll_dependency_bins:
        def _collect_dlls(target, source, env):
            builder.copy_dll_to_build(merge_built())
            with open(str(target[0]), "w"):
                pass
        dll_stamp = os_path.join(builder.build_path, ".dll_collect.stamp")
        dll_collect_node = base_env.Command(dll_stamp, dll_dependency_bins, _collect_dlls)
        NoCache(dll_collect_node)

if verbose:
    logger.debug(f"total targets registered: {len(build_state.targets)}")

###############################################################################
# Scons progress build output
###############################################################################

# scons_utils.build_add_progress_bar(targets)

progress_bar_fun = scons_utils.get_progress_bar_function(build_state.targets)
if progress_bar_fun:
    Progress(progress_bar_fun, interval=1)


###############################################################################
# Scons after build
###############################################################################

import atexit

def merge_built():
    merged = {}
    for d in [build_state.generated_bins, build_state.generated_tests, build_state.generated_demos]:
        for key, value in d.items():
            merged.setdefault(key, []).extend(value)
    return merged

def after_build():
    success, failures_message = scons_utils.build_status()
    scons_utils.build_print_status(success, failures_message, build_start_time)
    if is_dry_run:
        return
    if success and hasattr(app, "on_build_success"):
        scons_utils.build_print_built(
            build_state.generated_bins, build_state.generated_demos, build_state.generated_tests
        )
        app.on_build_success(build_modules, builder)
    elif hasattr(app, "on_build_fail"):
        app.on_build_fail(build_modules, builder)
    builder.symlink_build()
    if success and distribution:
        builder.distribute_app(app, build_modules)
    if compile_commands:
        builder.safe_symlink(compilation_db_path, os_path.join(builder.build_entry_path, "compile_commands.json"))


atexit.register(after_build)

logger.info("starting scons build (took {:.3f} sec)".format(time.time() - build_start_time))
