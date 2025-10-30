#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS Workstation Mount Monitor
Automated monitoring and maintenance of NAS mounts across lab workstations
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
import datetime
import getpass
import logging
import signal
import socket
import time
from pathlib import Path

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
import linuxutils
from urdecorators import show_exceptions_and_frames as trap
from urlogger import URLogger
from dorunrun import dorunrun

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


def is_off_hours() -> bool:
    """Check if current time is during off-hours (no email notifications)"""
    global myconfig
    
    if not hasattr(myconfig, 'off_hours_start') or not hasattr(myconfig, 'off_hours_end'):
        return False  # If not configured, never suppress
    
    current_hour = datetime.datetime.now().hour
    start = myconfig.off_hours_start
    end = myconfig.off_hours_end
    
    # Handle overnight periods (e.g., 19:00 to 05:00)
    if start > end:
        return current_hour >= start or current_hour < end
    else:
        return start <= current_hour < end


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
    result = dorunrun(cmd, timeout=5)
    return result.get('code', -1) == 0


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
    result = dorunrun(cmd, timeout=myconfig.ssh_timeout)
    exit_code, stdout, stderr = result.get("code", -1), result.get("stdout", ""), result.get("stderr", "")
    
    # Debug logging
    logger.debug(f"{workstation}: mount -av exit code: {exit_code}")
    if stderr:
        logger.info(f"{workstation}: mount -av stderr: {stderr}")
    logger.debug(f"{workstation}: mount -av stdout lines: {len(stdout.splitlines())}")
    
    # Parse mount output - get both regular output and errors
    mounts = []
    
    # First, check stderr for mount.nfs errors
    if stderr:
        logger.debug(f"{workstation}: Processing {len(stderr.splitlines())} stderr lines")
    for line in stderr.splitlines():
        logger.debug(f"{workstation}: stderr line: {line}")
        if line.startswith('mount.nfs:'):
            if 'does not exist' in line:
                # Extract mount point from error message
                # "mount.nfs: mount point /franksinatra/logP does not exist"
                parts = line.split('mount point')
                if len(parts) > 1:
                    mount_point = parts[1].split('does not exist')[0].strip()
                    mount_info = {
                        'device': '',
                        'mount_point': mount_point,
                        'status': 'directory_missing'
                    }
                    mounts.append(mount_info)
                    logger.warning(f"Mount point missing: {mount_point}")
            elif 'Connection timed out' in line or 'Connection refused' in line or 'access denied' in line.lower():
                # Log NFS connection errors but without specific mount point
                # These will be caught by the regular parsing if mount point is in output
                logger.error(f"NFS mount error: {line}")
            else:
                # Log other mount.nfs errors for debugging
                logger.debug(f"mount.nfs message: {line}")
    
    # Parse regular stdout output
    for line in stdout.splitlines():
        # Skip empty lines
        if not line.strip():
            continue
            
        # Look for mount status lines: "mount_point : status"
        # Examples:
        #   "/usr/local/chem.sw       : already mounted"
        #   "/boot                    : already mounted"
        #   "none                     : ignored"
        if ' : ' in line:
            try:
                # Split by ' : ' to get mount_point and status
                parts = line.split(' : ', 1)
                if len(parts) == 2:
                    mount_point = parts[0].strip()
                    status_text = parts[1].strip()
                    
                    # Skip ignored mounts and root filesystem
                    if 'ignored' in status_text.lower() or mount_point == '/':
                        continue
                    
                    # Device will be empty - we'd need to parse 'mount' output to get it
                    # For now, this is sufficient for mount status tracking
                    device = ''
                    
                    # Determine status from mount -av output
                    if 'already mounted' in status_text.lower():
                        status = 'mounted'
                    elif 'successfully mounted' in status_text.lower() or 'mounted' in status_text.lower():
                        status = 'newly_mounted'
                    elif 'failed' in status_text.lower() or 'error' in status_text.lower():
                        status = 'failed'
                    elif 'not mounted' in status_text.lower():
                        status = 'not_mounted'
                    else:
                        status = 'unknown'
                    
                    mount_info = {
                        'device': device,
                        'mount_point': mount_point,
                        'status': status
                    }
                    mounts.append(mount_info)
            except Exception:
                # Skip lines we can't parse
                continue
    
    # Check if any mounts have failure status
    has_failures = any(m.get('status') in ['failed', 'directory_missing', 'not_mounted', 'unknown'] 
                       for m in mounts)
    
    # If we found mounts, return them along with success/failure indication
    if mounts:
        if has_failures:
            logger.warning(f"Mount check completed with failures")
        return True, mounts, ""  # Return True because we got data, failures are in the mount list
    
    # Only return failure if exit code is bad AND we found no mounts
    if exit_code != 0:
        return False, [], stderr
    
    return True, mounts, ""


