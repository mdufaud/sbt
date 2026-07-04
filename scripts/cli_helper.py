import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sbt.core import builder
from sbt.core import loader
from sbt.core import conf as sbt_conf
from sbt.build import modules as build_modules_util
from sbt.scons import env_factory


def _runner_env():
    env = {}
    for entry in builder.get_test_runner_env():
        key, _, val = entry.partition("=")
        env[key] = val
    return env


def _test_env(app):
    fn = getattr(app, "generate_test_env", None)
    if fn is not None:
        if callable(fn):
            return fn(builder)
        else:
            raise TypeError(f"app.generate_test_env is not callable: {fn}")
    return {}


def _test_command(app):
    fn = getattr(app, "generate_test_command", None)
    if fn is not None:
        if callable(fn):
            return fn(builder)
        else:
            raise TypeError(f"app.generate_test_command is not callable: {fn}")
    return {}


def _relative_paths(build_path):
    abs_paths = {
        "bin": builder.build_bin_path,
        "lib": builder.build_lib_path,
        "include": builder.build_hdr_path,
        "etc": builder.build_etc_path,
        "share": builder.build_share_path,
        "test": builder.build_test_path,
        "test_bin": os.path.join(builder.build_test_path, "bin"),
        "demo": builder.build_demo_path,
        "obj": builder.build_obj_path,
        "extlib": builder.build_extlib_path,
        "extlib_lib": builder.build_extlib_lib_path,
    }
    return {k: os.path.relpath(v, build_path) for k, v in abs_paths.items()}


def _build_env():
    app = loader.load_app()
    return {
        "app_name": app.name,
        "root_path": builder.build_root_path,
        "modules_path": builder.build_modules_path,
        "build_path": builder.build_path,
        "build": {
            "platform": builder.build_platform,
            "machine": builder.build_machine,
            "mode": builder.build_mode,
            "compiler": builder.build_compiler_version,
            "triplet": builder.get_gnu_triplet(),
            "libs_type": builder.libs_type,
        },
        "paths": _relative_paths(builder.build_path),
        "test": {
            "runner": builder.get_test_runner() or "",
            "bin_ext": builder.get_test_bin_ext() or "",
            "runner_env": _runner_env(),
            "env": _test_env(app),
            "command": _test_command(app),
        },
    }


def _conf(module_filter=None):
    app = loader.load_app()
    modules_options = env_factory.compute_modules_options(
        builder.build_platform,
        builder.libs_type,
        builder.build_mode,
        builder.build_compiler,
        builder,
    )
    specific = None
    if module_filter:
        specific = [m for m in module_filter.split(",") if m]
    build_modules = build_modules_util.build_modules_conf(app, specific_modules=specific)

    print("build selectors: " + " ".join(modules_options))

    candidate_conf_keys = set(sbt_conf.CONF_FLAG_ENV.keys())
    for opt in modules_options:
        for key in sbt_conf.CONF_FLAG_ENV.keys():
            candidate_conf_keys.add(f"{opt}-{key}")

    for modname, conf in build_modules.items():
        if not isinstance(conf, dict):
            continue
        matched = {k: v for k, v in conf.items() if k in candidate_conf_keys}
        if not matched:
            continue
        print(f"\n{modname}:")
        for key in sorted(matched):
            print(f"  {key} = {' '.join(str(v) for v in matched[key])}")


def _keys():
    app = loader.load_app()
    return sbt_conf.get_conf_vocabulary(app)


def _dump():
    os.makedirs(builder.build_path, exist_ok=True)
    json_path = os.path.join(builder.build_path, "sbt_env.json")
    with open(json_path, "w") as f:
        json.dump(_build_env(), f, indent=4)
    return json_path


if __name__ == '__main__':
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "conf":
        _conf(sys.argv[2] if len(sys.argv) > 2 else None)
        sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit(0)
    if sys.argv[1] == "dump":
        print(_dump())
    elif sys.argv[1] == "keys":
        print(json.dumps(_keys(), indent=4))
    elif sys.argv[1] == "compiler":
        print(builder.build_compiler_version)
    elif sys.argv[1] == "platform":
        print(builder.build_platform)
    elif sys.argv[1] == "machine":
        print(builder.build_machine)
    elif sys.argv[1] == "mode":
        print(builder.build_mode)
    elif sys.argv[1] == "termux":
        print(builder.build_on_termux and "true" or "false")
    elif sys.argv[1] == "path":
        print(builder.build_path)
    elif sys.argv[1] == "modules_path":
        loader.load_app()
        print(builder.build_modules_path)
    elif sys.argv[1] == "static":
        print(builder.libs_type)
    elif sys.argv[1] == "triplet":
        print(builder.get_gnu_triplet())
    elif sys.argv[1] == "runner":
        print(builder.get_test_runner())
    elif sys.argv[1] == "runner_env":
        print("\n".join(builder.get_test_runner_env()))
