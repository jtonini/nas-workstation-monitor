#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS Workstation Mount Monitor
Automated monitoring and maintenance of NAS mounts across lab workstations
Version 1.1 - Improved error classification for better reporting
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
import tomli as toml  # Changed from 'toml' to 'tomli' for compatibility

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

def classify_mount_issue(workstation: str, error_msg: str = "") -> tuple:
    """
    Classify if the issue is connectivity-related or an actual mount failure.
    
    Returns: (issue_type, severity, description)
        issue_type: 'connectivity' or 'mount_failure'
        severity: 'warning' or 'critical'
        description: Human-readable description
    """
    if not error_msg:
        # No error message often means SSH worked but mount is missing
        return ('mount_failure', 'critical', 'Mount point not found')
    
    error_lower = error_msg.lower().strip()
    
    # Empty error after SSH command often means timeout/connection issue
    if error_lower == '' or error_lower == '()':
        return ('connectivity', 'warning', 'SSH connection timeout - unable to verify mounts')
    
    # Check for connectivity indicators
    connectivity_indicators = [
        'ssh', 'connection', 'timeout', 'refused', 'closed',
        'no route', 'unreachable', 'offline', 'timed out',
        'cannot connect', 'connection reset', 'broken pipe'
    ]
    
    if any(indicator in error_lower for indicator in connectivity_indicators):
        return ('connectivity', 'warning', f'Connection issue: {error_msg[:100]}')
    
    # Check for mount-specific errors
    mount_indicators = [
        'mount point', 'not mounted', 'stale', 'permission denied',
        'no such file', 'device not', 'already mounted'
    ]
    
    if any(indicator in error_lower for indicator in mount_indicators):
        return ('mount_failure', 'critical', f'Mount error: {error_msg[:100]}')
    
    # Default to mount failure for unknown errors
    return ('mount_failure', 'critical', f'Mount verification failed: {error_msg[:100]}')

@trap
def is_host_online(hostname: str) -> bool:
    """
    Check if a host is reachable via ping.
    """
    global myconfig
    
    result = dorunrun(['ping', '-c', '2', '-W', '2', hostname], timeout=5)
    return result['code'] == 0

@trap
def get_mount_status(workstation: str) -> Tuple[bool, List[Dict], str]:
    """
    Get mount status from workstation using SSH 'mount -av' command.
    
    Returns:
        Tuple of (success, mount_list, error_message)
    """
    global myconfig

    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'mount -av']
    
    try:
        result = dorunrun(cmd, timeout=myconfig.ssh_timeout)
    except Exception as e:
        logger.error(f"{workstation}: SSH command failed: {str(e)}")
        return False, [], str(e)
    
    # Check result
    if result['code'] != 0:
        error_msg = result.get('stderr', '') or f"Exit code {result['code']}"
        logger.error(f"Failed to get mount status from {workstation}: {error_msg}")
        return False, [], error_msg
    
    # Parse successful output
    stdout = result.get('stdout', '')
    stderr = result.get('stderr', '')
    
    if stderr:
        logger.info(f"{workstation}: mount -av stderr: {stderr}")
    logger.debug(f"{workstation}: mount -av stdout lines: {len(stdout.splitlines())}")

    # Parse mount output
    mounts = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        
        # Look for mount status lines: "mount_point : status"
        if ' : ' in line:
            try:
                mount_point, status_msg = line.split(' : ', 1)
                mount_point = mount_point.strip()
                status_msg = status_msg.strip()
                
                # Determine mount status
                if 'already mounted' in status_msg.lower():
                    status = 'mounted'
                elif 'successfully mounted' in status_msg.lower():
                    status = 'newly_mounted'
                elif 'ignored' in status_msg.lower():
                    continue
                else:
                    status = 'unknown'
                
                # Try to extract device info
                device = ''
                if ' on ' in line:
                    device = line.split(' on ')[0].strip()
                
                mounts.append({
                    'device': device,
                    'mount_point': mount_point,
                    'status': status
                })
                
            except ValueError:
                logger.debug(f"Could not parse mount line: {line}")
                continue
    
    return True, mounts, ""