@trap

@trap
def check_mount_point_directories(workstation: str, expected_mounts: List[str]) -> Dict[str, str]:
    """
    Check if mount point directories exist on workstation
    
    Args:
        workstation: Hostname
        expected_mounts: List of mount point paths that should exist
        
    Returns:
        Dict mapping mount_point to status:
            'exists' - directory exists
            'missing' - directory does not exist
            'error' - could not check
    """
    global myconfig, logger
    
    if not expected_mounts:
        return {}
    
    # Build command to check all mount points in one SSH call
    check_cmds = []
    for mp in expected_mounts:
        # Escape single quotes in mount point path
        safe_mp = mp.replace("'", "'\\''")
        check_cmds.append(f"test -d '{safe_mp}' && echo '{safe_mp}:EXISTS' || echo '{safe_mp}:MISSING'")
    
    cmd_str = ' ; '.join(check_cmds)
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, cmd_str]
    result = dorunrun(cmd, timeout=10)
    
    status_map = {}
    if result.get('code') == 0:
        for line in result.get('stdout', '').splitlines():
            if ':EXISTS' in line:
                mp = line.replace(':EXISTS', '').strip()
                status_map[mp] = 'exists'
            elif ':MISSING' in line:
                mp = line.replace(':MISSING', '').strip()
                status_map[mp] = 'missing'
                logger.warning(f"{workstation}: Mount point directory missing: {mp}")
    else:
        logger.error(f"{workstation}: Failed to check mount point directories")
        for mp in expected_mounts:
            status_map[mp] = 'error'
    
    return status_map


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
        software_list: List of software names to verify (e.g., ['amber', 'Columbus', 'gaussian'])
    
    Returns:
        Dictionary mapping software names to accessibility boolean:
        Example: {'amber': True, 'Columbus': True, 'gaussian': False}
        
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
        
        result = dorunrun(cmd, timeout=10)
        exit_code, stdout, stderr = result.get("code", -1), result.get("stdout", ""), result.get("stderr", "")
        results[software] = 'OK' in stdout
        
        # Log to database
        db.add_software_check(workstation, software, mount_point, results[software])
    
    return results


@trap
def attempt_remount(workstation: str, mount_point: str = None) -> Tuple[bool, str]:
    """Attempt to remount NAS directories on workstation
    
    Args:
        workstation: Hostname
        mount_point: Specific mount point to remount, or None for all mounts
    """
    global myconfig, logger
    
    if mount_point:
        # Try to remount specific mount point
        cmd = ['ssh'] + myconfig.ssh_options + [workstation, f'sudo mount {mount_point}']
        logger.info(f"Attempting to remount {mount_point} on {workstation}")
    else:
        # Remount all
        cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'sudo mount -a']
        logger.info(f"Attempting to remount all on {workstation}")
    
    result = dorunrun(cmd, timeout=60)
    exit_code, stdout, stderr = result.get("code", -1), result.get("stdout", ""), result.get("stderr", "")
    
    if exit_code == 0:
        logger.info(f"Successfully remounted on {workstation}")
        return True, "Remount successful"
    else:
        logger.error(f"Failed to remount on {workstation}: {stderr}")
        return False, stderr


