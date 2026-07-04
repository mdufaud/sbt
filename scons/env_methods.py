"""SCons environment methods for module builds.

Every function defined here becomes an env.method() available in each module's
scons.py once register_methods(base_env, ctx) has been called.  The BuildContext
*ctx* is captured by the closure wrappers inside register_methods(), so the
private implementation functions receive it as an explicit parameter.

Public API (methods available in module scons.py scripts):
  env.build_lib(src, name=None, static=None, **kwargs)
  env.build_bin(src, name=None, libs=[], android_dir=None, static_stdlib=False, static_libs=False, **kwargs)
  env.build_test(src, name=None, libs=[], static_stdlib=False, static_libs=False, **kwargs)
  env.build_demo(src, name, libs=[], android_dir=None, static_stdlib=False, static_libs=False, **kwargs)
  # static_libs: True (wrap all LIBS, requires .a files) or list[str] (wrap named libs only)
  env.build_demos(srcs, **kwargs)
  env.build_cpp_modules(src, **kwargs)
  env.export_test(includes=[], resources=[])
  env.copy_into_build(src, dst)
  env.file_basename(path)
  env.git_clone(url, branch, dest, recursive=False)
  env.file_replace(path, dic)
  env.build_replace(to_replace, replace_dic)
  env.create_module_env(**kwargs)
  env.pkg_config(config)
  env.parse_config(config)
  env.find_in_file(src, search_str)
  env.filter_files(files_lst, filter_lst)
  env.is_opt(name, default="")
  env.get_opt(name, default="")
  env.module_name()
  env.module_format_name()
  env.module_conf()
  env.module_dir()
  env.modules_to_build()
  env.app()
  env.builder()
  env.logger()
  env.is_dry_run()
"""

from glob import glob
from os import path as os_path

from SCons.Script import NoCache

from sbt.core import builder
from sbt.core import logger
from site_scons.sbt.build import cpp_module_parse as build_cpp_modules
from site_scons.sbt.scons import utils as scons_utils
from site_scons.sbt.scons import android as scons_android
from site_scons.sbt.scons import cpp_modules as scons_cpp_modules
from site_scons.sbt.scons import env_factory


###############################################################################
# Private helpers
###############################################################################

def _origin_rpath_flags(env, artifact_dir):
    """$ORIGIN-relative -rpath flags so an artifact in *artifact_dir* finds its libs.

    Relpath to the lib dirs follows the layout and survives `make install` (bin stays
    a sibling of lib). Each lib needs its own rpath: DT_RUNPATH is not inherited from
    the loader. Emitted as LINKFLAGS via Literal() because the RPATH var routes through
    RDirs and consumes the literal $ORIGIN.
    """
    if builder.do_distribution() or builder.build_compiler in ("mingw", "em", "ndk"):
        return []
    flags = []
    seen = set()
    for lib_dir in (builder.build_lib_path, builder.build_extlib_lib_path):
        rel = os_path.relpath(lib_dir, artifact_dir)
        origin = "$ORIGIN" if rel == os_path.curdir else os_path.join("$ORIGIN", rel)
        if origin not in seen:
            seen.add(origin)
            flags.append(env.Literal("-Wl,-rpath," + origin))
    for extra in env.get("RPATH_EXTRA_DIRS", []):
        flags.append(env.Literal("-Wl,-rpath," + extra))
    return flags


