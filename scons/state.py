"""Mutable build state shared across all module builds.

A single BuildState instance is created at the start of the build and passed
through the BuildContext to every env method. It replaces the ~10 module-level
global dicts/lists that previously lived directly in sbt/scons.py.
"""

from sbt.core import logger


class BuildState:
    """Registry of everything produced or exported during a build session."""

    def __init__(self, verbose):
        self.verbose = verbose

        # Registered build artefacts per module
        self.generated_libs = {}
        self.generated_bins = {}
        self.generated_tests = {}
        self.generated_demos = {}

        # Test infrastructure shared between modules
        self.exported_test_includes = {}
        self.exported_test_resources = {}

        # C++20 module support
        self.exported_bmis = {}    # module_name -> list of BMI names exported by that module
        self.cpp_modules = {}      # cpp_module_name -> {owner, compiler, bmi_dir, bmi_path, objects}

        # Git repositories cloned during the build
        self.cloned_git_repos = {}

        # Object nodes keyed by module, used to assemble the combined library
        self.lib_objects = {}

        # All source file nodes touched during the build (used for progress bar)
        self.targets = set()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def add_generated(self, gentype, registry, module_name, name, path):
        """Register a produced artefact in *registry* and log it if verbose."""
        registry.setdefault(module_name, []).append({"name": name, "path": path})
        if self.verbose:
            logger.debug(f"module '{module_name}' registered {gentype}: {path}")

    def add_targets(self, src):
        """Add *src* to the targets set, converting strings to SCons File nodes."""
        from SCons.Script import File
        if isinstance(src, str):
            self.targets.add(File(src))
        elif isinstance(src, list):
            self.targets.update(File(s) if isinstance(s, str) else s for s in src)
        else:
            self.targets.add(src)