@trap
def check_mount_point_directories(workstation: str, expected_mounts: List[str]) -> Dict[str, str]:
    """
    Check if mount point directories exist on the workstation.
    """
    global myconfig
    results = {}
    
    if not expected_mounts:
        return results
    
    # Build command to check all mount points
    checks = ' && '.join([f'test -d "{mp}" && echo "{mp}:exists" || echo "{mp}:missing"' 
                          for mp in expected_mounts])
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, f'bash -c \'{checks}\'']
    
    try:
        result = dorunrun(cmd, timeout=myconfig.ssh_timeout)
        
        if result['code'] == 0:
            for line in result['stdout'].splitlines():
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
            accessible = result['stdout'].strip() == '1'
            results[software] = accessible
            
            # Log to database (using mount_point instead of software_path)
#            db.record_software_check(workstation, software, mount_point, accessible)
            
        except Exception as e:
            logger.error(f"Failed to check {software} on {workstation}: {e}")
            results[software] = False
#            db.record_software_check(workstation, software, mount_point, False)
    
    return results

@trap
def attempt_remount(workstation: str, mount_point: str = None) -> bool:
    """
    Attempt to remount filesystem(s) on workstation.
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
        
        if result['code'] == 0:
            logger.info(f"Successfully remounted on {workstation}")
            return True
        else:
            logger.error(f"Failed to remount on {workstation}: {result.get('stderr', '')}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to remount on {workstation}: {e}")
        return False

@trap
def count_active_users(workstation: str) -> Tuple[int, Optional[str]]:
    """
    Count number of active users on workstation.
    """
    global myconfig
    
    cmd = ['ssh'] + myconfig.ssh_options + [workstation, 'who | cut -d" " -f1 | sort -u']
    
    try:
        result = dorunrun(cmd, timeout=10)
        if result['code'] == 0 and result['stdout'].strip():
            users = result['stdout'].strip().split('\n')
            user_count = len(users)
            user_list = ','.join(users)
            return user_count, user_list
    except Exception as e:
        logger.debug(f"Could not count users on {workstation}: {e}")
    
    return 0, None

@trap
def monitor_workstation(workstation_config: Dict) -> Dict:
    """
    Monitor a single workstation's NAS mounts and verify software accessibility.
    
    Args:
        workstation_config: Dictionary with 'host' and 'mounts' keys
                           Example: {'host': 'adam', 'mounts': ['/usr/local/chem.sw']}
    
    Returns:
        Dictionary containing monitoring results
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
        'mounts': {},
        'software': {},
        'issues': [],
        'users': 0
    }
    
    logger.info(f"Checking workstation: {workstation}")
    mynetid = os.environ.get('USER', 'unknown')
    
    # Check if host is online
    if not is_host_online(workstation):
        report['online'] = False
        logger.warning(f"{workstation} is offline")
        db.update_workstation_status(workstation, is_online=False, active_users=0,
                                    user_list=None, checked_by=mynetid)
        return report
    
    report['online'] = True
    
    # Count active users if configured
    if myconfig.track_users:
        user_count, user_list = count_active_users(workstation)
        report['users'] = user_count
        if user_count > 0:
            logger.info(f"{workstation} has {user_count} active users: {user_list}")
    
    # Get mount status
    success, mount_list, error_msg = get_mount_status(workstation)
    
    if not success:
        # Classify the error
        issue_type, severity, description = classify_mount_issue(workstation, error_msg)
        
        logger.error(f"Failed to get mount status from {workstation}: {error_msg}")
        
        # Store the issue with classification
        report['issues'].append({
            'type': issue_type,
            'severity': severity,
            'description': description,
            'raw_error': error_msg
        })
        
        db.update_workstation_status(workstation, is_online=True, 
                                    active_users=report['users'],
                                    user_list=None, checked_by=mynetid)
        
        # Don't attempt fixes if it's just a connectivity issue
        if issue_type == 'connectivity':
            logger.info(f"Skipping mount attempts for {workstation} due to connectivity issue")
            return report
    else:
        # Process mount results
        mounted_points = {m['mount_point']: m for m in mount_list}
        
        for mount_point in expected_mounts:
            if mount_point in mounted_points:
                report['mounts'][mount_point] = 'mounted'
                db.record_mount_status(workstation, mount_point, 
                                     mounted_points[mount_point].get('device', ''),
                                     'nfs', 'mounted')
            else:
                # This is a real mount failure
                report['mounts'][mount_point] = 'not_mounted'
                report['issues'].append({
                    'type': 'mount_failure',
                    'severity': 'critical',
                    'mount_point': mount_point,
                    'description': f"Mount point {mount_point} is not mounted"
                })
                
                db.record_mount_status(workstation, mount_point, '', 'nfs', 'not_mounted')
                
                # Attempt to fix if configured and no users
                if myconfig.attempt_fix and report['users'] == 0:
                    logger.info(f"Attempting to fix mounts on {workstation}")
                    if attempt_remount(workstation):
                        # Re-check this specific mount
                        success2, mounts2, _ = get_mount_status(workstation)
                        if success2:
                            mounted2 = {m['mount_point']: m for m in mounts2}
                            if mount_point in mounted2:
                                report['mounts'][mount_point] = 'remounted'
                                db.record_mount_status(workstation, mount_point,
                                                     mounted2[mount_point].get('device', ''),
                                                     'nfs', 'newly_mounted',
                                                     action_taken='Auto-remounted')
                elif report['users'] > 0:
                    logger.info(f"Skipping auto-fix on {workstation} - users active")
    
    # Check critical software if mounts are OK
    for sw_config in myconfig.critical_software:
        mount_point = sw_config['mount']
        software_list = sw_config['software']
        
        # Only check if this mount is expected on this workstation
        if mount_point in expected_mounts:
            software_status = verify_software_access(
                workstation, mount_point, software_list
            )
            for software, accessible in software_status.items():
                report['software'][software] = accessible
                if not accessible:
                    report['issues'].append({
                        'type': 'software_missing',
                        'severity': 'warning',
                        'software': software,
                        'mount_point': mount_point,
                        'description': f"Software {software} not accessible on {mount_point}"
                    })
    
    # Update database
    db.update_workstation_status(
        workstation,
        is_online=True,
        active_users=report['users'],
        user_list=None,
        checked_by=mynetid
    )
    
    return report

