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
#   source /home/zeus/nas-workstation-monitor/nas_functions.sh
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
#   nas_dbcheck              # Check database health
#
# NOTES:
#   - All functions use Python scripts in /home/zeus/nas-monitor/
#   - Modify paths below if installed in different location
#   - Functions pass through additional arguments to underlying scripts
#   - Use --help on any function to see full options
################################################################################

# Base directory where NAS monitor is installed
NAS_MONITOR_DIR="/home/zeus/nas-workstation-monitor"

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
#   nas_monitor --verbose          # Detailed output
################################################################################
function nas_monitor() {
    cd "$NAS_MONITOR_DIR" && python3 nas_monitor.py --once "$@"
}

################################################################################
# nas_query - Generic query function (internal)
#
# Base function called by other query functions. This executes nas_query.py
# with the specified query type.
#
# USAGE:
#   nas_query <query_type> [args]
#
# ARGUMENTS:
#   query_type    One of: status, failures, recent, reliability, 
#                 software, detail, config
#   args          Additional arguments passed to nas_query.py
################################################################################
function nas_query() {
    cd "$NAS_MONITOR_DIR" && python3 nas_query.py "$@"
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
# Lists all workstations currently experiencing mount problems.
# This helps identify which systems need immediate attention.
#
# OUTPUT:
#   Table showing:
#   - Workstation with failure
#   - Mount point that failed
#   - When failure was first detected
#   - Number of consecutive failures
#
# USAGE:
#   nas_failures
#
# EXAMPLE OUTPUT:
#   ======================================================================
#   UNRESOLVED MOUNT FAILURES
#   ======================================================================
#   Workstation     Mount                     First Failed     Failures
#   ----------------------------------------------------------------------
#   cooper          /usr/local/chem.sw        2025-01-15       3
################################################################################
function nas_failures() {
    nas_query failures
}

################################################################################
# nas_reliability - Show 7-day reliability statistics
#
# Calculates and displays uptime percentages for each workstation over the
# past week. Helps identify chronically problematic systems.
#
# OUTPUT:
#   Table showing:
#   - Workstation name
#   - Total monitoring checks performed
#   - Successful checks
#   - Success rate (percentage)
#
# USAGE:
#   nas_reliability
#
# EXAMPLE OUTPUT:
#   ======================================================================
#   WORKSTATION RELIABILITY (7 Days)
#   ======================================================================
#   Workstation     Total Checks  Successful   Success Rate
#   ----------------------------------------------------------------------
#   adam            168           168          100.0%
#   sarah           168           165          98.2%
################################################################################
function nas_reliability() {
    nas_query reliability
}

################################################################################
# nas_software - Show software availability
#
# Displays the accessibility status of critical software packages
# (e.g., Gaussian, ORCA) on each workstation.
#
# OUTPUT:
#   Table showing which software packages are accessible on which mounts
#
# USAGE:
#   nas_software
################################################################################
function nas_software() {
    nas_query software
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
#   - Status (mounted/failed)
#   - Action taken (if any)
#
# EXAMPLES:
#   nas_detail adam           # Last 24 hours
#   nas_detail sarah 48       # Last 48 hours
#   nas_detail cooper 168     # Last week
################################################################################
function nas_detail() {
    local workstation="$1"
    local hours="${2:-24}"
    
    if [ -z "$workstation" ]; then
        echo "Usage: nas_detail <workstation> [hours]"
        echo "Example: nas_detail adam 48"
        return 1
    fi
    
    nas_query detail --workstation "$workstation" --hours "$hours"
}

################################################################################
# nas_recent - Show recent failures (24 hours)
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
# nas_dbcheck - Database health and configuration checks
#
# Provides quick diagnostic checks of the database status.
# All timestamps are displayed in local time (Eastern US).
#
# USAGE:
#   nas_dbcheck [check_type]
#
# CHECK TYPES:
#   config      Show database configuration settings
#   retention   Show data retention and cleanup status  
#   records     Show record counts by table
#   health      Show comprehensive database health check (default)
#   all         Run all checks
#
# EXAMPLES:
#   nas_dbcheck              # Run health check
#   nas_dbcheck config       # Show config only
#   nas_dbcheck retention    # Check data retention
#   nas_dbcheck all          # Run all diagnostics
################################################################################
function nas_dbcheck() {
    local check_type="${1:-health}"
    local db="$HOME/nas_workstation_monitor.db"
    
    case "$check_type" in
        config)
            echo "======================================================================"
            echo "DATABASE CONFIGURATION"
            echo "======================================================================"
            sqlite3 "$db" <<'SQL'
.mode column
.headers on
SELECT 
    id,
    keep_hours || ' hours (' || ROUND(keep_hours/24.0, 1) || ' days)' as retention,
    CASE aggressive_cleanup 
        WHEN 0 THEN 'Auto'
        WHEN 1 THEN 'Aggressive'
        ELSE 'Unknown'
    END as cleanup_mode
FROM monitor_config;
SQL
            ;;
            
        retention)
            echo "======================================================================"
            echo "DATA RETENTION STATUS"
            echo "======================================================================"
            sqlite3 "$db" <<'SQL'
.mode column
.headers on
SELECT 
    'Oldest mount record' as record_type,
    datetime(MIN(timestamp), 'localtime') as timestamp,
    ROUND((JULIANDAY('now') - JULIANDAY(MIN(timestamp))) * 24, 1) || ' hours' as age
FROM workstation_mount_status
UNION ALL
SELECT 
    'Newest mount record',
    datetime(MAX(timestamp), 'localtime'),
    ROUND((JULIANDAY('now') - JULIANDAY(MAX(timestamp))) * 24, 1) || ' hours'
FROM workstation_mount_status
UNION ALL
SELECT
    'Total mount records',
    COUNT(*),
    '-'
FROM workstation_mount_status;
SQL
            echo ""
            echo "Configured retention:"
            sqlite3 "$db" "SELECT keep_hours || ' hours (' || ROUND(keep_hours/24.0, 1) || ' days)' FROM monitor_config;"
            ;;
            
        records)
            echo "======================================================================"
            echo "DATABASE RECORD COUNTS"
            echo "======================================================================"
            sqlite3 "$db" <<'SQL'