def _android_build_apk(env, src, name, output_dir, libs, ctx, android_dir=None, **kwargs):
    """Orchestrate building an Android APK from the given source(s).

    Stages a Gradle project from templates, compiles a SharedLibrary, copies
    the .so into jniLibs, then runs gradle assembleDebug.
    """
    module_dir = env['APP_MODULE_DIR']

    apk_env = env.Clone()
    apk_env.Prepend(LIBS=libs)
    scons_utils.add_env_app_conf(ctx.app, apk_env, "demo")
    for app_conf in ctx.default_app_conf_to_get:
        scons_utils.add_env_app_conf(ctx.app, apk_env, "demo", app_conf)

    module_android_dir = os_path.join(module_dir, android_dir) if android_dir else None
    project_name = ctx.app.name
    config = scons_android.load_override_config(module_android_dir, project_name=project_name) if module_android_dir else {
        "namespace": f"{project_name}.android.terminal",
        "native_activity": False,
    }

    sanitized_name = name.replace("-", "_").lower()
    extra_srcs = []
    ndk_root = builder.get_ndk_root()

    if config["native_activity"]:
        glue_src = os_path.join(
            ndk_root, "sources", "android", "native_app_glue", "android_native_app_glue.c"
        )
        extra_srcs.append(glue_src)
        apk_env.Append(SHLINKFLAGS=[
            '-u', 'ANativeActivity_onCreate',
            '-Wl,--no-undefined',
            '-static-libstdc++',
        ])
    else:
        bridge_src = scons_android.stage_bridge_source(
            os_path.join(builder.build_path, "apk-obj", sanitized_name, "terminal_bridge.cpp"),
            config["namespace"], project_name,
        )
        extra_srcs.append(bridge_src)
        apk_env.Append(SHLINKFLAGS=['-Wl,--no-undefined', '-static-libstdc++'])
        for lib in ['android', 'log']:
            if lib not in apk_env.get('LIBS', []):
                apk_env.Append(LIBS=[lib])

    all_srcs = [src] if isinstance(src, str) else list(src)
    objects = apk_env.SharedObject(all_srcs)
    for extra_src in extra_srcs:
        basename = os_path.splitext(os_path.basename(extra_src))[0]
        obj_path = os_path.join(builder.build_path, "apk-obj", sanitized_name, basename)
        objects.extend(apk_env.SharedObject(obj_path, extra_src))

    so_path = os_path.join(builder.build_lib_path, sanitized_name)
    so_lib = apk_env.SharedLibrary(so_path, objects)

    staging_dir = os_path.join(builder.build_path, "apk-staging", sanitized_name)
    apk_output = os_path.join(output_dir, f"{name}.apk")
    android_permissions = env['APP_MODULE_CONF'].get('android-permissions', [])

    def _stage_and_build_apk(target, source, env):
        scons_android.stage_gradle_project(
            staging_dir, name, module_android_dir, permissions=android_permissions,
            project_name=project_name,
        )
        scons_android.copy_so_to_jnilibs(staging_dir, str(source[0]), sanitized_name)
        return scons_android.build_apk(staging_dir, str(target[0]))

    apk_cmd = apk_env.Command(apk_output, so_lib, _stage_and_build_apk)
    apk_env.AlwaysBuild(apk_cmd)
    ctx.state.add_targets(src)
    return apk_cmd


###############################################################################
# Build method implementations
###############################################################################

def _get_static_stdlib_flags():
    """Return per-compiler flags to link the C++ stdlib statically.

    Returns [] when it is already handled globally (build_static_libs, musl)
    or when the compiler/platform embeds its stdlib unconditionally (em, zig, ndk).
    """
    if builder.build_static_libs or builder.libc == "musl":
        return []
    compiler = builder.build_compiler
    if compiler in ("gcc", "mingw"):
        return ["-static-libgcc", "-static-libstdc++"]
    if compiler == "clang":
        return ["-static-libstdc++"]
    # em, ndk, zig: stdlib always statically embedded — no extra flags needed
    return []


def _wrap_libs_static(env, static_libs):
    """Wrap selected LIBS with -Wl,-Bstatic/-Bdynamic to force static linking.

    static_libs can be:
      True        - wrap every string lib in LIBS (requires .a files to exist)
      list[str]   - wrap only the named libs; others remain in LIBS unchanged

    File-node LIBS (explicit .a/.so paths) are always left in LIBS untouched.
    No-op when build_static_libs is already set (entire build is static)
    or on compilers where the flag is irrelevant (em, zig).

    The wrapped flags are injected AFTER $SOURCES in LINKCOM so that static
    archives (.a) are resolved correctly (linker must see object undefined
    references before scanning the archive).
    """
    if builder.build_static_libs or builder.build_compiler in ("em", "zig"):
        return
    all_libs = list(env["LIBS"])
    if static_libs is True:
        to_wrap = [l for l in all_libs if isinstance(l, str)]
        keep = [l for l in all_libs if not isinstance(l, str)]
    else:
        wrap_set = set(static_libs)
        to_wrap_from_libs = [l for l in all_libs if isinstance(l, str) and l in wrap_set]
        keep = [l for l in all_libs if not isinstance(l, str) or l not in wrap_set]
        # Libs named in static_libs but not in LIBS are added directly to the static section
        found = set(to_wrap_from_libs)
        to_wrap = to_wrap_from_libs + [l for l in static_libs if l not in found]
    if not to_wrap:
        return
    env.Replace(LIBS=keep)
    wrapped_str = " ".join(["-Wl,-Bstatic"] + [f"-l{l}" for l in to_wrap] + ["-Wl,-Bdynamic"])
    env["_SBT_STATIC_LIBFLAGS"] = wrapped_str
    if "${_SBT_STATIC_LIBFLAGS}" not in str(env["LINKCOM"]):
        env["LINKCOM"] = str(env["LINKCOM"]) + " ${_SBT_STATIC_LIBFLAGS}"


