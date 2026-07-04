"""SCons-level C++20 module integration layer.

Pure Python helpers (BMI path computation, GCC mapper writing, module-name
parsing) live in sbt/build/cpp_modules.py.  This module bridges those helpers
with SCons build mechanics: Builder registration, compiler flags, Depends()
edges, and source/prebuilt-object splitting.
"""

from os import path as os_path

from sbt.core import builder
from site_scons.sbt.build import cpp_module_parse as build_cpp_modules
from site_scons.sbt.scons import utils as scons_utils


def register_suffixes(env):
    """Register .cppm and .ixx as valid C++ source suffixes in *env*."""
    cpp_suffixes = ['.cppm', '.ixx']
    for builder_name in ['Object', 'SharedObject']:
        object_builder = env['BUILDERS'][builder_name]
        cpp_action = object_builder.builder.action.generator['.cpp']
        cpp_emitter = object_builder.emitter['.cpp']
        for suffix in cpp_suffixes:
            object_builder.add_action(suffix, cpp_action)
            object_builder.add_emitter(suffix, cpp_emitter)
            if suffix not in object_builder.builder.src_suffix:
                object_builder.builder.src_suffix.append(suffix)
    env.AppendUnique(CPPSUFFIXES=cpp_suffixes)


def enable(env, ctx):
    """Enable C++20 module compilation flags on *env*.

    Registers .cppm/.ixx suffixes, sets the appropriate compiler flags for the
    active backend (gcc or clang), and returns the BMI cache directory path.
    Raises RuntimeError if the current compiler/target has no modules backend.
    """
    backend = builder.cpp_modules_backend
    if backend is None:
        raise RuntimeError(
            "C++ modules are not supported for compiler '{}' on this build target".format(
                builder.build_compiler
            )
        )
    register_suffixes(env)
    bmi_dir = build_cpp_modules.get_bmi_dir(backend, builder.build_path, ctx.is_dry_run)
    if backend == 'gcc':
        mapper_file = build_cpp_modules.write_gcc_mapper(
            builder.build_path, ctx.state.cpp_modules, ctx.is_dry_run
        )
        env.AppendUnique(CXXFLAGS=['-fmodules', f'-fmodule-mapper={mapper_file}'])
    elif backend == 'clang':
        clang_module_flags = [f'-fprebuilt-module-path={bmi_dir}']
        if builder.cpp_modules_compiler_major >= 22:
            clang_module_flags.append('-fno-modules-reduced-bmi')
        env.AppendUnique(CXXFLAGS=clang_module_flags)
    return bmi_dir


def split_inputs(env, src):
    """Split *src* into (sources_to_compile, prebuilt_object_nodes).

    Prebuilt objects (files whose suffix matches $OBJSUFFIX or $SHOBJSUFFIX)
    are passed through as-is; everything else is treated as a source to compile.
    """
    sources = []
    prebuilt = []
    object_suffixes = {env.subst('$OBJSUFFIX'), env.subst('$SHOBJSUFFIX')}
    for value in scons_utils.as_list(src):
        get_suffix = getattr(value, 'get_suffix', None)
        suffix = get_suffix() if get_suffix else os_path.splitext(str(value))[1]
        (prebuilt if suffix in object_suffixes else sources).append(value)
    return sources, prebuilt


def resolve_nodes(imports, ctx):
    """Resolve C++ module names in *imports* to their compiled object nodes.

    Looks up each name in ctx.state.cpp_modules (populated by build_cpp_modules
    env method).  Raises RuntimeError if any module has not been compiled yet.
    """
    missing = []
    resolved = []
    for name in scons_utils.dedupe_keep_order(scons_utils.as_list(imports)):
        info = ctx.state.cpp_modules.get(name)
        if info is None:
            missing.append(name)
        else:
            resolved.extend(info.get('objects', []))
    if missing:
        raise RuntimeError("missing exported C++ modules: {}".format(", ".join(missing)))
    return scons_utils.dedupe_keep_order(resolved)


def extract_imports(kwargs):
    """Pop the 'cpp_modules' key from *kwargs*.

    Returns (imports_list, remaining_kwargs) so callers can forward only the
    clean kwargs to SCons builder functions.
    """
    local_kwargs = kwargs.copy()
    imports = scons_utils.as_list(local_kwargs.pop('cpp_modules', []))
    return imports, local_kwargs


def build_objects(env, src, ctx, shared=False, cpp_modules=[], **kwargs):
    """Compile *src* to object nodes, wiring C++ module Depends() edges.

    Prebuilt object nodes (matched by suffix) pass through unchanged.
    When *cpp_modules* is non-empty, a Depends() edge is added from the
    compiled objects to the resolved C++ module object nodes.
    """
    sources, prebuilt = split_inputs(env, src)
    objects = []
    if sources:
        builder_func = env.SharedObject if shared else env.Object
        objects = scons_utils.as_list(builder_func(sources, **kwargs))
        if cpp_modules:
            env.Depends(objects, resolve_nodes(cpp_modules, ctx))
    return objects + prebuilt
