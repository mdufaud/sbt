#!/bin/bash
# Usage: run_coverage.sh <BUILD_PATH> <PROJECT_ROOT_PATH> [module1 module2 ...]
#
# Runs gcovr on the coverage-instrumented object files for the specified modules
# (or all modules if none given) and emits:
#   <BUILD_PATH>/coverage/coverage.xml          (global Cobertura)
#   <BUILD_PATH>/coverage/index.html            (global HTML summary)
#   <BUILD_PATH>/coverage/<module>/coverage.xml (per-module Cobertura)
#   <BUILD_PATH>/coverage/<module>/index.html   (per-module HTML summary)
#   <BUILD_PATH>/coverage/<module>/src/         (per-file HTML details)
#
# Expects .gcda / .gcno files under <BUILD_PATH>/obj/<module>/.

set -e

if ! command -v gcovr >/dev/null 2>&1; then
    echo "gcovr not found - install with: pip install gcovr" >&2
    exit 1
fi

BUILD_PATH="$1"
PROJECT_ROOT_PATH="$2"
shift 2
MODULES="$*"

if [ -z "$BUILD_PATH" ] || [ -z "$PROJECT_ROOT_PATH" ]; then
    echo "Usage: $0 <BUILD_PATH> <PROJECT_ROOT_PATH> [module ...]" >&2
    exit 1
fi

COVERAGE_DIR="$BUILD_PATH/coverage"
mkdir -p "$COVERAGE_DIR"

# If no modules given, discover all that have a scons.py
if [ -z "$(printf '%s' "$MODULES" | tr -d ' ')" ]; then
    MODULES=$(cd "$PROJECT_ROOT_PATH" && ls -d */scons.py 2>/dev/null | sed 's|/scons.py||' | tr '\n' ' ')
fi

gcovr_filter=()
gcovr_search=()

for mod in $MODULES; do
    gcovr_filter+=(--filter "$mod/src" --filter "$mod/include")
    obj_dir="$BUILD_PATH/obj/$mod"
    [ -d "$obj_dir" ] && gcovr_search+=("$obj_dir")
done

if [ ${#gcovr_search[@]} -eq 0 ]; then
    echo "No object directories found under $BUILD_PATH/obj/ for modules: $MODULES" >&2
    exit 1
fi

echo "Writing coverage report to $COVERAGE_DIR/"

# Per-module reports
# Detail HTML files land alongside their index.html, so we put the index in src/
# giving: coverage/<mod>/coverage.xml, coverage/<mod>/index.html (summary),
#         coverage/<mod>/src/index.html + coverage/<mod>/src/index.*.html (details)
for mod in $MODULES; do
    obj_dir="$BUILD_PATH/obj/$mod"
    [ -d "$obj_dir" ] || continue
    mod_dir="$COVERAGE_DIR/$mod"
    mod_src_dir="$mod_dir/src"
    mkdir -p "$mod_src_dir"
    gcovr \
        --gcov-ignore-errors=no_working_dir_found \
        --cobertura  "$mod_dir/coverage.xml" \
        --html-details "$mod_src_dir/index.html" \
        --root       "$PROJECT_ROOT_PATH" \
        --exclude    '.*/test/.*' \
        --exclude    '.*/demo/.*' \
        --exclude-unreachable-branches \
        --filter     "$mod/src" \
        --filter     "$mod/include" \
        "$obj_dir"
done

# Global report
gcovr \
    --gcov-ignore-errors=no_working_dir_found \
    --cobertura  "$COVERAGE_DIR/coverage.xml" \
    --html       "$COVERAGE_DIR/index.html" \
    --root       "$PROJECT_ROOT_PATH" \
    --exclude    '.*/test/.*' \
    --exclude    '.*/demo/.*' \
    --exclude-unreachable-branches \
    --print-summary \
    "${gcovr_filter[@]}" \
    "${gcovr_search[@]}"

# Print clickable report links
echo ""
echo "Coverage reports:"
echo "- global: $COVERAGE_DIR/index.html"
for mod in $MODULES; do
    mod_index="$COVERAGE_DIR/$mod/src/index.html"
    [ -f "$mod_index" ] && echo "  - $mod: $mod_index"
done
