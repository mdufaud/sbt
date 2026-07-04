import sys

name = 'project-name'
version = "0.1.0"
git_url = "https://github.com/yourname/project-name.git"

# files to include into this module (paths relative to site_scons/)
includes = [
]

###############################################################################
# modules
###############################################################################

modules = {
    "my-module": {
        "extlibs": ['fmt'],
        "libs": ['fmt']
    },
}

###############################################################################
# external libs
###############################################################################

extlibs = {
    # unit test
    "gtest": "1.17.0#2",
    # my-module
    "fmt": "12.1.0",
}

vcpkg_baseline = "3a3285c4878c7f5a957202201ba41e6fdeba8db4"

###############################################################################
# tests
###############################################################################

test_extlibs = ['gtest']
test_libs = ['gtest']

###############################################################################
# compilation
###############################################################################

## general compilation parameters

flags = ['-Wall', '-Wextra', '-pipe', '-fPIC']
defines = []

## mode specifics
modes = ["debug", "release"]

debug_flags = ["-g", "-Og"]
release_flags = ["-O3"]

## gcc specifics

gcc_flags = ["-Werror"]

gcc_release_link = ['-s']

gcc_link = [
    "-Wl,-z,defs",
    "-Wl,-z,now",
    "-Wl,-z,relro",
]

# Position Independent Executable for security hardening - only for binaries
gcc_shared_bin_link = ["-Wl,-pie",]

if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
    gcc_flags.append("-fdiagnostics-color=always")