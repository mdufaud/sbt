#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

bash $SCRIPT_DIR/make_src_file.sh $1 $2 $3 || exit 1
bash $SCRIPT_DIR/make_hdr_file.sh $1 $2 $3