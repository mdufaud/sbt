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

# Optional: declare which sbt compile modes build a stripped ("release") APK via
# gradle assembleRelease. Any mode NOT listed here builds a debug APK. Only
# needed when you want a mode to produce the release APK.
# android_release_modes = ["release"]
# # or: android_release_modes = ["release", "superReleaseToto2"]

# Optional: sign the release APK instead of leaving it unsigned. Point this at
# a gitignored `keystore.properties` file (see android/keystore.properties.example);
# sbt then injects a keystore loader + `signingConfigs { release { ... } }` block
# into the staged app/build.gradle and references it from the release build type,
# so assembleRelease produces a signed APK. The passwords are read from that file
# at Gradle configure time, never written into a generated file or committed.
# Leave unset/empty to keep the release APK unsigned.
# android_sign_config = "keystore.properties"

mode_debug_flags = ["-g", "-Og"]
mode_release_flags = ["-O3"]

## gcc specifics

gcc_flags = ["-Werror"]

mode_release_gcc_link = ['-s']

gcc_link = [
    "-Wl,-z,defs",
    "-Wl,-z,now",
    "-Wl,-z,relro",
]

# Position Independent Executable for security hardening - only for binaries.
gcc_shared_bin_link = ["-pie"]

if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
    gcc_flags.append("-fdiagnostics-color=always")
