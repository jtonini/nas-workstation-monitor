#!/bin/bash
################################################################################
# NAS Monitor Shell Functions
#
# Convenience wrappers for NAS workstation monitoring tools.
# These functions provide simple commands for system administrators to check
# mount status, review failures, and analyze reliability trends.
#
# INSTALLATION:
#   Add to your ~/.bashrc:
#   source /home/zeus/nas-monitor/nas_functions.sh
#
#   Then reload:
#   source ~/.bashrc
#
# USAGE:
#   nas_monitor              # Run monitoring check once
#   nas_status               # Show current status
#   nas_failures             # Show unresolved failures
#   nas_reliability          # Show 7-day reliability stats
#   nas_detail adam          # Show detailed history for 'adam'
#
# NOTES:
#   - All functions use Python scripts in /home/zeus/nas-monitor/
#   - Modify paths below if installed in different location
#   - Functions pass through additional arguments to underlying scripts
#   - Use --help on any function to see full options
################################################################################

# Base directory where NAS monitor is installed
NAS_MONITOR_DIR="/home/zeus/nas-monitor"

################################################################################
# nas_monitor - Run monitoring check once
#
# Executes a single monitoring cycle without entering daemon mode.
# This checks all configured workstations, attempts remounts if needed,
# and logs results to database.
#
# USAGE:
#   nas_monitor                    # Run with default config
#   nas_monitor --verbose          # Show detailed output
#   nas_monitor --config /path     # Use custom config file
#
# ARGUMENTS:
#   All arguments are passed through to nas_monitor.py
#   See: nas_monitor --help
#
# EXAMPLES:
#   nas_monitor                    # Quick check
#   nas_monitor --verbose          # See what's happening
#   nas_monitor --config test.toml # Use test configuration
################################################################################
function nas_monitor() {
    python3 "${NAS_MONITOR_DIR}/nas_monitor.py" --once "$@"
}

################################################################################
# nas_query - Query monitoring database
#
# Generic query function that accepts any query command.
# Prefer using specific functions (nas_status, nas_failures, etc.) for
# common operations.
#
# USAGE:
#   nas_query <command> [options]
#
# COMMANDS:
#   status        Current workstation status
#   failures      Unresolved mount failures
#   recent        Recent failures (24 hours)
#   reliability   7-day reliability statistics
#   software      Software availability summary
#   detail        Detailed workstation history
#   config        Show database configuration
#   cleanup       Clean up old records
#
# EXAMPLES:
#   nas_query status
#   nas_query detail --workstation adam --hours 48
#   nas_query cleanup --confirm
################################################################################
function nas_query() {
    python3 "${NAS_MONITOR_DIR}/nas_query.py" "$@"
}

################################################################################
# nas_status - Show current workstation status
#
# Displays the most recent mount status for all monitored workstations.
# This is the quickest way to get an overview of the entire lab.
#
# OUTPUT:
#   Table showing:
#   - Workstation name
#   - Mount point
#   - Mount status (mounted/failed)
#   - Online status
#   - Active users
#
# USAGE:
#   nas_status
#
# EXAMPLE OUTPUT:
#   ======================================================================
#   CURRENT WORKSTATION STATUS
#   ======================================================================
#   Workstation     Mount                     Status     Online   Users
#   ----------------------------------------------------------------------
#   adam            /usr/local/chem.sw        mounted    1        2
#   sarah           /usr/local/chem.sw        mounted    1        0
################################################################################
function nas_status() {
    nas_query status
}

################################################################################
# nas_failures - Show unresolved mount failures
#
# Lists all workstations with ongoing mount problems that haven't been
# resolved. This is useful for identifying persistent issues that need
# manual intervention.
#
# OUTPUT:
#   Table showing:
#   - Workstation name
#   - Mount point
#   - When failure first occurred
#   - Number of consecutive failures
#   - Days failing
#
# USAGE:
#   nas_failures
#
# NOTES:
#   - Failures are auto-resolved when mount succeeds
#   - "Days failing" indicates problem duration
#   - High failure count suggests systematic issue
################################################################################
function nas_failures() {
    nas_query failures
}

