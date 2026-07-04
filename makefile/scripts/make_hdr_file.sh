#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

HDR_TEMPLATE="${HDR_TEMPLATE:=$SCRIPT_DIR/../templates/class/hdr_template.txt}"

if [ -z "$1" ]; then
    echo "App name is not set"
    exit 1;
fi
if [ -z "$2" ]; then
    echo "Module name is not set"
    exit 1;
fi
if [ -z "$3" ]; then
    echo "Class name is not set"
    exit 1;
fi

set -e

if [ -n "${MODULES_DIR:-}" ]; then
    mkdir -p "$MODULES_DIR"
    cd "$MODULES_DIR"
fi

APP_NAME=$1
MODULE_NAME=$2
CLASS_NAME=$3
CLASS_HDR_FILENAME=$MODULE_NAME/include/$APP_NAME/$MODULE_NAME/$3.hpp

echo "Making new class $CLASS_NAME for module $MODULE_NAME: $CLASS_HDR_FILENAME"

if [ -f $CLASS_HDR_FILENAME ]; then
    echo "Class header file already exist"
else
    cp $HDR_TEMPLATE $CLASS_HDR_FILENAME

    sed -i "s/APP_NAME_UPPER/${APP_NAME^^}/g" $CLASS_HDR_FILENAME
    sed -i "s/MODULE_NAME_UPPER/${MODULE_NAME^^}/g" $CLASS_HDR_FILENAME
    sed -i "s/CLASS_NAME_UPPER/${CLASS_NAME^^}/g" $CLASS_HDR_FILENAME
    sed -i "s/APP_NAME/$APP_NAME/g" $CLASS_HDR_FILENAME
    sed -i "s/MODULE_NAME/$MODULE_NAME/g" $CLASS_HDR_FILENAME
    sed -i "s/CLASS_NAME/$CLASS_NAME/g" $CLASS_HDR_FILENAME
    echo "Header file done"
fi