#!/bin/bash

if [ -z "$1" ]; then
    echo "App name is not set"
    exit 1;
fi
if [ -z "$2" ]; then
    echo "Module name is not set"
    exit 1;
fi

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

if [ -n "${MODULES_DIR:-}" ]; then
    mkdir -p "$MODULES_DIR"
    cd "$MODULES_DIR"
fi

APP_NAME=$1
MODULE_NAME=$2
echo "Building module $MODULE_NAME"
mkdir -p $MODULE_NAME/src \
    $MODULE_NAME/test \
    $MODULE_NAME/include/$APP_NAME/$MODULE_NAME \
    $MODULE_NAME/etc/$APP_NAME/$MODULE_NAME \
    $MODULE_NAME/share/$APP_NAME/$MODULE_NAME

if [ ! -f $MODULE_NAME/scons.py ]; then
    cp $SCRIPT_DIR/../templates/scons_template.txt $MODULE_NAME/scons.py
    sed -i "s/APP_NAME/$APP_NAME/g" $MODULE_NAME/scons.py
    sed -i "s/MODULE_NAME/$MODULE_NAME/g" $MODULE_NAME/scons.py
fi
if [ ! -f $MODULE_NAME/test/main.cpp ]; then
    cp $SCRIPT_DIR/../templates/test/main_template.txt $MODULE_NAME/test/main.cpp
fi
echo "Module built"