def _clone_env_with_new_libs(self, libs, static_stdlib):
    """Clone the module env for a bin/test/demo artifact: prepend LIBS + static stdlib."""
    artifact_env = self.Clone()
    artifact_env.Prepend(LIBS=libs)
    if static_stdlib:
        artifact_env.Append(LINKFLAGS=_get_static_stdlib_flags())
    return artifact_env


def _apply_bin_linkflags(self, env, rpath_target):
    """Append BIN_LINKFLAGS and the $ORIGIN rpath flags shared by bin/test/demo links."""
    if self['BIN_LINKFLAGS']:
        env.Append(LINKFLAGS=self['BIN_LINKFLAGS'])
    env.Append(LINKFLAGS=_origin_rpath_flags(env, rpath_target))


def _static_link_into_shared_lib(self, lib_env, static_libs):
    """Whole-archive static-only libs into the shared lib; drop them from consumers.

    PE has no symbol interposition: an archive linked into both this DLL and a
    consumer yields two copies of any global, breaking libs with process-global
    state. Bundling the full archive into the DLL keeps a single copy.

    Windows shared build only; elsewhere the libs link normally.
    """
    if builder.build_platform != "windows" or builder.build_static_libs:
        return
    drop = set(static_libs)
    archives = [os_path.join(builder.build_extlib_lib_path, f"lib{l}.a") for l in static_libs]
    self["LIBS"] = [l for l in self["LIBS"] if l not in drop]
    lib_env["LIBS"] = [l for l in lib_env["LIBS"] if l not in drop]
    lib_env.Append(LINKFLAGS=["-Wl,--whole-archive"] + archives + ["-Wl,--no-whole-archive"])


def _build_lib(self, src, name, static, ctx, **kwargs):
    static_libs = kwargs.pop("static_libs", None)
    module_name = self['APP_MODULE_NAME']
    if name is None:
        name = self["APP_MODULE_FORMAT_NAME"]

    lib_path = os_path.join(builder.build_lib_path, name)
    cpp_mods, build_kwargs = scons_cpp_modules.extract_imports(kwargs)
    if cpp_mods:
        scons_cpp_modules.enable(self, ctx)

    if (static is not None and static is True) or builder.build_static_libs:
        objects = scons_cpp_modules.build_objects(self, src, ctx, cpp_modules=cpp_mods, **build_kwargs)
        lib = NoCache(self.StaticLibrary(lib_path, objects, **build_kwargs))
    else:
        objects = scons_cpp_modules.build_objects(self, src, ctx, shared=True, cpp_modules=cpp_mods, **build_kwargs)
        lib_env = self.Clone()
        lib_env.Append(LINKFLAGS=_origin_rpath_flags(lib_env, builder.build_lib_path))
        if static_libs:
            _static_link_into_shared_lib(self, lib_env, static_libs)
        lib = NoCache(lib_env.SharedLibrary(lib_path, objects, **build_kwargs))

    ctx.state.add_targets(src)
    ctx.state.add_generated("lib", ctx.state.generated_libs, module_name, name, lib_path)

    if builder.build_combined:
        ctx.state.lib_objects.setdefault(module_name, []).extend(
            objects if isinstance(objects, list) else [objects]
        )
    return lib


