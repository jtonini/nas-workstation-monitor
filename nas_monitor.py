#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS Workstation Mount Monitor
Automated monitoring and maintenance of NAS mounts across lab workstations
"""
import typing
from typing import *

min_py = (3, 8)

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
import datetime
import getpass
import logging
import signal
import socket
import time
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

###
# Installed libraries (TOML parser)
###
try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # Python 3.6-3.10
    except ImportError:
        print("ERROR: Neither tomllib nor tomli available. Install tomli:", file=sys.stderr)
        print("  pip install tomli --break-system-packages", file=sys.stderr)
        sys.exit(os.EX_SOFTWARE)

###
# From hpclib (git submodule)
###
from hpclib import linuxutils
from hpclib.urdecorators import show_exceptions_and_frames as trap
from hpclib.urlogger import URLogger
from hpclib.dorunrun import dorunrun

###
# Local imports
###
from nas_monitor_db import NASMonitorDB

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
# Global configuration, logger, and database
# Loaded by load_config()
###
myconfig = None
logger = None
db = None


@trap
def load_config(config_path: str) -> object:
    """Load configuration from TOML file"""
    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(os.EX_NOINPUT)
    
    with open(config_path, 'rb') as f:
        config_dict = tomllib.load(f)
    
    # Convert dict to object for dot notation access (like dfstat)
    class Config:
        def __init__(self, d):
            for key, value in d.items():
                if isinstance(value, dict):
                    setattr(self, key, Config(value))
                else:
                    setattr(self, key, value)
    
    return Config(config_dict)


@trap
def check_workstation_online(workstation: str) -> bool:
    """Check if workstation is reachable"""
    cmd = ['ping', '-c', '1', '-W', '2', workstation]
    exit_code, stdout, stderr = dorunrun(cmd, timeout=5, return_datatype=tuple)
    return exit_code == 0


@trap
def get_mount_status(workstation: str) -> Tuple[bool, List[Dict], str]:
    """
    Get mount status from workstation using SSH 'mount -av' command.
    
    The 'mount -av' command verifies all mounts in /etc/fstab and reports:
    - Mounts that are already mounted (healthy)
    - Mounts that can be mounted (were unmounted but work)
    - Mounts that fail to mount (need attention)
    
    Args:
        workstation: Hostname of the workstation to check
    
    Returns:
        Tuple of (success, mount_list, error_message):
        - success (bool): True if command executed successfully
        - mount_list (List[Dict]): List of mount information dicts, each containing:
            * device: Source device/NFS path (e.g., '141.166.186.35:/mnt/usrlocal/8')
            * mount_point: Target mount point (e.g., '/usr/local/chem.sw')
            * status: 'mounted' or 'newly_mounted'
        - error_message (str): Error details if command failed, empty string on success
    
    Example mount output parsing:
        "141.166.186.35:/mnt/usrlocal/8 on /usr/local/chem.sw already mounted"
        → {'device': '141.166.186.35:/mnt/usrlocal/8', 
           'mount_point': '/usr/local/chem.sw',
           'status': 'mounted'}
    """
    global myconfig
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'mount -av']
    exit_code, stdout, stderr = dorunrun(cmd, timeout=myconfig.ssh_timeout, return_datatype=tuple)
    
    if exit_code != 0:
        return False, [], stderr
    
    # Parse mount output
    mounts = []
    for line in stdout.splitlines():
        if ':' in line or '/dev' in line:
            parts = line.split()
            if len(parts) >= 3:
                mount_info = {
                    'device': parts[0] if parts else '',
                    'mount_point': parts[2] if len(parts) > 2 else '',
                    'status': 'mounted' if 'already mounted' in line.lower() 
                             else 'newly_mounted'
                }
                mounts.append(mount_info)
    
    return True, mounts, ""


@trap
def verify_software_access(workstation: str, mount_point: str, 
                           software_list: List[str]) -> Dict[str, bool]:
    """
    Verify that critical software packages are accessible on a mount point.
    
    This checks whether important computational chemistry software is available
    and accessible. A missing or inaccessible package could indicate:
    - Mount failure or unmount
    - Permission issues
    - NFS stale file handle
    - Network connectivity problems
    
    The function uses SSH 'test -e' command to check file/directory existence.
    Results are logged to the software_availability table for tracking.
    
    Args:
        workstation: Hostname to check
        mount_point: Base mount path (e.g., '/usr/local/chem.sw')
        software_list: List of software names to verify (e.g., ['amber', 'gaussian'])
    
    Returns:
        Dictionary mapping software names to accessibility boolean:
        Example: {'amber': True, 'gaussian': False, 'Columbus': True}
        
    Side Effects:
        - Inserts software check results into database via db.add_software_check()
        - Each software is tested individually for granular tracking
    
    Note:
        Software names are expected to be subdirectories or files directly under
        the mount_point. Adjust paths in TOML config if software uses different structure.
    """
    global myconfig, db
    
    results = {}
    
    for software in software_list:
        test_path = f"{mount_point}/{software}"
        cmd = ['ssh'] + myconfig.ssh_options + [workstation, 
               f'test -e {test_path} && echo "OK" || echo "MISSING"']
        
        exit_code, stdout, stderr = dorunrun(cmd, timeout=10, return_datatype=tuple)
        results[software] = 'OK' in stdout
        
        # Log to database
        db.insert_software_check(workstation, software, mount_point, results[software])
    
    return results


@trap
def attempt_remount(workstation: str) -> Tuple[bool, str]:
    """Attempt to remount all NAS directories on workstation"""
    global myconfig, logger
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'sudo mount -a']
    exit_code, stdout, stderr = dorunrun(cmd, timeout=60, return_datatype=tuple)
    
    if exit_code == 0:
        logger.info(f"Successfully remounted on {workstation}")
        return True, "Remount successful"
    else:
        logger.error(f"Failed to remount on {workstation}: {stderr}")
        return False, stderr


@trap
def count_active_users(workstation: str) -> int:
    """Count active users on workstation"""
    global myconfig
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'who | wc -l']
    exit_code, stdout, stderr = dorunrun(cmd, timeout=10, return_datatype=tuple)
    
    if exit_code == 0:
        try:
            return int(stdout.strip())
        except:
            pass
    return 0


@trap
def monitor_workstation(workstation_config: Dict) -> Dict:
    """
    Monitor a single workstation's NAS mounts and verify software accessibility.
    
    This function performs the core monitoring workflow:
    1. Check if workstation is online (ping test)
    2. Get mount status via SSH 'mount -av' command
    3. Count active users if configured
    4. Attempt remount if issues detected and auto-fix is enabled
    5. Verify critical software is accessible on each mount
    6. Record all results to database
    
    Args:
        workstation_config: Dictionary with 'host' and 'mounts' keys
                           Example: {'host': 'adam', 'mounts': ['/usr/local/chem.sw']}
    
    Returns:
        Dictionary containing monitoring results:
        - workstation: Host name
        - timestamp: ISO format timestamp
        - online: Boolean, is host reachable
        - mounts_ok: Boolean, are mounts working
        - active_users: Integer count of logged-in users
        - mount_details: List of mount info dicts
        - software_issues: List of inaccessible software
        - actions_taken: List of remediation actions
    """
    global myconfig, logger, db
    
    workstation = workstation_config['host']
    expected_mounts = workstation_config['mounts']
    
    logger.info(f"Checking workstation: {workstation}")
    
    report = {
        'workstation': workstation,
        'timestamp': datetime.datetime.now().isoformat(),
        'online': False,
        'mounts_ok': False,
        'active_users': 0,
        'mount_details': [],
        'software_issues': [],
        'actions_taken': []
    }
    
    # Check if workstation is online
    if not check_workstation_online(workstation):
        logger.warning(f"{workstation} is offline")
        db.update_workstation_status(workstation, is_online=False, checked_by=mynetid)
        return report
    
    report['online'] = True
    
    # Count active users if configured
    if myconfig.track_users:
        report['active_users'] = count_active_users(workstation)
    
    # Get mount status
    success, mounts, error_msg = get_mount_status(workstation)
    
    if not success:
        logger.error(f"Failed to get mount status from {workstation}: {error_msg}")
        report['error'] = error_msg
        
        if myconfig.attempt_fix:
            logger.info(f"Attempting to fix mounts on {workstation}")
            fix_success, fix_msg = attempt_remount(workstation)
            report['actions_taken'].append(f"Remount attempt: {fix_msg}")
            
            if fix_success:
                # Re-check after fix
                success, mounts, error_msg = get_mount_status(workstation)
                report['mounts_ok'] = success
                report['mount_details'] = mounts
    else:
        report['mounts_ok'] = True
        report['mount_details'] = mounts
    
    # Log mounts to database
    action_str = ', '.join(report['actions_taken']) if report['actions_taken'] else None
    
    for mount in mounts:
        db.insert_mount_status(
            workstation, mount['mount_point'], mount['device'], 
            mount['status'], report['active_users'], action_str,
            mynetid, os.getenv('SLURM_JOB_ID')
        )
    
    # Check critical software if mounts are OK
    if report['mounts_ok']:
        for sw_config in myconfig.critical_software:
            mount_point = sw_config['mount']
            software_list = sw_config['software']
            
            # Only check if this mount is expected on this workstation
            if mount_point in expected_mounts:
                software_status = verify_software_access(
                    workstation, mount_point, software_list
                )
                
                for software, accessible in software_status.items():
                    if not accessible:
                        issue = {'software': software, 'mount': mount_point}
                        report['software_issues'].append(issue)
                        logger.warning(
                            f"Software not accessible on {workstation}: {software} at {mount_point}"
                        )
    
    db.update_workstation_status(workstation, is_online=True, 
                                 success=report['mounts_ok'], checked_by=mynetid)
    
    return report


@trap
def monitor_all_workstations() -> List[Dict]:
    """Monitor all configured workstations"""
    global myconfig, logger
    
    logger.info(f"Starting monitoring of {len(myconfig.workstations)} workstations")
    
    results = []
    for ws_config in myconfig.workstations:
        result = monitor_workstation(ws_config)
        results.append(result)
    
    # Cleanup old records using database triggers
    db.cleanup_old_records()
    logger.info("Database cleanup completed")
    
    return results


@trap
def generate_report(results: List[Dict]) -> str:
    """Generate human-readable report"""
    control_host = socket.gethostname()
    
    report_lines = [
        "=" * 70,
        "NAS Workstation Mount Status Report",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Control Host: {control_host}",
        f"User: {mynetid}",
        "=" * 70,
        ""
    ]
    
    total = len(results)
    online = sum(1 for r in results if r['online'])
    issues = sum(1 for r in results if not r['mounts_ok'] or r['software_issues'])
    
    report_lines.extend([
        "SUMMARY:",
        f"  Total Workstations: {total}",
        f"  Online: {online}",
        f"  Offline: {total - online}",
        f"  With Issues: {issues}",
        ""
    ])
    
    if issues > 0:
        report_lines.append("WORKSTATIONS WITH ISSUES:")
        report_lines.append("-" * 70)
        
        for result in results:
            if not result['mounts_ok'] or result['software_issues']:
                report_lines.append(f"\n{result['workstation']}:")
                report_lines.append(f"  Online: {result['online']}")
                report_lines.append(f"  Mounts OK: {result['mounts_ok']}")
                
                if result.get('error'):
                    report_lines.append(f"  Error: {result['error']}")
                
                if result['software_issues']:
                    report_lines.append("  Software Issues:")
                    for issue in result['software_issues']:
                        report_lines.append(
                            f"    - {issue['software']} not accessible at {issue['mount']}"
                        )
                
                if result['actions_taken']:
                    report_lines.append("  Actions Taken:")
                    for action in result['actions_taken']:
                        report_lines.append(f"    - {action}")
    else:
        report_lines.append("All workstations have healthy NAS mounts")
    
    report_lines.append("\n" + "=" * 70)
    
    return "\n".join(report_lines)


@trap
def send_email_notification(subject: str, body: str) -> None:
    """Send email notification"""
    global myconfig, logger
    
    try:
        msg = MIMEMultipart()
        msg['From'] = myconfig.notification_source
        msg['To'] = ', '.join(myconfig.notification_addresses)
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP(myconfig.smtp_server, myconfig.smtp_port) as server:
            server.send_message(msg)
        
        logger.info(f"Email notification sent: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


@trap
def nas_monitor_main(myargs: argparse.Namespace = None) -> int:
    """
    Main monitoring loop - continuous daemon that monitors all workstations.
    
    This is the primary entry point when running as a daemon. It:
    1. Loads TOML configuration file
    2. Initializes logger (URLogger with rotation)
    3. Initializes database (creates schema if needed)
    4. Sets up signal handling (ignores most signals for stability)
    5. Enters infinite monitoring loop with configurable interval
    6. Generates reports and sends notifications on issues
    
    The daemon will continue running until:
    - Killed by system administrator
    - System shutdown/reboot
    - Unhandled exception (logged via @trap decorator)
    
    Args:
        myargs: Parsed command line arguments from argparse
                Expected attributes:
                - config: Path to TOML configuration file
    
    Returns:
        os.EX_OK (0) on successful completion
        
    Exit Codes:
        os.EX_OK (0): Normal exit
        os.EX_NOINPUT (66): Config file not found
        os.EX_SOFTWARE (70): Python version too old
    
    Configuration:
        See nas_monitor.toml for all configuration options including:
        - time_interval: Seconds between monitoring cycles (default: 3600)
        - attempt_fix: Auto-remount on failure (default: true)
        - send_notifications: Email alerts (default: true)
    
    Signal Handling:
        Most signals are ignored for daemon stability. To stop:
        - Use 'kill -9 <pid>' (SIGKILL)
        - Or remove from cron and wait for completion
    """
    global myconfig, logger, db
    
    # Load configuration
    config_file = myargs.config if myargs else '/home/zeus/nas-monitor/nas_monitor.toml'
    myconfig = load_config(config_file)
    
    # Initialize logger
    logger = URLogger(logfile=myconfig.log_file, level=logging.INFO)
    logger.info(f"NAS Monitor started by {mynetid}")
    
    # Initialize database
    db = NASMonitorDB(myconfig.database, myconfig.schema_file)
    logger.info(f"Database initialized: {myconfig.database}")
    
    # Set up signal handling
    for sig in range(0, signal.SIGRTMAX):
        try:
            signal.signal(sig, signal.SIG_IGN)
        except:
            pass
    
    # Main monitoring loop
    while True:
        try:
            results = monitor_all_workstations()
            
            # Generate report
            report = generate_report(results)
            print(report)
            
            # Send notifications if configured and issues found
            if myconfig.send_notifications:
                issues = sum(1 for r in results if not r['mounts_ok'] or r['software_issues'])
                if issues > 0:
                    subject = f"NAS Mount Issues on {issues} Workstation(s)"
                    send_email_notification(subject, report)
            
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")
        
        # Sleep until next interval
        time.sleep(myconfig.time_interval)
    
    return os.EX_OK


if __name__ == '__main__':
    
    parser = argparse.ArgumentParser(prog="nas_monitor", 
        description="Monitor NAS mounts on chemistry workstations")

    parser.add_argument('-c', '--config', type=str, 
        default='/home/zeus/nas-monitor/nas_monitor.toml',
        help="Configuration file path")
    parser.add_argument('--once', action='store_true',
        help="Run once and exit (don't loop)")
    parser.add_argument('--nice', type=int, choices=range(0, 20), default=0,
        help="Niceness may affect execution time")
    parser.add_argument('-v', '--verbose', action='store_true',
        help="Be chatty about what is taking place")

    myargs = parser.parse_args()
    myargs.verbose and linuxutils.dump_cmdline(myargs)
    if myargs.nice: 
        os.nice(myargs.nice)

    try:
        if myargs.once:
            # Run once and exit
            myconfig = load_config(myargs.config)
            logger = URLogger(logfile=myconfig.log_file, level=logging.INFO)
            db = NASMonitorDB(myconfig.database, myconfig.schema_file)
            results = monitor_all_workstations()
            report = generate_report(results)
            print(report)
            sys.exit(os.EX_OK)
        else:
            # Run in daemon mode
            sys.exit(nas_monitor_main(myargs))

    except Exception as e:
        print(f"Escaped or re-raised exception: {e}")
