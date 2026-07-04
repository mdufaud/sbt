#!/bin/bash

if [ -z "$1" ]; then
    echo "App name is not set"
    exit 1;
fi
if [ -z "$2" ]; then
    echo "Module name is not set"
    exit 1;
fi
if [ -z "$3" ]; then
    echo "Test name is not set"
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
TEST_NAME=$3
TEST_FILENAME=$MODULE_NAME/test/Test$3.cpp

echo "Making new test $TEST_NAME for module $MODULE_NAME: $TEST_FILENAME"
if [ -f TEST_FILENAME ]; then
    echo "Test already exist"
    exit 1
else
    cp $SCRIPT_DIR/../templates/test/template.txt $TEST_FILENAME
    sed -i "s/APP_NAME/$APP_NAME/g" $TEST_FILENAME
    sed -i "s/MODULE_NAME/$MODULE_NAME/g" $TEST_FILENAME
    sed -i "s/LOWER_CLASS_NAME/${TEST_NAME,,}/g" $TEST_FILENAME
    sed -i "s/CLASS_NAME/$TEST_NAME/g" $TEST_FILENAME
    echo "Test file done"
fi