def _build_bin(self, src, name, libs, android_dir, ctx, **kwargs):
    static_stdlib = kwargs.pop("static_stdlib", False)
    static_libs = kwargs.pop("static_libs", False)
    module_name = self['APP_MODULE_NAME']
    if name is None:
        name = self['APP_MODULE_FORMAT_NAME']

    if ctx.build_platform == "android":
        apk = _android_build_apk(self, src, name, builder.build_bin_path, libs, ctx, android_dir, **kwargs)
        ctx.state.add_generated(
            "bin", ctx.state.generated_bins, module_name,
            f"{name}.apk", os_path.join(builder.build_bin_path, f"{name}.apk")
        )
        return apk

    bin_env = _clone_env_with_new_libs(self, libs, static_stdlib)
    if static_libs:
        _wrap_libs_static(bin_env, static_libs)

    cpp_mods, build_kwargs = scons_cpp_modules.extract_imports(kwargs)
    if cpp_mods:
        scons_cpp_modules.enable(bin_env, ctx)

    _apply_bin_linkflags(self, bin_env, builder.build_bin_path)

    name += ctx.bin_ext
    bin_path = os_path.join(builder.build_bin_path, name)
    if cpp_mods:
        objects = scons_cpp_modules.build_objects(bin_env, src, ctx, cpp_modules=cpp_mods, **build_kwargs)
        result = bin_env.Program(bin_path, objects, **build_kwargs)
    else:
        result = bin_env.Program(bin_path, src, **build_kwargs)

    ctx.state.add_targets(src)
    ctx.state.add_generated("bin", ctx.state.generated_bins, module_name, name, bin_path)
    return result


def _build_test(self, src, name, libs, ctx, **kwargs):
    static_stdlib = kwargs.pop("static_stdlib", False)
    static_libs = kwargs.pop("static_libs", False)
    if not builder.build_tests:
        return None
    module_name = self['APP_MODULE_NAME']
    if ctx.modules_lst and module_name not in ctx.modules_lst:
        return None

    test_env = _clone_env_with_new_libs(self, libs, static_stdlib)
    cpp_mods, build_kwargs = scons_cpp_modules.extract_imports(kwargs)
    if cpp_mods and not builder.is_cpp_modules:
        return None
    conf = self['APP_MODULE_CONF']

    exported_test_cpppaths = []
    for dep_modname in conf.get("depends", []):
        for include_path in ctx.state.exported_test_includes.get(dep_modname, []):
            exported_test_cpppaths.append(
                os_path.join(builder.build_modules_path, dep_modname, include_path)
            )
        for resource_path in ctx.state.exported_test_resources.get(dep_modname, []):
            resource_src = os_path.join(builder.build_modules_path, dep_modname, resource_path)
            resource_dst = os_path.join("test", "resources", dep_modname)
            if os_path.isfile(resource_src):
                resource_dst = os_path.join(resource_dst, os_path.basename(resource_path))
            scons_utils.install_module_res_into_build(
                test_env, dep_modname, resource_path, resource_dst, must_exist=False
            )
    scons_utils.prepend_unique_paths(test_env, "CPPPATH", exported_test_cpppaths)

    scons_utils.add_env_app_conf(ctx.app, test_env, "test")
    for app_conf in ctx.default_app_conf_to_get:
        scons_utils.add_env_app_conf(ctx.app, test_env, "test", app_conf)

    if cpp_mods:
        scons_cpp_modules.enable(test_env, ctx)

    if static_libs:
        _wrap_libs_static(test_env, static_libs)

    _apply_bin_linkflags(self, test_env, os_path.join(builder.build_test_path, "bin"))

    if name is None:
        name = self["APP_MODULE_FORMAT_NAME"]
    name += ctx.bin_ext
    test_path = os_path.join(builder.build_test_path, "bin", name)

    if cpp_mods:
        objects = scons_cpp_modules.build_objects(test_env, src, ctx, cpp_modules=cpp_mods, **build_kwargs)
        test = test_env.Program(test_path, objects, **build_kwargs)
    else:
        test = test_env.Program(test_path, src, **build_kwargs)

    ctx.state.add_targets(src)
    ctx.state.add_generated("test", ctx.state.generated_tests, module_name, name, test_path)
    return test


