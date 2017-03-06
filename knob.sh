#!/usr/bin/env bash


# Make sure umask is sane
umask 022

# Keep track of the DevStack directory
TOP_DIR=$(cd $(dirname "$0") && pwd)

# Import  basic definitions
# This include enabled services and DB connection string
source .stackenv

# Import common functions
source $TOP_DIR/functions

# Import common services (database, message queue) configuration
source $TOP_DIR/lib/database
source $TOP_DIR/lib/rpc_backend

# Import module specific functions
# Import TLS functions
source $TOP_DIR/lib/tls

# Source project function libraries
source $TOP_DIR/lib/infra
source $TOP_DIR/lib/oslo

source $TOP_DIR/lib/knob
source $TOP_DIR/lib/keystone

# Initialize database backends
initialize_database_backends && echo "Using $DATABASE_TYPE database backend" || echo "No database enabled"


# Configure database
# ------------------
if is_service_enabled $DATABASE_BACKENDS; then
    echo "Configuring database"
    configure_database
    #install_database
fi


# Work flow
echo " ---> Configure knob service"
configure_knob

echo " ---> Create knob accounts"
source $TOP_DIR/userrc_early
create_knob_accounts

echo " ---> Init knob"
init_knob

echo " ---> Start Knob service ..."
start_knob

