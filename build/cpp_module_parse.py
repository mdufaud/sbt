import os
import re

_module_re = re.compile(r'^\s*(?:export\s+)?module\s+([A-Za-z_][A-Za-z0-9_.:.]*)\s*;')

def parse_module_name(path):
    with open(path, 'r', encoding='utf-8') as fd:
        for line in fd:
            m = _module_re.match(line)
            if m:
                return m.group(1)
    raise RuntimeError(f"unable to determine C++ module name from: {path}")

def resolve_source_path(module_dir, source):
    source_path = str(source)
    if os.path.isabs(source_path):
        return source_path
    candidate = os.path.join(module_dir, source_path)
    return candidate if os.path.exists(candidate) else source_path

def _bmi_cache_name(backend):
    if backend == 'gcc':
        return 'gcm.cache'
    if backend == 'clang':
        return 'pcm.cache'
    raise RuntimeError(f"unsupported C++ modules backend: '{backend}'")

def get_bmi_dir(backend, build_path, dry_run=False):
    cache_dir = os.path.join(build_path, _bmi_cache_name(backend))
    if not dry_run:
        os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_bmi_filename(backend, module_name):
    if backend == 'gcc':
        return f'{module_name}.gcm'
    if backend == 'clang':
        return f"{module_name.replace(':', '-')}.pcm"
    raise RuntimeError(f"unsupported C++ modules backend: '{backend}'")

def get_bmi_path(backend, build_path, module_name, dry_run=False):
    return os.path.join(
        get_bmi_dir(backend, build_path, dry_run),
        get_bmi_filename(backend, module_name)
    )

def write_gcc_mapper(build_path, registry, dry_run=False):
    """Write/update the GCC module mapper file from the current modules registry.

    Format (from GCC mapper spec): '<module-name> <bmi-path>' one per line.
    """
    mapper_file = os.path.join(build_path, 'gcm.cache.mapper')
    if dry_run:
        return mapper_file
    with open(mapper_file, 'w') as f:
        for module_name, module_info in registry.items():
            f.write(f"{module_name} {module_info['bmi_path']}\n")
    return mapper_file
