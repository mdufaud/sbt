#!/bin/bash
# Extract package name or launchable activity from an APK.
# Usage: apk_info.sh <package|activity> <path/to/apk>
set -e

MODE="$1"
APK="$2"

if [ -z "$MODE" ] || [ -z "$APK" ]; then
    echo "Usage: $0 <package|activity> <path/to/apk>" >&2
    exit 1
fi

if [ ! -f "$APK" ]; then
    echo "APK not found: $APK" >&2
    exit 1
fi

# Try aapt2 first, then aapt
BADGING=""
if command -v aapt2 >/dev/null 2>&1; then
    BADGING=$(aapt2 dump badging "$APK" 2>/dev/null) || true
fi
if [ -z "$BADGING" ] && command -v aapt >/dev/null 2>&1; then
    BADGING=$(aapt dump badging "$APK" 2>/dev/null) || true
fi

# Try ANDROID_SDK_PATH build-tools
if [ -z "$BADGING" ] && [ -n "$ANDROID_SDK_PATH" ]; then
    BT_DIR="$ANDROID_SDK_PATH/build-tools"
    if [ -d "$BT_DIR" ]; then
        LATEST_BT=$(ls -1 "$BT_DIR" | sort -V | tail -n1)
        if [ -n "$LATEST_BT" ]; then
            AAPT2="$BT_DIR/$LATEST_BT/aapt2"
            if [ -x "$AAPT2" ]; then
                BADGING=$("$AAPT2" dump badging "$APK" 2>/dev/null) || true
            fi
        fi
    fi
fi

if [ -z "$BADGING" ]; then
    echo "Cannot dump APK info: aapt2/aapt not found" >&2
    exit 1
fi

case "$MODE" in
    package)
        echo "$BADGING" | grep -oP "package: name='\K[^']+"
        ;;
    activity)
        echo "$BADGING" | grep -oP "launchable-activity: name='\K[^']+"
        ;;
    *)
        echo "Unknown mode: $MODE (use 'package' or 'activity')" >&2
        exit 1
        ;;
esac
