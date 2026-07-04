###############################################################################
# Env
###############################################################################

import os
import sys
from os import getenv

def dedupe_keep_order(values):
    """Remove duplicates from *values* while preserving first-seen order."""
    return list(dict.fromkeys(values))

###############################################################################
# Filesystem
###############################################################################

def link_tree(src, dst):
    """Recursively create symlinks in dst for each file found under src."""
    if not os.path.isdir(src):
        return
    os.makedirs(dst, exist_ok=True)
    for entry in os.scandir(src):
        # Resolve to absolute real path to avoid chaining symlinks
        s = os.path.realpath(entry.path)
        d = os.path.join(dst, entry.name)
        if entry.is_dir(follow_symlinks=False):
            link_tree(entry.path, d)
        else:
            if os.path.islink(d) or os.path.exists(d):
                os.unlink(d)
            os.symlink(s, d)

def get_opt(argname, default_val=""):
    prefix = argname + "="
    for arg in sys.argv:
        if arg.startswith(prefix):
            val = arg[len(prefix):]
            if len(val) > 0:
                return val
    return getenv(argname, "") or default_val

def is_opt(argname, default_val=""):
    ret = get_opt(argname, default_val)
    return ret == "1" or ret.lower() == "true"
