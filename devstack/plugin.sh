# plugin.sh - DevStack plugin.sh dispatch script


# check for service enabled
if is_service_enabled knob; then

    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        # Set up system services
        echo_summary "Configuring system services Knob - nothing to do"
        #install_package cowsay

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        # Perform installation of service source
        echo_summary "Installing Knob"
        install_knobclient

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        # Configure after the other layer 1 and 2 services have been configured
        echo_summary "Configuring Knob"
        configure_knob

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        # Initialize and start the knob service
        echo_summary "Initializing Knob"
        init_knob
        
        echo_summary "Starting Knob"
        start_knob
    fi

    if [[ "$1" == "unstack" ]]; then
        # Shut down knob services
        stop_knob
    fi

    if [[ "$1" == "clean" ]]; then
        # Remove state and transient data
        # Remember clean.sh first calls unstack.sh
        cleanup_knob
    fi
fi