def _build_demo(self, src, name, libs, android_dir, ctx, **kwargs):
    static_stdlib = kwargs.pop("static_stdlib", False)
    static_libs = kwargs.pop("static_libs", False)
    if not builder.build_demo:
        return None
    module_name = self['APP_MODULE_NAME']
    if ctx.modules_lst and module_name not in ctx.modules_lst:
        return None

    if ctx.build_platform == "android":
        demo = _android_build_apk(self, src, name, builder.build_demo_path, libs, ctx, android_dir, **kwargs)
        ctx.state.add_generated(
            "demo", ctx.state.generated_demos, module_name,
            f"{name}.apk", os_path.join(builder.build_demo_path, f"{name}.apk")
        )
        return demo

    demo_env = _clone_env_with_new_libs(self, libs, static_stdlib)

    cpp_mods, build_kwargs = scons_cpp_modules.extract_imports(kwargs)
    scons_utils.add_env_app_conf(ctx.app, demo_env, "demo")
    for app_conf in ctx.default_app_conf_to_get:
        scons_utils.add_env_app_conf(ctx.app, demo_env, "demo", app_conf)

    if cpp_mods:
        scons_cpp_modules.enable(demo_env, ctx)

    if static_libs:
        _wrap_libs_static(demo_env, static_libs)

    _apply_bin_linkflags(self, demo_env, builder.build_demo_path)

    name += ctx.bin_ext
    demo_path = os_path.join(builder.build_demo_path, name)
    if cpp_mods:
        objects = scons_cpp_modules.build_objects(demo_env, src, ctx, cpp_modules=cpp_mods, **build_kwargs)
        demo = demo_env.Program(demo_path, objects, **build_kwargs)
    else:
        demo = demo_env.Program(demo_path, src, **build_kwargs)

    ctx.state.add_targets(src)
    ctx.state.add_generated("demo", ctx.state.generated_demos, module_name, name, demo_path)
    return demo


def _build_demos(self, srcs, **kwargs):
    for src in srcs:
        name = self.file_basename(src)
        self.build_demo(src, name=name, **kwargs)


def _build_cpp_modules_method(self, src, ctx, **kwargs):
    owner_module_name = self['APP_MODULE_NAME']
    if not builder.is_cpp_modules:
        raise RuntimeError(
            "C++ modules are not supported with compiler '{}' on this build target".format(
                builder.build_compiler
            )
        )
    local_kwargs = kwargs.copy()
    explicit_module_names = local_kwargs.pop('module_name', None)
    imports = scons_utils.as_list(local_kwargs.pop('imports', []))
    sources = scons_utils.as_list(src)
    backend = builder.cpp_modules_backend
    module_dir = self['APP_MODULE_DIR']

    if explicit_module_names is None:
        module_names = [
            build_cpp_modules.parse_module_name(
                build_cpp_modules.resolve_source_path(module_dir, s)
            )
            for s in sources
        ]
    else:
        module_names = scons_utils.as_list(explicit_module_names)

    if len(module_names) != len(sources):
        raise RuntimeError("module_name must match the number of C++ module sources")

    cppm_env = self.Clone()
    # Only enable on the clone used for compiling the module interface unit.
    # The parent env must NOT be mutated here: build_lib/build_test/build_demo
    # already call enable() themselves when cpp_modules= is passed, and mutating
    # self would inject -fmodules/-fmodule-mapper into every source registered
    # before this call (SCons is lazy: flags are evaluated at build time).
    scons_cpp_modules.enable(cppm_env, ctx)

    bmi_dir = build_cpp_modules.get_bmi_dir(backend, builder.build_path, ctx.is_dry_run)
    imported_objects = scons_cpp_modules.resolve_nodes(imports, ctx) if imports else []
    objects = []

    if backend == 'gcc':
        objects = scons_utils.as_list(cppm_env.Object(sources, **local_kwargs))
        if imported_objects:
            cppm_env.Depends(objects, imported_objects)
    elif backend == 'clang':
        for source, module_name in zip(sources, module_names):
            source_env = cppm_env.Clone()
            bmi_path = build_cpp_modules.get_bmi_path(backend, builder.build_path, module_name, ctx.is_dry_run)
            source_env.AppendUnique(CXXFLAGS=[f'-fmodule-output={bmi_path}'])
            source_objects = scons_utils.as_list(source_env.Object(source, **local_kwargs))
            if imported_objects:
                source_env.Depends(source_objects, imported_objects)
            objects.extend(source_objects)
    else:
        raise RuntimeError("unsupported C++ modules backend '{}'".format(backend))

    exported = ctx.state.exported_bmis.setdefault(owner_module_name, [])
    for module_name, object_node in zip(module_names, objects):
        if module_name not in exported:
            exported.append(module_name)
        ctx.state.cpp_modules[module_name] = {
            'owner': owner_module_name,
            'compiler': builder.build_compiler,
            'bmi_dir': bmi_dir,
            'bmi_path': build_cpp_modules.get_bmi_path(
                backend, builder.build_path, module_name, ctx.is_dry_run
            ),
            'objects': [object_node],
        }

    if backend == 'gcc':
        build_cpp_modules.write_gcc_mapper(builder.build_path, ctx.state.cpp_modules, ctx.is_dry_run)

    ctx.state.add_targets(src)
    return objects


