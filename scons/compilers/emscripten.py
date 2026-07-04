from sbt.core import builder
from sbt.core import logger
import os
import re

def _parse_emscripten_config(config_path):
    """
    Safely parse ~/.emscripten config file.
    Returns a dict of configuration values.
    The file format is Python-like assignments: KEY = 'value' or KEY = "value"
    """
    config = {}
    try:
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Match KEY = 'value' or KEY = "value" patterns
                match = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=\s*['\"](.*)['\"]", line)
                if match:
                    key, value = match.groups()
                    config[key] = value
    except Exception as e:
        logger.warning(f"could not parse emscripten configuration: {config_path} - {e}")
    return config

def load_in_env(env):
    env.Replace(
        CC = "emcc",
        CXX = "em++",
        AR = "emar",
        RANLIB = "emranlib",
        LINK = "emcc",
    )

    emscripten_conf = os.path.join(os.getenv("HOME", ""), ".emscripten")
    if os.path.isfile(emscripten_conf):
        config = _parse_emscripten_config(emscripten_conf)
        # Use config values if needed (e.g., LLVM_ROOT, EMSCRIPTEN_ROOT)
        if 'EMSCRIPTEN_ROOT' in config:
            logger.info(f"Using emscripten from: {config['EMSCRIPTEN_ROOT']}")