@trap
@trap
def get_active_users(workstation: str) -> tuple:
    """Get active user count and list of usernames on workstation
    
    Returns:
        tuple: (user_count, user_list_string)
            user_count: Number of active users
            user_list_string: Comma-separated list of up to 3 usernames, 
                             or None if no users
    """
    global myconfig
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'who']
    result = dorunrun(cmd, timeout=10)
    exit_code, stdout, stderr = result.get("code", -1), result.get("stdout", ""), result.get("stderr", "")
    
    if exit_code == 0:
        users = set()
        for line in stdout.splitlines():
            parts = line.split()
            if parts:
                users.add(parts[0])
        
        user_count = len(users)
        if user_count == 0:
            return 0, None
        
        # Sort and limit to first 3 users
        sorted_users = sorted(users)
        if user_count <= 3:
            user_list = ','.join(sorted_users)
        else:
            user_list = ','.join(sorted_users[:3]) + f',+{user_count-3}'
        
        return user_count, user_list
    
    return 0, None

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
        'user_list': None,
        'mount_details': [],
        'software_issues': [],
        'actions_taken': []
    }
    
    # Check if workstation is online
    if not check_workstation_online(workstation):
        logger.warning(f"{workstation} is offline")
        db.update_workstation_status(workstation, is_online=False, active_users=0,
                                             user_list=None, checked_by=mynetid)
        return report
    
    report['online'] = True
    
    # Count active users if configured
    if myconfig.track_users:
        report['active_users'], report['user_list'] = get_active_users(workstation)
    else:
        report['user_list'] = None
    
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
        report['mount_details'] = mounts
        # Check if any mounts have failure status
        failed_mounts = [m for m in mounts if m.get('status') in ['failed', 'directory_missing', 'not_mounted', 'unknown']]
        has_failures = len(failed_mounts) > 0
        report['mounts_ok'] = not has_failures
        
        # Attempt to fix failed mounts
        if has_failures and myconfig.attempt_fix:
            for failed_mount in failed_mounts:
                mount_point = failed_mount['mount_point']
                logger.info(f"Attempting to fix failed mount on {workstation}: {mount_point}")
                fix_success, fix_msg = attempt_remount(workstation, mount_point)
                report['actions_taken'].append(f"Remount {mount_point}: {fix_msg}")
                
                if fix_success:
                    # Re-check this specific mount
                    success_recheck, mounts_recheck, _ = get_mount_status(workstation)
                    if success_recheck:
                        # Update the mount in our list
                        for i, m in enumerate(report['mount_details']):
                            if m['mount_point'] == mount_point:
                                recheck_mount = next((rm for rm in mounts_recheck if rm['mount_point'] == mount_point), None)
                                if recheck_mount:
                                    report['mount_details'][i] = recheck_mount
                        # Re-evaluate if we still have failures
                        failed_mounts = [m for m in report['mount_details'] if m.get('status') in ['failed', 'directory_missing', 'not_mounted', 'unknown']]
                        report['mounts_ok'] = len(failed_mounts) == 0
    
    # Log mounts to database
    action_str = ', '.join(report['actions_taken']) if report['actions_taken'] else None
    
    for mount in mounts:
        db.add_mount_status(
            workstation, mount['mount_point'], mount['device'], 
            mount['status'], report['active_users'], action_str,
            mynetid, os.getenv('SLURM_JOB_ID')
        )
    
    # Check critical software if mounts are OK and workstation is still online
    if report['mounts_ok']:
        # Verify workstation is still online before checking software (can take time)
        if not check_workstation_online(workstation):
            logger.warning(f"{workstation} went offline during monitoring")
            report['online'] = False
            db.update_workstation_status(workstation, is_online=False, active_users=0,
                                        user_list=None, checked_by=mynetid)
            return report
        
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
                                         success=report['mounts_ok'],
                                         active_users=report['active_users'],
                                         user_list=report['user_list'],
                                         checked_by=mynetid)
    
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
    """Send email notification using system mail command"""
    global myconfig, logger
    
    try:
        import subprocess
        
        # Use system mail command (works with sendmail/postfix)
        # Create mail command with each recipient as separate argument
        cmd = ['mail', '-s', subject]
        if hasattr(myconfig, 'notification_source') and myconfig.notification_source:
            cmd.extend(['-r', myconfig.notification_source])
        # Add all recipients as separate arguments
        cmd.extend(myconfig.notification_addresses)
        
        # Send email using subprocess with stdin
        result = subprocess.run(
            cmd,
            input=body.encode('utf-8'),
            capture_output=True,
            timeout=30
        )
        
        if result.returncode == 0:
            recipients_str = ', '.join(myconfig.notification_addresses)
            logger.info(f"Email notification sent: {subject} to {recipients_str}")
        else:
            stderr = result.stderr.decode('utf-8', errors='ignore')
            logger.error(f"Failed to send email: {stderr}")
            
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


@trap