def _export_test(self, includes, resources, ctx):
    module_name = self['APP_MODULE_NAME']
    if includes:
        normalized = [
            scons_utils.normalize_module_relative_path(module_name, p) for p in includes
        ]
        store = ctx.state.exported_test_includes.setdefault(module_name, [])
        for path in normalized:
            if path not in store:
                store.append(path)
    if resources:
        normalized = [
            scons_utils.normalize_module_relative_path(module_name, p) for p in resources
        ]
        store = ctx.state.exported_test_resources.setdefault(module_name, [])
        for path in normalized:
            if path not in store:
                store.append(path)


def _copy_into_build(self, src, dst, ctx):
    module_name = self['APP_MODULE_NAME']
    scons_utils.install_module_res_into_build(self, module_name, src, dst)


def _file_basename(self, path):
    return os_path.basename(os_path.splitext(str(path))[0])


def _git_clone(self, url, branch, dest, recursive, ctx):
    modname = self['APP_MODULE_NAME']
    if not os_path.isabs(dest):
        dest = os_path.join(builder.build_modules_path, modname, dest)
    ret = True
    if os_path.isdir(dest):
        logger.info("repository already cloned: {}".format(dest))
    else:
        logger.info("cloning repository: {} -> {}".format(url, dest))
        from subprocess import call as subprocess_call
        args = ['git', 'clone']
        if recursive:
            args.append("--recursive")
        args.extend(['--branch', branch, '--depth', '1', url, dest])
        if ctx.verbose:
            logger.info("git clone cmd: '{}'".format(" ".join(args)))
        if not ctx.is_dry_run:
            ret = subprocess_call(args) == 0
    if ret:
        ctx.state.cloned_git_repos.setdefault(modname, []).append(dest)
    return ret


def _replace_in_file(self, path, dic, ctx):
    module_name = self['APP_MODULE_NAME']
    if not os_path.isabs(path):
        path = os_path.join(builder.build_modules_path, module_name, path)
    logger.debug("replacing file: " + path)
    if not ctx.is_dry_run:
        scons_utils.fileinput_replace(path, dic)


def _replace_in_build(self, to_replace, replace_dic, ctx):
    module_name = self['APP_MODULE_NAME']
    files_to_replace = []
    for pattern in to_replace:
        ret = glob(os_path.join(builder.build_path, module_name, pattern), recursive=True)
        files_to_replace += ret if ret else [pattern]
    if ctx.verbose:
        logger.debug("replacing values in build files - {} files to replace".format(len(files_to_replace)))
    for path in files_to_replace:
        logger.debug("replacing file: " + path)
        if not ctx.is_dry_run:
            scons_utils.fileinput_replace(path, replace_dic)


def _create_module_env(self, ctx, **kwargs):
    return env_factory.create_module_env(self["APP_MODULE_CONF"], ctx, **kwargs)


def _pkg_config(self, config):
    return scons_utils.load_env_packages_config(self, [config])


def _parse_config(self, config):
    return scons_utils.parse_config_command(self, [config])


def _find_in_file(self, src, search_str, ctx):
    module_name = self['APP_MODULE_NAME']
    if not os_path.isabs(src):
        src = os_path.join(builder.build_modules_path, module_name, src)
    with open(src, 'r') as fd:
        for line in fd:
            if search_str in line:
                return True
    return False


def _filter_files(self, files_lst, filter_lst):
    return [f for f in files_lst if os_path.basename(str(f)) not in filter_lst]


###############################################################################
# Method registration
###############################################################################

