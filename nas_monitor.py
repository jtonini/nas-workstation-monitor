#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS Workstation Mount Monitor - Enhanced Version 2.0
Automated monitoring and maintenance of NAS mounts across lab workstations
Now distinguishes between connectivity issues and actual mount failures
"""
import typing
from typing import *

min_py = (3, 9)

import argparse
import datetime
import os
import pathlib
import socket
import sys
import time
import toml

# Import hpclib modules
from dorunrun import dorunrun, ExitCode
from linuxutils import *
from nas_monitor_dbclass import NASMonitorDB
from sqlitedb import SQLiteDB
from urdecorators import trap
from urlogger import URLogger

# Global variables
myconfig = None
logger = None
db = None

@trap
def is_host_online(hostname: str) -> bool:
    """
    Check if a host is reachable via ping.
    
    Args:
        hostname: Target hostname to check
        
    Returns:
        bool: True if host responds to ping, False otherwise
    """
    global myconfig
    
    # Use ping with timeout
    result = dorunrun(['ping', '-c', '2', '-W', '2', hostname], timeout=5)
    return result.code == 0

@trap
def get_mount_status(workstation: str) -> Tuple[str, List[Dict], str]:
    """
    Get mount status from workstation using SSH 'mount -av' command.
    
    Enhanced to distinguish between connection failures and mount issues.
    
    Returns:
        Tuple of (status_type, mount_list, error_message):
        - status_type: 'success', 'connection_failed', or 'command_failed'
        - mount_list: List of mount information dicts
        - error_message: Error details if command failed
    """
    global myconfig

    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'mount -av']
    
    try:
        result = dorunrun(cmd, timeout=myconfig.ssh_timeout)
    except TimeoutError:
        logger.error(f"{workstation}: SSH connection timeout")
        return 'connection_failed', [], "SSH connection timeout"
    except Exception as e:
        logger.error(f"{workstation}: SSH connection failed: {str(e)}")
        return 'connection_failed', [], f"SSH connection error: {str(e)}"
    
    # Check SSH-specific error codes
    if result.code == 255:
        return 'connection_failed', [], "SSH connection failed (code 255)"
    elif result.code == 124:
        return 'connection_failed', [], "SSH command timeout"
    elif result.code == 1:
        # SSH connected but mount command had issues
        return 'command_failed', [], f"Mount command error: {result.stderr}"
    elif result.code != 0:
        return 'command_failed', [], f"Mount command failed with code {result.code}"
    
    # Parse successful output
    stdout = result.stdout
    stderr = result.stderr
    
    if stderr:
        logger.info(f"{workstation}: mount -av stderr: {stderr}")
    
    # Parse mount output
    mounts = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
            
        # Look for mount status lines
        if ' : ' in line:
            try:
                mount_point, status_msg = line.split(' : ', 1)
                mount_point = mount_point.strip()
                status_msg = status_msg.strip()
                
                # Determine mount status
                if 'already mounted' in status_msg.lower():
                    status = 'mounted'
                elif 'mounted' in status_msg.lower():
                    status = 'newly_mounted'
                elif 'ignored' in status_msg.lower():
                    continue  # Skip ignored entries
                else:
                    status = 'unknown'
                
                # Extract device info if available
                device = ''
                if ' on ' in line:
                    device = line.split(' on ')[0].strip()
                
                mounts.append({
                    'device': device,
                    'mount_point': mount_point,
                    'status': status
                })
                
            except ValueError as e:
                logger.debug(f"Could not parse mount line: {line}")
                continue
    
    return 'success', mounts, ""

@trap
def check_mount_point_directories(workstation: str, expected_mounts: List[str]) -> Dict[str, str]:
    """
    Check if mount point directories exist on the workstation.
    
    Args:
        workstation: Target hostname
        expected_mounts: List of mount point paths that should exist
        
    Returns:
        Dictionary mapping mount points to status ('exists', 'missing', 'error')
    """
    global myconfig
    results = {}
    
    if not expected_mounts:
        return results
    
    # Build command to check all mount points at once
    checks = ' && '.join([f'test -d "{mp}" && echo "{mp}:exists" || echo "{mp}:missing"' 
                          for mp in expected_mounts])
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, f'bash -c \'{checks}\'']
    
    try:
        result = dorunrun(cmd, timeout=myconfig.ssh_timeout)
        
        if result.code == 0:
            for line in result.stdout.splitlines():
                if ':' in line:
                    mp, status = line.rsplit(':', 1)
                    results[mp] = status
        else:
            for mp in expected_mounts:
                results[mp] = 'error'
                
    except Exception as e:
        logger.error(f"Failed to check mount directories on {workstation}: {e}")
        for mp in expected_mounts:
            results[mp] = 'error'
    
    return results

@trap
def verify_software_access(workstation: str, mount_point: str, software_list: List[str]) -> Dict[str, bool]:
    """
    Verify that critical software is accessible on a mount point.
    
    Args:
        workstation: Hostname to check
        mount_point: Base mount path (e.g., '/usr/local/chem.sw')
        software_list: List of software names to verify
        
    Returns:
        Dictionary mapping software names to accessibility boolean
    """
    global myconfig
    global db
    
    results = {}
    
    if not software_list:
        return results
    
    for software in software_list:
        software_path = f"{mount_point}/{software}"
        cmd = ['ssh'] + myconfig.ssh_options + [
            workstation, f'test -e "{software_path}" && echo "1" || echo "0"'
        ]
        
        try:
            result = dorunrun(cmd, timeout=10)
            accessible = result.stdout.strip() == '1'
            results[software] = accessible
            
            # Log to database
            db.record_software_check(workstation, software, software_path, accessible)
            
        except Exception as e:
            logger.error(f"Failed to check {software} on {workstation}: {e}")
            results[software] = False
            db.record_software_check(workstation, software, software_path, False, str(e))
    
    return results

@trap
def attempt_remount(workstation: str, mount_point: str = None) -> bool:
    """
    Attempt to remount filesystem(s) on workstation.
    
    Args:
        workstation: Target hostname
        mount_point: Specific mount point or None for all
        
    Returns:
        bool: True if remount succeeded
    """
    global myconfig
    
    if mount_point:
        logger.info(f"Attempting to remount {mount_point} on {workstation}")
        cmd_str = f'sudo mount {mount_point}'
    else:
        logger.info(f"Attempting to remount all on {workstation}")
        cmd_str = 'sudo mount -a'
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, cmd_str]
    
    try:
        result = dorunrun(cmd, timeout=60)
        
        if result.code == 0:
            logger.info(f"Successfully remounted on {workstation}")
            return True
        else:
            logger.error(f"Failed to remount on {workstation}: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Remount attempt failed on {workstation}: {e}")
        return False

@trap
def count_active_users(workstation: str) -> Tuple[int, Optional[str]]:
    """
    Count number of active users on workstation.
    
    Returns:
        Tuple of (user_count, comma_separated_user_list)
    """
    global myconfig
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'who | cut -d" " -f1 | sort -u']
    
    try:
        result = dorunrun(cmd, timeout=10)
        if result.code == 0 and result.stdout.strip():
            users = result.stdout.strip().split('\n')
            user_count = len(users)
            user_list = ','.join(users)
            return user_count, user_list
    except Exception as e:
        logger.debug(f"Could not count users on {workstation}: {e}")
    
    return 0, None

@trap
def monitor_workstation(workstation_config: Dict) -> Dict:
    """
    Monitor a single workstation's NAS mounts with improved error classification.
    
    Distinguishes between:
    - Connectivity issues (can't reach the workstation)
    - Mount failures (workstation reachable but mounts have problems)
    - Successful checks
    
    Args:
        workstation_config: Dictionary with 'host' and 'mounts' keys
        
    Returns:
        Dictionary containing monitoring results with issue classification
    """
    global myconfig
    global db
    global logger
    
    workstation = workstation_config['host']
    expected_mounts = workstation_config['mounts']
    
    report = {
        'workstation': workstation,
        'timestamp': datetime.datetime.now().isoformat(),
        'online': None,
        'connectivity': 'unknown',
        'mounts': {},
        'software': {},
        'issues': [],
        'users': 0
    }
    
    logger.info(f"Checking workstation: {workstation}")
    mynetid = os.environ.get('USER', 'unknown')
    
    # First check if host is reachable
    if not is_host_online(workstation):
        report['online'] = False
        report['connectivity'] = 'unreachable'
        logger.warning(f"{workstation} is offline")
        
        # Record connectivity issue
        db.record_connectivity_issue(workstation, 'host_unreachable', 
                                    'Ping failed - host is offline or unreachable')
        db.update_workstation_status(workstation, is_online=False, active_users=0,
                                    user_list=None, checked_by=mynetid)
        
        report['issues'].append({
            'type': 'connectivity',
            'severity': 'critical',
            'message': 'Workstation is offline or unreachable',
            'requires_action': False
        })
        return report
    
    report['online'] = True
    
    # Count active users if configured
    if myconfig.track_users:
        user_count, user_list = count_active_users(workstation)
        report['users'] = user_count
        if user_count > 0:
            logger.info(f"{workstation} has {user_count} active users: {user_list}")
    
    # Get mount status
    status_type, mount_list, error_msg = get_mount_status(workstation)
    
    if status_type == 'connection_failed':
        # SSH/network issue - not a mount problem
        report['connectivity'] = 'ssh_failed'
        
        # Record this as a connectivity issue, not a mount failure
        db.record_connectivity_issue(workstation, 'ssh_failed', error_msg)
        
        report['issues'].append({
            'type': 'connectivity',
            'severity': 'warning',
            'message': f"Cannot verify mounts - SSH failed: {error_msg}",
            'requires_action': False
        })
        
        logger.warning(f"{workstation}: Connectivity issue (SSH failed) - {error_msg}")
        
        # Don't report mount failures if we can't connect
        # But update status to indicate uncertainty
        db.update_workstation_status(workstation, is_online=True, 
                                    connectivity='ssh_failed',
                                    active_users=report['users'],
                                    checked_by=mynetid)
        return report
    
    elif status_type == 'command_failed':
        # Connected but mount command had issues
        report['connectivity'] = 'connected'
        report['issues'].append({
            'type': 'command_error',
            'severity': 'warning',
            'message': f"Mount command error: {error_msg}",
            'requires_action': True
        })
        logger.warning(f"{workstation}: Mount command failed but connected")
    
    else:
        # Successfully got mount status
        report['connectivity'] = 'connected'
        
        # Clear any previous connectivity issues
        db.resolve_connectivity_issues(workstation)
        
        # Check each expected mount
        mounted_points = {m['mount_point']: m for m in mount_list}
        
        for mount_point in expected_mounts:
            if mount_point in mounted_points:
                # Mount is healthy
                report['mounts'][mount_point] = 'mounted'
                db.record_mount_status(workstation, mount_point, 
                                     mounted_points[mount_point].get('device', ''),
                                     'nfs', 'mounted')
            else:
                # This is an actual mount failure
                report['mounts'][mount_point] = 'not_mounted'
                report['issues'].append({
                    'type': 'mount_failure',
                    'severity': 'critical',
                    'mount_point': mount_point,
                    'message': f"{mount_point} is not mounted",
                    'requires_action': True
                })
                
                db.record_mount_status(workstation, mount_point, '', 'nfs', 
                                     'not_mounted', error_message='Mount point not found')
                
                # Attempt to fix if configured and no users active
                if myconfig.attempt_fix and report['users'] == 0:
                    logger.info(f"Attempting to fix mounts on {workstation}")
                    if attempt_remount(workstation):
                        # Re-check mount status
                        _, new_mounts, _ = get_mount_status(workstation)
                        new_mounted = {m['mount_point']: m for m in new_mounts}
                        
                        if mount_point in new_mounted:
                            report['mounts'][mount_point] = 'remounted'
                            db.record_mount_status(workstation, mount_point,
                                                 new_mounted[mount_point].get('device', ''),
                                                 'nfs', 'newly_mounted',
                                                 action_taken='Auto-remounted successfully')
                            logger.info(f"Successfully remounted {mount_point} on {workstation}")
                        else:
                            logger.error(f"Remount of {mount_point} on {workstation} failed")
                elif report['users'] > 0:
                    logger.info(f"Skipping auto-fix on {workstation} - users active")
    
    # Check critical software if mounts are OK
    for sw_config in myconfig.critical_software:
        mount_point = sw_config['mount']
        software_list = sw_config['software']
        
        # Only check if this mount is expected and mounted
        if mount_point in expected_mounts and report['mounts'].get(mount_point) in ['mounted', 'remounted']:
            software_status = verify_software_access(workstation, mount_point, software_list)
            
            for software, accessible in software_status.items():
                report['software'][software] = accessible
                if not accessible:
                    report['issues'].append({
                        'type': 'software_missing',
                        'severity': 'warning',
                        'software': software,
                        'mount_point': mount_point,
                        'message': f"Software {software} not accessible on {mount_point}",
                        'requires_action': False
                    })
    
    # Update database with final status
    db.update_workstation_status(
        workstation,
        is_online=True,
        connectivity=report['connectivity'],
        active_users=report['users'],
        mount_status='healthy' if not report['issues'] else 'issues',
        checked_by=mynetid
    )
    
    return report

@trap
def monitor_all_workstations(workstation_configs: List[Dict]) -> List[Dict]:
    """
    Monitor all configured workstations.
    
    Args:
        workstation_configs: List of workstation configurations
        
    Returns:
        List of monitoring reports
    """
    global db
    global logger
    
    results = []
    
    for ws_config in workstation_configs:
        result = monitor_workstation(ws_config)
        results.append(result)
    
    # Cleanup old records
    mount_deleted, software_deleted, failures_deleted = db.cleanup_old_records()
    logger.info(f"Database cleanup: {mount_deleted} mount, {software_deleted} software, "
               f"{failures_deleted} failure records removed")
    
    return results

@trap
def generate_summary_report(results: List[Dict]) -> str:
    """
    Generate a human-readable summary report with improved issue classification.
    
    Separates:
    - Critical issues (actual mount failures)
    - Warnings (connectivity issues, software issues)
    - Informational items
    """
    total = len(results)
    online = sum(1 for r in results if r['online'])
    offline = sum(1 for r in results if not r['online'])
    
    # Classify issues
    mount_failures = []
    connectivity_issues = []
    other_issues = []
    
    for result in results:
        workstation = result['workstation']
        for issue in result.get('issues', []):
            issue['workstation'] = workstation
            
            if issue['type'] == 'mount_failure':
                mount_failures.append(issue)
            elif issue['type'] == 'connectivity':
                connectivity_issues.append(issue)
            else:
                other_issues.append(issue)
    
    # Build report
    lines = [
        "=" * 70,
        "NAS Workstation Mount Status Report",
        f"Generated: {datetime.datetime.now()}",
        f"Control Host: {socket.gethostname()}",
        f"User: {os.environ.get('USER', 'unknown')}",
        "=" * 70,
        "",
        "SUMMARY:",
        f"  Total Workstations: {total}",
        f"  Online: {online}",
        f"  Offline: {offline}",
        f"  Mount Failures: {len(mount_failures)}",
        f"  Connectivity Issues: {len(connectivity_issues)}",
        ""
    ]
    
    if mount_failures:
        lines.append("CRITICAL - MOUNT FAILURES:")
        lines.append("-" * 70)
        for issue in mount_failures:
            lines.append(f"{issue['workstation']}: {issue['mount_point']} - NOT MOUNTED")
        lines.append("")
    
    if connectivity_issues:
        lines.append("WARNING - CONNECTIVITY ISSUES:")
        lines.append("-" * 70)
        for issue in connectivity_issues:
            lines.append(f"{issue['workstation']}: {issue['message']}")
        lines.append("Note: Mount status cannot be verified for these workstations")
        lines.append("")
    
    if other_issues:
        lines.append("OTHER ISSUES:")
        lines.append("-" * 70)
        for issue in other_issues:
            lines.append(f"{issue['workstation']}: {issue['message']}")
        lines.append("")
    
    if not mount_failures and not connectivity_issues and not other_issues:
        lines.append("All workstations have healthy NAS mounts")
    
    lines.append("=" * 70)
    
    return "\n".join(lines)

@trap
def should_suppress_notification() -> bool:
    """
    Check if we're in off-hours or weekend suppression period.
    """
    global myconfig
    
    if not hasattr(myconfig, 'off_hours_start') or not hasattr(myconfig, 'off_hours_end'):
        return False
    
    now = datetime.datetime.now()
    current_hour = now.hour
    weekday = now.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
    
    # Check weekend suppression
    if hasattr(myconfig, 'suppress_weekends') and myconfig.suppress_weekends:
        # Friday after 6 PM
        if weekday == 4 and current_hour >= 18:
            return True
        # All day Saturday and Sunday
        if weekday in [5, 6]:
            return True
        # Monday before 6 AM
        if weekday == 0 and current_hour < 6:
            return True
    
    # Check daily off-hours
    start = myconfig.off_hours_start
    end = myconfig.off_hours_end
    
    # Handle overnight periods (e.g., 18:00 to 06:00)
    if start > end:
        return current_hour >= start or current_hour < end
    else:
        return start <= current_hour < end

def send_notification(subject: str, message: str):
    """
    Send email notification.
    """
    global myconfig
    global logger
    
    if not myconfig.send_notifications:
        return
    
    if should_suppress_notification():
        logger.info("Notification suppressed due to off-hours/weekend setting")
        # Store for later off-hours summary
        db.store_off_hours_issue(message)
        return
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg['From'] = myconfig.notification_source
        msg['To'] = ', '.join(myconfig.notification_addresses)
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        
        with smtplib.SMTP(myconfig.smtp_server, myconfig.smtp_port) as server:
            server.send_message(msg)
        
        logger.info(f"Notification sent: {subject}")
        
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

def send_off_hours_summary():
    """
    Send summary of issues detected during off-hours.
    """
    global db
    global myconfig
    global logger
    
    issues = db.get_off_hours_issues()
    
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
        f"Issues Detected: {datetime.datetime.now()}",
        f"Control Host: {socket.gethostname()}",
        "=" * 70,
        "",
        f"Total Workstations with Issues: {len(by_workstation)}",
        ""
    ]
    
    for workstation in sorted(by_workstation.keys()):
        report_lines.append("-" * 70)
        report_lines.append(f"{workstation}:")
        
        # Separate by issue type
        mount_issues = [i for i in by_workstation[workstation] if 'mount' in i['type'].lower()]
        conn_issues = [i for i in by_workstation[workstation] if 'connect' in i['type'].lower() or 'ssh' in i['type'].lower()]
        
        if mount_issues:
            report_lines.append("  Mount Failures:")
            for issue in mount_issues:
                report_lines.append(f"    {issue['details']} (at {issue['time']})")
        
        if conn_issues:
            report_lines.append("  Connectivity Issues:")
            for issue in conn_issues:
                report_lines.append(f"    {issue['details']} (at {issue['time']})")
    
    report_lines.append("")
    report_lines.append("=" * 70)
    
    report = "\n".join(report_lines)
    
    # Send the summary
    send_notification(
        f"NAS Monitor Off-Hours Summary: {len(by_workstation)} Workstation(s) with Issues",
        report
    )
    
    # Clear the off-hours issues after sending
    db.clear_off_hours_issues()

def main():
    """Main entry point."""
    global myconfig
    global logger
    global db
    
    parser = argparse.ArgumentParser(
        prog='nas_monitor',
        description='NAS Workstation Mount Monitor'
    )
    
    parser.add_argument('-c', '--config', type=str,
                       default='/home/zeus/nas-workstation-monitor/nas_monitor.toml',
                       help='Configuration file path')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit')
    parser.add_argument('--send-off-hours-summary', action='store_true',
                       help='Send off-hours summary and exit')
    parser.add_argument('--nice', type=int, default=0, choices=range(20),
                       help='Nice level (0-19)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    
    args = parser.parse_args()
    
    # Set nice level
    if args.nice > 0:
        os.nice(args.nice)
    
    # Load configuration
    with open(args.config, 'r') as f:
        config_dict = toml.load(f)
    
    # Convert to object notation
    class Config:
        def __init__(self, d):
            for key, value in d.items():
                if isinstance(value, dict):
                    setattr(self, key, Config(value))
                else:
                    setattr(self, key, value)
    
    myconfig = Config(config_dict)
    
    # Initialize logger
    logger = URLogger(logfile=myconfig.log_file, level='DEBUG' if args.verbose else 'INFO')
    
    # Initialize database
    db = NASMonitorDB(myconfig.database, myconfig.schema_file)
    
    # Handle off-hours summary
    if args.send_off_hours_summary:
        send_off_hours_summary()
        return 0
    
    # Run monitoring
    try:
        while True:
            results = monitor_all_workstations(myconfig.workstations)
            
            # Generate and print summary
            summary = generate_summary_report(results)
            print(summary)
            
            # Log to file
            logger.info(summary)
            
            # Send notifications for critical issues
            critical_issues = [r for r in results if any(
                i['severity'] == 'critical' and i['type'] == 'mount_failure' 
                for i in r.get('issues', [])
            )]
            
            if critical_issues:
                send_notification(
                    f"NAS Mount Alert: {len(critical_issues)} workstation(s) with mount failures",
                    summary
                )
            
            if args.once:
                break
            
            # Wait for next cycle
            time.sleep(myconfig.time_interval)
            
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Monitor failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