@trap
def monitor_all_workstations(workstation_configs: List[Dict]) -> List[Dict]:
    """
    Monitor all configured workstations.
    """
    global db
    global logger
    
    results = []
    
    for ws_config in workstation_configs:
        result = monitor_workstation(ws_config)
        results.append(result)
    
    # Cleanup old records using database triggers
    mount_deleted, software_deleted, failures_deleted = db.cleanup_old_records()
    logger.info(f"Database cleanup: {mount_deleted} mount, {software_deleted} software, {failures_deleted} failure records removed")
    
    return results

@trap
def generate_summary_report(results: List[Dict]) -> str:
    """
    Generate a human-readable summary report.
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
            if issue.get('type') == 'mount_failure':
                mount_failures.append((workstation, issue))
            elif issue.get('type') == 'connectivity':
                connectivity_issues.append((workstation, issue))
            else:
                other_issues.append((workstation, issue))
    
    with_issues = len(set(w for w, _ in mount_failures + connectivity_issues + other_issues))
    
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
        f"  With Issues: {with_issues}",
        ""
    ]
    
    if mount_failures or connectivity_issues or other_issues:
        lines.append("WORKSTATIONS WITH ISSUES:")
        lines.append("-" * 70)
        
        # Group issues by workstation
        ws_issues = {}
        for ws, issue in mount_failures + connectivity_issues + other_issues:
            if ws not in ws_issues:
                ws_issues[ws] = []
            ws_issues[ws].append(issue)
        
        for workstation in sorted(ws_issues.keys()):
            lines.append(f"{workstation}:")
            
            # Show mount failures first (critical)
            mount_issues = [i for i in ws_issues[workstation] if i.get('type') == 'mount_failure']
            if mount_issues:
                for issue in mount_issues:
                    lines.append(f"  Mount Failure: {issue.get('description', issue.get('mount_point', 'Unknown'))}")
            
            # Show connectivity issues (warnings)
            conn_issues = [i for i in ws_issues[workstation] if i.get('type') == 'connectivity']
            if conn_issues:
                for issue in conn_issues:
                    lines.append(f"  Connectivity Issue: {issue.get('description', 'Connection failed')}")
            
            # Show other issues
            other = [i for i in ws_issues[workstation] if i.get('type') not in ['mount_failure', 'connectivity']]
            if other:
                for issue in other:
                    lines.append(f"  {issue.get('type', 'Issue')}: {issue.get('description', 'Unknown')}")
    else:
        lines.append("All workstations have healthy NAS mounts")
    
    lines.append("")
    lines.append("=" * 70)
    
    return "\n".join(lines)

@trap
def should_suppress_notification() -> bool:
    """
    Check if we're in off-hours or weekend suppression period.
    """
    global myconfig
    
    if not hasattr(myconfig, 'off_hours_start') or not hasattr(myconfig, 'off_hours_end'):
        return False  # If not configured, never suppress
    
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
        # Store for later
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
    Send summary of issues detected during off-hours with better classification.
    """
    global db
    global myconfig
    global logger
    
    issues = db.get_off_hours_issues()
    
    if not issues:
        logger.info("No off-hours issues to report")
        return
    
    # Group and classify issues
    by_workstation = {}
    mount_failure_count = 0
    connectivity_count = 0
    
    for issue_id, workstation, issue_type, details, detected_at in issues:
        if workstation not in by_workstation:
            by_workstation[workstation] = {'mount_failures': [], 'connectivity': [], 'other': []}
        
        # Try to classify based on the details
        if 'mount' in details.lower() and 'ssh' not in details.lower() and 'connection' not in details.lower():
            by_workstation[workstation]['mount_failures'].append({
                'details': details,
                'time': detected_at
            })
            mount_failure_count += 1
        elif 'ssh' in details.lower() or 'connection' in details.lower() or 'timeout' in details.lower():
            by_workstation[workstation]['connectivity'].append({
                'details': details,
                'time': detected_at
            })
            connectivity_count += 1
        else:
            by_workstation[workstation]['other'].append({
                'details': details,
                'time': detected_at
            })
    
    # Generate enhanced summary report
    report_lines = [
        "=" * 70,
        "NAS Workstation Monitor - Off-Hours Summary",
        f"Issues Detected: {datetime.datetime.now()}",
        f"Control Host: {socket.gethostname()}",
        "=" * 70,
        "",
        f"Total Workstations with Issues: {len(by_workstation)}",
        f"  Mount Failures: {mount_failure_count}",
        f"  Connectivity Issues: {connectivity_count}",
        ""
    ]
    
    for workstation in sorted(by_workstation.keys()):
        report_lines.append("-" * 70)
        report_lines.append(f"{workstation}:")
        
        ws_data = by_workstation[workstation]
        
        # Show mount failures first (critical)
        if ws_data['mount_failures']:
            report_lines.append("  Mount Failures:")
            first_time = ws_data['mount_failures'][0]['time']
            last_time = ws_data['mount_failures'][-1]['time']
            count = len(ws_data['mount_failures'])
            report_lines.append(f"    First: {first_time}")
            report_lines.append(f"    Last: {last_time}")
            report_lines.append(f"    Count: {count}")
        
        # Show connectivity issues separately
        if ws_data['connectivity']:
            report_lines.append("  Connectivity Issues (may not indicate mount problems):")
            first_time = ws_data['connectivity'][0]['time']
            last_time = ws_data['connectivity'][-1]['time']
            count = len(ws_data['connectivity'])
            report_lines.append(f"    First: {first_time}")
            report_lines.append(f"    Last: {last_time}")
            report_lines.append(f"    Count: {count}")
            report_lines.append(f"    Note: Mounts may be fine - connectivity prevented verification")
        
        # Show other issues
        if ws_data['other']:
            report_lines.append("  Other Issues:")
            for issue in ws_data['other']:
                report_lines.append(f"    {issue['time']}: {issue['details'][:80]}")
    
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
    
    # Load configuration (using 'rb' for tomli compatibility)
    with open(args.config, 'rb') as f:
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
            
            # Send notifications for critical issues (mount failures only)
            critical_issues = []
            for r in results:
                for issue in r.get('issues', []):
                    if issue.get('type') == 'mount_failure' and issue.get('severity') == 'critical':
                        critical_issues.append(r)
                        break
            
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