def register_methods(base_env, ctx):
    """Attach all module build methods to *base_env*, capturing *ctx* via closure.

    After this call, every module's scons.py can access these methods on the
    *env* object exported to it via SConscript.
    """
    from site_scons.sbt.core import utils as build_utils

    # --- Artefact builders ---

    def build_lib(self, src, name=None, static=None, **kwargs):
        return _build_lib(self, src, name, static, ctx, **kwargs)

    def build_bin(self, src, name=None, libs=[], android_dir=None, **kwargs):
        return _build_bin(self, src, name, libs, android_dir, ctx, **kwargs)

    def build_test(self, src, name=None, libs=[], **kwargs):
        return _build_test(self, src, name, libs, ctx, **kwargs)

    def build_demo(self, src, name, libs=[], android_dir=None, **kwargs):
        return _build_demo(self, src, name, libs, android_dir, ctx, **kwargs)

    def build_demos(self, srcs, **kwargs):
        return _build_demos(self, srcs, **kwargs)

    def build_cpp_modules(self, src, **kwargs):
        return _build_cpp_modules_method(self, src, ctx, **kwargs)

    def export_test(self, includes=[], resources=[]):
        return _export_test(self, includes, resources, ctx)

    # --- File / path helpers ---

    def copy_into_build(self, src, dst):
        return _copy_into_build(self, src, dst, ctx)

    def file_basename(self, path):
        return _file_basename(self, path)

    def git_clone(self, url, branch, dest, recursive=False):
        return _git_clone(self, url, branch, dest, recursive, ctx)

    def file_replace(self, path, dic):
        return _replace_in_file(self, path, dic, ctx)

    def build_replace(self, to_replace, replace_dic):
        return _replace_in_build(self, to_replace, replace_dic, ctx)

    # --- Environment introspection / creation ---

    def create_module_env(self, **kwargs):
        return _create_module_env(self, ctx, **kwargs)

    def pkg_config(self, config):
        return _pkg_config(self, config)

    def parse_config(self, config):
        return _parse_config(self, config)

    def find_in_file(self, src, search_str):
        return _find_in_file(self, src, search_str, ctx)

    def filter_files(self, files_lst, filter_lst):
        return _filter_files(self, files_lst, filter_lst)

    # --- Register all methods ---

    base_env.AddMethod(build_lib, "build_lib")
    base_env.AddMethod(build_bin, "build_bin")
    base_env.AddMethod(build_test, "build_test")
    base_env.AddMethod(build_demo, "build_demo")
    base_env.AddMethod(build_demos, "build_demos")
    base_env.AddMethod(build_cpp_modules, "build_cpp_modules")
    base_env.AddMethod(export_test, "export_test")
    base_env.AddMethod(copy_into_build, "copy_into_build")
    base_env.AddMethod(file_basename, "file_basename")
    base_env.AddMethod(git_clone, "git_clone")
    base_env.AddMethod(file_replace, "file_replace")
    base_env.AddMethod(build_replace, "build_replace")
    base_env.AddMethod(create_module_env, "create_module_env")
    base_env.AddMethod(pkg_config, "pkg_config")
    base_env.AddMethod(parse_config, "parse_config")
    base_env.AddMethod(find_in_file, "find_in_file")
    base_env.AddMethod(filter_files, "filter_files")

    # Delegates to build_utils
    base_env.AddMethod(lambda self, *a, **kw: build_utils.is_opt(*a, **kw), "is_opt")
    base_env.AddMethod(lambda self, *a, **kw: build_utils.get_opt(*a, **kw), "get_opt")

    # Simple env accessors
    base_env.AddMethod(lambda self: self['APP_MODULE_NAME'], "module_name")
    base_env.AddMethod(lambda self: self['APP_MODULE_FORMAT_NAME'], "module_format_name")
    base_env.AddMethod(lambda self: self['APP_MODULE_CONF'], "module_conf")
    base_env.AddMethod(lambda self: self['APP_MODULE_DIR'], "module_dir")
    base_env.AddMethod(lambda self: self['APP_MODULES_BUILD'], "modules_to_build")

    # Shared singletons exposed on the env for convenience
    base_env.AddMethod(lambda self: ctx.app, "app")
    base_env.AddMethod(lambda self: builder, "builder")
    base_env.AddMethod(lambda self: logger, "logger")
    base_env.AddMethod(lambda self: ctx.is_dry_run, "is_dry_run")
