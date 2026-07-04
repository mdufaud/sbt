from os.path import dirname, realpath, basename, isfile, abspath, isdir
import sys
import importlib.util
from os import getenv, environ

# root/site_scons/sbt/core/loader.py -> root/site_scons
__sbt_root_path = dirname(dirname(dirname(realpath(__file__))))

# root/site_scons -> root
__project_root_path = dirname(__sbt_root_path)

sys.path.append(__sbt_root_path)
sys.path.append(__project_root_path)

import re

from sbt.core import logger
from site_scons.sbt.core import utils

def __import_module_no_bytecode(module_name):
    """
    Import a module without writing bytecode files
    """
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return __import__(module_name, fromlist=[''])
    except ImportError as e:
        logger.error(f"Failed to import module {module_name}: {e}")
        raise
    finally:
        sys.dont_write_bytecode = before

def __import_from_path(file_path):
    """
    Import a module from a file path without writing bytecode files.
    Supports both absolute and relative paths, including subdirectories.
    """
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        # If path is relative, resolve it relative to project root
        if not file_path.startswith('/'):
            file_path = abspath(__project_root_path + '/' + file_path)
        else:
            file_path = abspath(file_path)
        if not isfile(file_path):
            raise ImportError(f"File not found: {file_path}")
        
        module_name = basename(file_path).replace(".py", "")
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module spec from: {file_path}")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = before

def load_env():
    env_module = None
    env_module_name = "env.py"

    env_arg = utils.get_opt("env", None)
    if env_arg is not None:
        logger.debug(f"Loading specific environment from: {env_arg}")
        env_module_name = env_arg

    try:
        env_module = __import_from_path(env_module_name)
    except ImportError as e:
        logger.debug(f"Could not load env from path {env_module_name}: {e}")
        pass

    if env_module is not None:
        env_keys = [item for item in dir(env_module) if not item.startswith("__")]
        for env_key in env_keys:
            if getenv(env_key, "") == "":
                value = getattr(env_module, env_key)
                environ[env_key] = str(value)

    return env_module

def _process_includes(app):
    """
    Process app.includes: load each file and merge its public attributes into the app module.
    Include paths are relative to the site_scons/ directory.

    Two-phase processing:
      1. Merge all public attributes from each include into the app module
      2. Call configure(app) on includes that define it, allowing them to
         compute values that depend on app-level attributes (name, version, ...)
    """
    if getattr(app, '_includes_processed', False):
        return
    includes = getattr(app, "includes", [])
    loaded_modules = []
    # phase 1: merge static attributes
    for include_path in includes:
        if not include_path.startswith('/'):
            abs_path = abspath(__sbt_root_path + '/' + include_path)
        else:
            abs_path = include_path
        try:
            module = __import_from_path(abs_path)
        except ImportError as e:
            logger.error(f"Failed to load include '{include_path}': {e}")
            raise
        for attr in dir(module):
            if not attr.startswith('_'):
                setattr(app, attr, getattr(module, attr))
        loaded_modules.append((include_path, module))
        logger.debug(f"included '{include_path}'")
    # phase 2: call configure(app) callbacks
    for include_path, module in loaded_modules:
        configure_fn = getattr(module, 'configure', None)
        if callable(configure_fn):
            configure_fn(app)
            logger.debug(f"configured '{include_path}'")
    app._includes_processed = True

def _validate_app(app):
    name = getattr(app, 'name', None)
    if not name:
        raise ValueError("app.py: 'name' is required")
    if not re.match(r'^[A-Za-z0-9_\-]+$', name):
        raise ValueError(
            f"app.py: 'name' must contain only letters, digits, hyphens and underscores (got: {name!r})"
        )
    modules_path = getattr(app, 'modules_path', "")
    if modules_path and not isdir(abspath(__project_root_path + '/' + modules_path)):
        raise ValueError(f"app.py: modules_path '{modules_path}' does not exist")
    if not isinstance(getattr(app, 'modules', None), dict):
        raise ValueError("app.py: 'modules' dict is required")
    version = getattr(app, 'version', None)
    if not version or not re.match(r'^\d+\.\d+\.\d+$', str(version)):
        raise ValueError(
            f"app.py: 'version' must be in 'x.y.z' format (got: {version!r})"
        )


def load_app():
    try:
        app = __import_module_no_bytecode("app")
    except ImportError as e:
        logger.error(f"Failed to load app module: {e}")
        raise
    _process_includes(app)
    _validate_app(app)
    from sbt.core import builder
    builder.set_modules_path(getattr(app, "modules_path", ""))
    from sbt.core import architectures
    architectures.register_machines(getattr(app, "architectures", None))
    architectures.register_machines(getattr(app, "extra_machines", None))
    return app