def send_off_hours_summary() -> None:
    """Send consolidated email of all issues detected during off-hours"""
    global myconfig, logger, db
    
    issues = db.get_off_hours_issues(unnotified_only=True)
    
    if not issues:
        logger.info("No off-hours issues to report")
        return
    
    # Group issues by workstation
    by_workstation = {}
    for issue_id, workstation, issue_type, details, detected_at in issues:
        if workstation not in by_workstation:
            by_workstation[workstation] = []
        by_workstation[workstation].append({
            'type': issue_type,
            'details': details,
            'time': detected_at
        })
    
    # Generate summary report
    report_lines = [
        "=" * 70,
        "NAS Workstation Monitor - Off-Hours Summary",
        f"Issues Detected: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Control Host: {socket.gethostname()}",
        "=" * 70,
        "",
        f"Total Workstations with Issues: {len(by_workstation)}",
        ""
    ]
    
    for workstation in sorted(by_workstation.keys()):
        report_lines.append("-" * 70)
        report_lines.append(f"{workstation}:")
        
        # Group by issue type
        issues_by_type = {}
        for issue in by_workstation[workstation]:
            issue_type = issue['type']
            if issue_type not in issues_by_type:
                issues_by_type[issue_type] = []
            issues_by_type[issue_type].append(issue)
        
        for issue_type, type_issues in issues_by_type.items():
            report_lines.append(f"  {issue_type.replace('_', ' ').title()}:")
            # Show most recent occurrence
            most_recent = max(type_issues, key=lambda x: x['time'])
            report_lines.append(f"    First: {type_issues[-1]['time']}")
            report_lines.append(f"    Last: {most_recent['time']}")
            report_lines.append(f"    Count: {len(type_issues)}")
            if most_recent['details']:
                report_lines.append(f"    Details: {most_recent['details']}")
        report_lines.append("")
    
    report_lines.append("=" * 70)
    
    report = "\n".join(report_lines)
    
    # Send email
    subject = f"NAS Monitor Off-Hours Summary: {len(by_workstation)} Workstation(s) with Issues"
    send_email_notification(subject, report)
    
    # Mark as notified
    count = db.mark_off_hours_issues_notified()
    logger.info(f"Off-hours summary sent for {count} issues across {len(by_workstation)} workstations")
    
    print(report)


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
                issues = sum(1 for r in results if not r['online'] or not r['mounts_ok'] or r['software_issues'])
                if issues > 0:
                    subject = f"NAS Monitor Alert: {issues} Workstation(s) with Issues"
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
        default='/home/zeus/nas-workstation-monitor/nas_monitor.toml',
        help="Configuration file path")
    parser.add_argument('--once', action='store_true',
    parser.add_argument('--send-off-hours-summary', action='store_true',
        help='Send summary of off-hours issues and exit')
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
        if myargs.send_off_hours_summary:
            # Send off-hours summary and exit
            myconfig = load_config(myargs.config)
            logger = URLogger(logfile=myconfig.log_file, level=logging.INFO)
            db = NASMonitorDB(myconfig.database, myconfig.schema_file)
            send_off_hours_summary()
            sys.exit(os.EX_OK)
        elif myargs.once:
            # Run once and exit
            myconfig = load_config(myargs.config)
            logger = URLogger(logfile=myconfig.log_file, level=logging.INFO)
            db = NASMonitorDB(myconfig.database, myconfig.schema_file)
            results = monitor_all_workstations()
            report = generate_report(results)
            print(report)
            
            # Send notifications if configured and issues found
            if myconfig.send_notifications:
                issues = sum(1 for r in results if not r['online'] or not r['mounts_ok'] or r['software_issues'])
                if issues > 0:
                    # Check if we're in off-hours
                    if is_off_hours():
                        # Log issues for morning summary instead of sending email
                        logger.info(f"Off-hours: Logging {issues} workstation issues for morning summary")
                        for r in results:
                            if not r['online']:
                                db.log_off_hours_issue(r['workstation'], 'offline', 'Workstation is offline')
                            elif not r['mounts_ok']:
                                mount_details = ', '.join([f"{m['mount_point']}: {m['status']}" 
                                                          for m in r.get('mount_details', []) 
                                                          if m.get('status') not in ['mounted', 'newly_mounted']])
                                db.log_off_hours_issue(r['workstation'], 'mount_failure', mount_details)
                            if r['software_issues']:
                                software_details = ', '.join([f"{s['software']} at {s['mount']}" 
                                                             for s in r['software_issues']])
                                db.log_off_hours_issue(r['workstation'], 'software_issue', software_details)
                    else:
                        # Business hours - send email immediately
                        subject = f"NAS Monitor Alert: {issues} Workstation(s) with Issues"
                        send_email_notification(subject, report)
                        logger.info(f"Email notification sent for {issues} workstation(s) with issues")
            
            sys.exit(os.EX_OK)
        else:
            # Run in daemon mode
            sys.exit(nas_monitor_main(myargs))

    except Exception as e:
        print(f"Escaped or re-raised exception: {e}")
