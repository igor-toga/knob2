#!/bin/bash

# Keep track of the current DevStack directory.
TOP_DIR=$(cd $(dirname "$0") && pwd)
FILES=$TOP_DIR/files

# Import common functions
source $TOP_DIR/functions

# Import database library
source $TOP_DIR/lib/database
source $TOP_DIR/lib/rpc_backend

# Destination path for service data
DATA_DIR=${DATA_DIR:-${DEST}/data}

# Import module specific functions
source $TOP_DIR/lib/knob

echo "Stopping knob service ..."
stop_knob