################################################################################
# nas_reliability - Show 7-day reliability statistics
#
# Displays success rate for each workstation over the past week.
# Helps identify chronically problematic systems or trending issues.
#
# OUTPUT:
#   Table showing:
#   - Workstation name
#   - Total checks performed
#   - Successful checks
#   - Success rate percentage
#
# USAGE:
#   nas_reliability
#
# INTERPRETATION:
#   100%    = Perfect, no issues
#   95-99%  = Minor intermittent problems
#   90-95%  = Significant issues, investigate
#   <90%    = Critical problems, immediate attention needed
#
# EXAMPLE OUTPUT:
#   Workstation     Total Checks   Successful    Success Rate
#   --------------------------------------------------------------
#   adam            168            168           100.0%
#   sarah           168            165           98.2%
################################################################################
function nas_reliability() {
    nas_query reliability
}

################################################################################
# nas_detail - Show detailed history for a specific workstation
#
# Displays complete monitoring history for one workstation, showing
# every check performed within the specified time window.
#
# USAGE:
#   nas_detail <workstation> [hours]
#
# ARGUMENTS:
#   workstation    Required. Hostname to query (e.g., adam, sarah)
#   hours          Optional. Hours of history (default: 24)
#
# OUTPUT:
#   Chronological table showing:
#   - Timestamp of each check
#   - Mount point checked
#   - Status result
#   - Number of active users
#   - Actions taken (remounts, etc.)
#
# EXAMPLES:
#   nas_detail adam           # Last 24 hours for adam
#   nas_detail sarah 48       # Last 48 hours for sarah
#   nas_detail michael 168    # Last week for michael
#
# NOTES:
#   - Useful for troubleshooting specific workstation problems
#   - Shows pattern of failures and recoveries
#   - Can reveal timing patterns (e.g., failures at specific times)
################################################################################
function nas_detail() {
    # Validate arguments
    if [ -z "$1" ]; then
        echo "ERROR: Workstation name required"
        echo ""
        echo "USAGE:"
        echo "  nas_detail <workstation> [hours]"
        echo ""
        echo "EXAMPLES:"
        echo "  nas_detail adam           # Last 24 hours"
        echo "  nas_detail sarah 48       # Last 48 hours"
        echo ""
        return 1
    fi
    
    local workstation="$1"
    local hours="${2:-24}"  # Default to 24 hours if not specified
    
    nas_query detail --workstation "$workstation" --hours "$hours"
}

################################################################################
# ADDITIONAL HELPER FUNCTIONS
#
# The following functions provide shortcuts for other common operations.
################################################################################

################################################################################
# nas_software - Show software availability summary
#
# Displays 7-day availability statistics for critical software packages
# (Gaussian, ORCA, Lumerical, etc.) across all workstations.
#
# USAGE:
#   nas_software
################################################################################
function nas_software() {
    nas_query software
}

################################################################################
# nas_recent - Show recent failures (last 24 hours)
#
# Quick summary of which workstations had problems in the last day.
# Faster than full failure list, focuses on immediate issues.
#
# USAGE:
#   nas_recent
################################################################################
function nas_recent() {
    nas_query recent
}

################################################################################
# nas_config - Show database configuration
#
# Displays current database settings including:
#   - How many hours of history are kept
#   - Cleanup mode (standard vs aggressive)
#
# USAGE:
#   nas_config
################################################################################
function nas_config() {
    nas_query config
}

################################################################################
# nas_help - Show available functions
#
# Displays this help information
#
# USAGE:
#   nas_help
################################################################################
function nas_help() {
    echo "========================================================================"
    echo "NAS Monitor Shell Functions - Help"
    echo "========================================================================"
    echo ""
    echo "COMMON COMMANDS:"
    echo "  nas_monitor              Run monitoring check once"
    echo "  nas_status               Show current status of all workstations"
    echo "  nas_failures             Show unresolved mount failures"
    echo "  nas_reliability          Show 7-day reliability statistics"
    echo "  nas_detail <host>        Show detailed history for a workstation"
    echo ""
    echo "ADDITIONAL COMMANDS:"
    echo "  nas_software             Show software availability"
    echo "  nas_recent               Show recent failures (24 hours)"
    echo "  nas_config               Show database configuration"
    echo "  nas_help                 Show this help message"
    echo ""
    echo "GETTING MORE HELP:"
    echo "  nas_monitor --help       Full monitoring options"
    echo "  nas_query --help         Full query options"
    echo ""
    echo "EXAMPLES:"
    echo "  nas_status               # Quick health check"
    echo "  nas_detail adam 48       # Last 48 hours for adam"
    echo "  nas_monitor --verbose    # Run check with detailed output"
    echo ""
}

# Print helpful message when sourced
echo "NAS Monitor functions loaded. Type 'nas_help' for available commands."