.mode column
.headers on
SELECT 'Mount status records' as table_name, COUNT(*) as records FROM workstation_mount_status
UNION ALL
SELECT 'Workstation status', COUNT(*) FROM workstation_status
UNION ALL
SELECT 'Software checks', COUNT(*) FROM software_availability
UNION ALL
SELECT 'Mount failures', COUNT(*) FROM mount_failures;
SQL
            ;;
            
        health|"")
            echo "======================================================================"
            echo "DATABASE HEALTH CHECK"
            echo "======================================================================"
            echo ""
            echo "Configuration:"
            sqlite3 "$db" <<'SQL'
.mode list
SELECT '  Retention: ' || keep_hours || ' hours (' || ROUND(keep_hours/24.0, 1) || ' days)' FROM monitor_config
UNION ALL
SELECT '  Cleanup: ' || CASE aggressive_cleanup WHEN 0 THEN 'Auto' WHEN 1 THEN 'Aggressive' ELSE 'Unknown' END FROM monitor_config;
SQL
            echo ""
            echo "Record Counts:"
            sqlite3 "$db" <<'SQL'
.mode list
SELECT '  Mount records: ' || COUNT(*) FROM workstation_mount_status
UNION ALL
SELECT '  Workstation status: ' || COUNT(*) FROM workstation_status
UNION ALL
SELECT '  Software checks: ' || COUNT(*) FROM software_availability
UNION ALL
SELECT '  Failures: ' || COUNT(*) FROM mount_failures;
SQL
            echo ""
            echo "Data Age (Local Time):"
            sqlite3 "$db" <<'SQL'
.mode list
SELECT '  Oldest: ' || datetime(MIN(timestamp), 'localtime') || ' (' || ROUND((JULIANDAY('now') - JULIANDAY(MIN(timestamp))) * 24, 1) || ' hours old)' FROM workstation_mount_status
UNION ALL
SELECT '  Newest: ' || datetime(MAX(timestamp), 'localtime') || ' (' || ROUND((JULIANDAY('now') - JULIANDAY(MAX(timestamp))) * 24, 1) || ' hours old)' FROM workstation_mount_status;
SQL
            echo ""
            echo "Database File:"
            ls -lh "$db" | awk '{print "  Size: " $5 "\n  Modified: " $6 " " $7 " " $8}'
            ;;
            
        all)
            nas_dbcheck config
            echo ""
            nas_dbcheck records
            echo ""
            nas_dbcheck retention
            ;;
            
        *)
            echo "Unknown check type: $check_type"
            echo "Valid types: config, retention, records, health, all"
            return 1
            ;;
    esac
}

################################################################################
# nas_help - Show available functions
#
# Displays this help information
#
# USAGE:
#   nas_help
################################################################################
################################################################################
# nas_db_export - Export database to tab-delimited TSV files
#
# Creates a timestamped directory with all database tables and views exported
# to tab-delimited format compatible with Excel, R, and Python.
#
# OUTPUT:
#   Creates ~/nas_monitor_export_YYYYMMDD_HHMMSS/ containing:
#   - Raw tables (workstation_mount_status.tsv, mount_failures.tsv, etc.)
#   - Summary views (current_status_summary.tsv, reliability_summary.tsv)
#   - README.txt with usage instructions
#
# USAGE:
#   nas_db_export
#
# EXAMPLES:
#   nas_db_export                    # Export all data
#   # Then open in Excel, or:
#   # R: data <- read.delim("~/nas_monitor_export_*/workstation_mount_status.tsv")
#   # Python: pd.read_csv("~/nas_monitor_export_*/workstation_mount_status.tsv", sep="\t")
################################################################################
function nas_db_export() {
    bash ${NAS_MONITOR_DIR}/nas_db_export.sh "$@"
}

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
    echo "  nas_dbcheck [type]       Database health and diagnostics"
    echo ""
    echo "ADDITIONAL COMMANDS:"
    echo "  nas_software             Show software availability"
    echo "  nas_recent               Show recent failures (24 hours)"
    echo "  nas_config               Show database configuration"
    echo "  nas_db_export            Export database to tab-delimited TSV files"
    echo "  nas_help                 Show this help message"
    echo ""
    echo "DATABASE CHECKS:"
    echo "  nas_dbcheck              Quick health check (default)"
    echo "  nas_dbcheck config       Show configuration"
    echo "  nas_dbcheck retention    Check data retention status"
    echo "  nas_dbcheck records      Show record counts"
    echo "  nas_dbcheck all          Run all diagnostics"
    echo ""
    echo "GETTING MORE HELP:"
    echo "  nas_monitor --help       Full monitoring options"
    echo "  nas_query --help         Full query options"
    echo ""
    echo "EXAMPLES:"
    echo "  nas_status               # Quick health check"
    echo "  nas_detail adam 48       # Last 48 hours for adam"
    echo "  nas_monitor --verbose    # Run check with detailed output"
    echo "  nas_dbcheck retention    # Check data cleanup status"
    echo ""
}

# Print helpful message when sourced
echo "NAS Monitor functions loaded. Type 'nas_help' for available commands."
