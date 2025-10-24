#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS Monitor Query Tool
Query and report on NAS mount monitoring database
"""
import typing
from typing import *

min_py = (3, 9)

###
# Standard imports, starting with os and sys
###
import os
import sys
if sys.version_info < min_py:
    print(f"This program requires Python {min_py[0]}.{min_py[1]}, or higher.")
    sys.exit(os.EX_SOFTWARE)

###
# Other standard distro imports
###
import argparse
import contextlib
import getpass
import logging
from datetime import datetime

###
# Installed libraries
###
try:
    import pandas
    use_pandas = True
except:
    use_pandas = False

###
# From hpclib (git submodule)
###
from hpclib import linuxutils
from hpclib.urdecorators import show_exceptions_and_frames as trap
from hpclib.urlogger import URLogger

###
# Local imports
###
from nas_monitor_dbclass import NASMonitorDB

###
# Credits
###
__author__ = 'University of Richmond HPC Team'
__copyright__ = 'Copyright 2025'
__credits__ = None
__version__ = 0.1
__maintainer__ = 'University of Richmond HPC Team'
__email__ = ['hpc@richmond.edu', 'jtonini@richmond.edu']
__status__ = 'in progress'
__license__ = 'MIT'

mynetid = getpass.getuser()

###
# Global objects (loaded by main)
###
myconfig = None
logger = None
db = None


@trap
def load_config(config_path: str) -> object:
    """Load configuration from TOML file"""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    
    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(os.EX_NOINPUT)
    
    with open(config_path, 'rb') as f:
        config_dict = tomllib.load(f)
    
    # Convert dict to object for dot notation
    class Config:
        def __init__(self, d):
            for key, value in d.items():
                if isinstance(value, dict):
                    setattr(self, key, Config(value))
                else:
                    setattr(self, key, value)
    
    return Config(config_dict)


@trap
def show_status() -> None:
    """
    Display current status of all workstations in a formatted table.
    
    This queries the current_workstation_summary view which provides the
    most recent check results for each workstation/mount combination.
    
    Output Format:
        If pandas available: Pretty-printed DataFrame
        Otherwise: Fixed-width column table
        
    Columns Displayed:
        - Workstation: Host name
        - Mount: Mount point path
        - Status: Mount status (mounted, failed, etc.)
        - Online: Whether host is reachable
        - Users: Number of active users
    
    Data Source:
        SQL View: current_workstation_summary
        This view JOINs workstation_mount_status with workstation_status
        to provide comprehensive current state.
    
    Use Cases:
        - Quick health check of all workstations
        - Verify after running monitor
        - Daily status review
        
    Example Output:
        ======================================================================
        CURRENT WORKSTATION STATUS
        ======================================================================
        
        Workstation     Mount                     Status     Online   Users 
        ----------------------------------------------------------------------
        adam            /usr/local/chem.sw        mounted    1        2     
        sarah           /usr/local/chem.sw        mounted    1        0     
    """
    global db
    
    print("\n" + "=" * 70)
    print("CURRENT WORKSTATION STATUS")
    print("=" * 70 + "\n")
    
    status = db.get_current_status()
    
    if use_pandas and isinstance(status, pandas.DataFrame):
        print(status.to_string(index=False))
    else:
        print(f"{'Workstation':<15} {'Mount':<25} {'Status':<10} {'Online':<8} {'Users':<6}")
        print("-" * 70)
        for row in status:
            print(f"{row[0]:<15} {row[1]:<25} {row[3]:<10} {row[5]:<8} {row[4]:<6}")
    
    print()


@trap
def show_failures() -> None:
    """Show unresolved mount failures"""
    global db
    
    print("\n" + "=" * 70)
    print("UNRESOLVED MOUNT FAILURES")
    print("=" * 70 + "\n")
    
    failures = db.get_unresolved_failures()
    
    if use_pandas and isinstance(failures, pandas.DataFrame):
        if failures.empty:
            print("No unresolved failures found.")
        else:
            print(failures.to_string(index=False))
    else:
        if not failures:
            print("No unresolved failures found.")
        else:
            print(f"{'Workstation':<15} {'Mount Point':<25} {'First Failure':<20} {'Count':<6} {'Days':<6}")
            print("-" * 70)
            for row in failures:
                print(f"{row[0]:<15} {row[1]:<25} {row[2]:<20} {row[4]:<6} {row[5]:<6.1f}")
    
    print()


@trap
def show_recent_failures() -> None:
    """Show recent failure summary (last 24 hours)"""
    global db
    
    print("\n" + "=" * 70)
    print("RECENT FAILURES (Last 24 Hours)")
    print("=" * 70 + "\n")
    
    failures = db.get_recent_failures()
    
    if use_pandas and isinstance(failures, pandas.DataFrame):
        if failures.empty:
            print("No recent failures found.")
        else:
            print(failures.to_string(index=False))
    else:
        if not failures:
            print("No recent failures found.")
        else:
            print(f"{'Workstation':<15} {'Failures':<10} {'Affected Mounts':<15} {'Latest':<20}")
            print("-" * 70)
            for row in failures:
                print(f"{row[0]:<15} {row[1]:<10} {row[2]:<15} {row[4]:<20}")
    
    print()


@trap
def show_reliability() -> None:
    """Show 7-day reliability statistics"""
    global db
    
    print("\n" + "=" * 70)
    print("WORKSTATION RELIABILITY (7 Days)")
    print("=" * 70 + "\n")
    
    reliability = db.get_reliability()
    
    if use_pandas and isinstance(reliability, pandas.DataFrame):
        print(reliability.to_string(index=False))
    else:
        print(f"{'Workstation':<15} {'Total Checks':<13} {'Successful':<12} {'Success Rate':<12}")
        print("-" * 70)
        for row in reliability:
            print(f"{row[0]:<15} {row[1]:<13} {row[2]:<12} {row[3]:<12.1f}%")
    
    print()


@trap
def show_software() -> None:
    """Show software availability summary"""
    global db
    
    print("\n" + "=" * 70)
    print("SOFTWARE AVAILABILITY (7 Days)")
    print("=" * 70 + "\n")
    
    software = db.get_software_summary()
    
    if use_pandas and isinstance(software, pandas.DataFrame):
        if software.empty:
            print("No software checks found.")
        else:
            print(software.to_string(index=False))
    else:
        if not software:
            print("No software checks found.")
        else:
            print(f"{'Software':<15} {'Mount Point':<25} {'Checks':<8} {'Available':<11} {'Rate':<8}")
            print("-" * 70)
            for row in software:
                print(f"{row[0]:<15} {row[1]:<25} {row[2]:<8} {row[3]:<11} {row[4]:<8.1f}%")
    
    print()


@trap
def show_workstation_detail(workstation: str, hours: int = 24) -> None:
    """Show detailed history for a workstation"""
    global db
    
    print("\n" + "=" * 70)
    print(f"WORKSTATION DETAIL: {workstation} (Last {hours} hours)")
    print("=" * 70 + "\n")
    
    detail = db.get_workstation_detail(workstation, hours)
    
    if use_pandas and isinstance(detail, pandas.DataFrame):
        if detail.empty:
            print(f"No records found for {workstation}")
        else:
            print(detail.to_string(index=False))
    else:
        if not detail:
            print(f"No records found for {workstation}")
        else:
            print(f"{'Timestamp':<20} {'Mount Point':<25} {'Status':<10} {'Users':<6}")
            print("-" * 70)
            for row in detail:
                print(f"{row[0]:<20} {row[1]:<25} {row[3]:<10} {row[4]:<6}")
    
    print()


@trap
def show_config() -> None:
    """Show current database configuration"""
    global db
    
    print("\n" + "=" * 70)
    print("DATABASE CONFIGURATION")
    print("=" * 70 + "\n")
    
    config = db.get_config()
    
    print(f"Keep hours: {config.get('keep_hours', 'N/A')}")
    print(f"Aggressive cleanup: {bool(config.get('aggressive_cleanup', 0))}")
    print()


@trap
def update_config(keep_hours: int, aggressive: bool) -> None:
    """Update database configuration"""
    global db, logger
    
    db.update_config(keep_hours, aggressive)
    logger.info(f"Updated config: keep_hours={keep_hours}, aggressive={aggressive}")
    print(f"Configuration updated: keep_hours={keep_hours}, aggressive={aggressive}")


@trap
def cleanup_database(confirm: bool = False) -> None:
    """Clean up old database records"""
    global db, logger
    
    if not confirm:
        print("Dry run - no records will be deleted")
        print("Use --confirm to actually perform cleanup")
        return
    
    mount_deleted, software_deleted = db.cleanup_old_records()
    total = mount_deleted + software_deleted
    
    logger.info(f"Cleanup: removed {mount_deleted} mount, {software_deleted} software records")
    print(f"Cleanup complete: {total} records removed")
    print(f"  Mount records: {mount_deleted}")
    print(f"  Software records: {software_deleted}")


@trap
def nas_query_main(myargs: argparse.Namespace) -> int:
    """
    Main query function - processes commands and displays results.
    
    This is a command-line interface for querying the NAS monitoring database.
    It provides read-only access to monitoring data and statistics without
    running any actual monitoring checks.
    
    Available Commands:
        status: Current workstation status
        failures: Unresolved mount failures
        recent: Recent failures (last 24 hours)
        reliability: 7-day reliability statistics
        software: Software availability summary
        detail: Detailed history for specific workstation
        config: Show database configuration
        update-config: Modify database configuration
        cleanup: Remove old database records
    
    Args:
        myargs: Parsed command line arguments including:
            - command: Which query/action to perform
            - config: Path to TOML configuration file
            - verbose: Enable debug logging
            - Additional args specific to each command
    
    Returns:
        os.EX_OK (0): Successful query
        os.EX_USAGE (64): Invalid command or missing required args
        os.EX_NOINPUT (66): Config file not found
    
    Database Access:
        Opens database in read-only mode for queries
        Uses NASMonitorDB class which inherits from SQLiteDB
        All queries use SQL views for optimized access
    
    Logging:
        Minimal logging unless --verbose specified
        Logs go to same log file as monitoring daemon
        Query operations are not logged by default to reduce noise
    
    Examples:
        nas_query.py status
        nas_query.py detail --workstation adam --hours 48
        nas_query.py cleanup --confirm
    """
    global myconfig, logger, db
    
    # Load configuration
    myconfig = load_config(myargs.config)
    
    # Initialize logger (silent for queries unless verbose)
    log_level = logging.DEBUG if myargs.verbose else logging.ERROR
    logger = URLogger(logfile=myconfig.log_file, level=log_level)
    
    # Initialize database
    db = NASMonitorDB(myconfig.database)
    
    # Execute command
    if myargs.command == 'status':
        show_status()
    
    elif myargs.command == 'failures':
        show_failures()
    
    elif myargs.command == 'recent':
        show_recent_failures()
    
    elif myargs.command == 'reliability':
        show_reliability()
    
    elif myargs.command == 'software':
        show_software()
    
    elif myargs.command == 'detail':
        if not myargs.workstation:
            print("ERROR: --workstation required for detail command")
            return os.EX_USAGE
        show_workstation_detail(myargs.workstation, myargs.hours)
    
    elif myargs.command == 'config':
        show_config()
    
    elif myargs.command == 'update-config':
        update_config(myargs.keep_hours, myargs.aggressive)
    
    elif myargs.command == 'cleanup':
        cleanup_database(myargs.confirm)
    
    else:
        print(f"Unknown command: {myargs.command}")
        return os.EX_USAGE
    
    db.close()
    return os.EX_OK


if __name__ == '__main__':
    
    parser = argparse.ArgumentParser(
        prog="nas_query",
        description="Query NAS mount monitoring database"
    )
    
    parser.add_argument('-c', '--config', type=str,
        default='/home/zeus/nas-workstation-monitor/nas_monitor.toml',
        help="Configuration file path")
    
    parser.add_argument('-v', '--verbose', action='store_true',
        help="Be chatty about what is taking place")
    
    parser.add_argument('--nice', type=int, choices=range(0, 20), default=0,
        help="Niceness may affect execution time")
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # status command
    subparsers.add_parser('status', help='Show current workstation status')
    
    # failures command
    subparsers.add_parser('failures', help='Show unresolved mount failures')
    
    # recent command
    subparsers.add_parser('recent', help='Show recent failures (24 hours)')
    
    # reliability command
    subparsers.add_parser('reliability', help='Show 7-day reliability stats')
    
    # software command
    subparsers.add_parser('software', help='Show software availability')
    
    # detail command
    detail_parser = subparsers.add_parser('detail', help='Show workstation detail')
    detail_parser.add_argument('--workstation', type=str, required=True,
        help='Workstation name')
    detail_parser.add_argument('--hours', type=int, default=24,
        help='Hours of history (default: 24)')
    
    # config command
    subparsers.add_parser('config', help='Show database configuration')
    
    # update-config command
    update_parser = subparsers.add_parser('update-config', 
        help='Update database configuration')
    update_parser.add_argument('--keep-hours', type=int, required=True,
        help='Hours of history to keep')
    update_parser.add_argument('--aggressive', action='store_true',
        help='Use aggressive cleanup mode')
    
    # cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', 
        help='Clean up old database records')
    cleanup_parser.add_argument('--confirm', action='store_true',
        help='Actually perform cleanup (default is dry run)')
    
    myargs = parser.parse_args()
    
    if not myargs.command:
        parser.print_help()
        sys.exit(os.EX_USAGE)
    
    myargs.verbose and linuxutils.dump_cmdline(myargs)
    if myargs.nice:
        os.nice(myargs.nice)
    
    try:
        sys.exit(nas_query_main(myargs))
    
    except Exception as e:
        print(f"Escaped or re-raised exception: {e}")
