#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

SRC_TEMPLATE="${SRC_TEMPLATE:=$SCRIPT_DIR/../templates/class/src_template.txt}"

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
CLASS_SRC_FILENAME=$MODULE_NAME/src/$3.cpp

echo "Making new class $CLASS_NAME for module $MODULE_NAME: $CLASS_SRC_FILENAME"
if [ -f $CLASS_SRC_FILENAME ]; then
    echo "Class source file already exist"
else
    cp $SRC_TEMPLATE $CLASS_SRC_FILENAME
    sed -i "s/APP_NAME/$APP_NAME/g" $CLASS_SRC_FILENAME
    sed -i "s/MODULE_NAME/$MODULE_NAME/g" $CLASS_SRC_FILENAME
    sed -i "s/CLASS_NAME/$CLASS_NAME/g" $CLASS_SRC_FILENAME
    echo "Source file done"
fi