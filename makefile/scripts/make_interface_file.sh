#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

HDR_TEMPLATE=$SCRIPT_DIR/../templates/interface/hdr_template.txt \
    bash $SCRIPT_DIR/make_hdr_file.sh $1 $2 $3