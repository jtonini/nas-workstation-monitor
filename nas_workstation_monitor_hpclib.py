#!/usr/bin/env python3
"""
NAS Workstation Mount Monitor - HPC Library Integration
Monitors and maintains NAS mounts across workstations using hpclib patterns
"""

import os
import sys
import sqlite3
import socket
import argparse
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from typing import List, Dict, Tuple, Optional
from enum import IntEnum

# Try to import hpclib modules if available
try:
    from dorunrun import dorunrun
    HPCLIB_AVAILABLE = True
except ImportError:
    HPCLIB_AVAILABLE = False
    import subprocess

# ExitCode enum (from hpclib pattern or fallback)
class ExitCode(IntEnum):
    """Standard Linux exit codes"""
    OK = 0
    GENERAL_ERROR = 1
    MISUSE_OF_SHELL = 2
    CANNOT_EXECUTE = 126
    COMMAND_NOT_FOUND = 127
    INVALID_EXIT_ARGUMENT = 128
    TERMINATED_BY_CTRL_C = 130
    OUT_OF_RANGE = 255

# Configuration
DB_PATH = "/home/zeus/nas_workstation_monitor.db"
LOG_FILE = "/home/zeus/nas_workstation_monitor.log"
EMAIL_FROM = "zeus@jonimitchell"
EMAIL_TO = "admin@yourdomain.com"  # Update this
SMTP_SERVER = "localhost"
SMTP_PORT = 25

# Workstation list from environment variable
WORKSTATIONS = os.getenv('my_computers', '').split()
if not WORKSTATIONS:
    WORKSTATIONS = ['aamy', 'adam', 'alexis', 'boyi', 'camryn', 'cooper', 
                    'evan', 'hamilton', 'irene2', 'josh', 'justin', 'kevin', 
                    'khanh', 'mayer', 'michael', 'sarah', 'thais']

# Critical software paths to verify
CRITICAL_SOFTWARE_PATHS = {
    '/usr/local/chem.sw': ['gaussian', 'orca', 'lumerical'],
    '/usr/local/phys.sw': ['matlab', 'mathematica'],
}

# SSH options for reliable connections
SSH_OPTIONS = [
    '-o', 'ConnectTimeout=10',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'BatchMode=yes',
    '-o', 'PasswordAuthentication=no'
]


def run_command(cmd: List[str], timeout: int = 30) -> Tuple[ExitCode, str, str]:
    """
    Run a command using hpclib's dorunrun if available, otherwise subprocess
    
    Args:
        cmd: Command and arguments as list
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    if HPCLIB_AVAILABLE:
        # Use hpclib's dorunrun pattern
        result = dorunrun(cmd, timeout=timeout, return_datatype=tuple)
        # dorunrun returns (exit_code, stdout, stderr)
        exit_code = ExitCode(result[0]) if result[0] in ExitCode.__members__.values() else ExitCode.GENERAL_ERROR
        return exit_code, result[1], result[2]
    else:
        # Fallback to subprocess
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            exit_code = ExitCode(result.returncode) if result.returncode in ExitCode.__members__.values() else ExitCode.GENERAL_ERROR
            return exit_code, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return ExitCode.GENERAL_ERROR, "", "Command timeout"
        except Exception as e:
            return ExitCode.GENERAL_ERROR, "", str(e)


class WorkstationMountMonitor:
    """Monitor NAS mounts on workstations using HPC patterns"""
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.control_host = socket.gethostname()
        self.init_database()
        
    def init_database(self):
        """Initialize SQLite database with workstation-specific tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Workstation mount status table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workstation_mount_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                workstation TEXT NOT NULL,
                mount_point TEXT NOT NULL,
                device TEXT,
                filesystem TEXT,
                status TEXT NOT NULL,
                response_time_ms FLOAT,
                error_message TEXT,
                action_taken TEXT,
                users_active INTEGER DEFAULT 0
            )
        ''')
        
        # Workstation status table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workstation_status (
                workstation TEXT PRIMARY KEY,
                is_online BOOLEAN DEFAULT 1,
                last_seen DATETIME,
                last_successful_check DATETIME,
                consecutive_failures INTEGER DEFAULT 0,
                notes TEXT
            )
        ''')
        
        # Mount failure tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mount_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workstation TEXT NOT NULL,
                mount_point TEXT NOT NULL,
                first_failure DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_failure DATETIME DEFAULT CURRENT_TIMESTAMP,
                failure_count INTEGER DEFAULT 1,
                resolved BOOLEAN DEFAULT 0,
                resolved_at DATETIME
            )
        ''')
        
        # Software availability tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS software_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                workstation TEXT NOT NULL,
                software_name TEXT NOT NULL,
                mount_point TEXT NOT NULL,
                is_accessible BOOLEAN,
                check_time_ms FLOAT
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def log_message(self, message: str, level: str = "INFO"):
        """Log message to file with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        
        with open(LOG_FILE, 'a') as f:
            f.write(log_entry)
        
        if level in ["ERROR", "CRITICAL"]:
            print(log_entry.strip(), file=sys.stderr)
        else:
            print(log_entry.strip())
    
    def check_workstation_online(self, workstation: str) -> bool:
        """Check if workstation is reachable"""
        cmd = ['ping', '-c', '1', '-W', '2', workstation]
        exit_code, stdout, stderr = run_command(cmd, timeout=5)
        return exit_code == ExitCode.OK
    
    def get_mount_status(self, workstation: str) -> Tuple[bool, List[Dict], str]:
        """
        Get mount status from workstation using mount -av
        Returns: (success, mount_list, error_message)
        """
        cmd = ['ssh'] + SSH_OPTIONS + [workstation, 'mount -av']
        exit_code, stdout, stderr = run_command(cmd, timeout=30)
        
        if exit_code != ExitCode.OK:
            return False, [], stderr
        
        # Parse mount output
        mounts = []
        for line in stdout.splitlines():
            if ':' in line or '/dev' in line:  # NFS or local mounts
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
    
    def verify_software_access(self, workstation: str, mount_point: str, 
                               software_list: List[str]) -> Dict[str, bool]:
        """Verify that critical software is accessible on the workstation"""
        results = {}
        
        for software in software_list:
            test_path = f"{mount_point}/{software}"
            cmd = ['ssh'] + SSH_OPTIONS + [workstation, 
                   f'test -e {test_path} && echo "OK" || echo "MISSING"']
            
            exit_code, stdout, stderr = run_command(cmd, timeout=10)
            results[software] = 'OK' in stdout
            
            # Log to database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO software_availability 
                (workstation, software_name, mount_point, is_accessible)
                VALUES (?, ?, ?, ?)
            ''', (workstation, software, mount_point, results[software]))
            conn.commit()
            conn.close()
        
        return results
    
    def attempt_remount(self, workstation: str) -> Tuple[bool, str]:
        """Attempt to remount all NAS directories on workstation"""
        cmd = ['ssh'] + SSH_OPTIONS + [workstation, 'sudo mount -a']
        exit_code, stdout, stderr = run_command(cmd, timeout=60)
        
        if exit_code == ExitCode.OK:
            return True, "Remount successful"
        else:
            return False, stderr
    
    def count_active_users(self, workstation: str) -> int:
        """Count active users on workstation"""
        cmd = ['ssh'] + SSH_OPTIONS + [workstation, 'who | wc -l']
        exit_code, stdout, stderr = run_command(cmd, timeout=10)
        
        if exit_code == ExitCode.OK:
            try:
                return int(stdout.strip())
            except:
                pass
        return 0
    
    def monitor_workstation(self, workstation: str, 
                           attempt_fix: bool = False) -> Dict:
        """Monitor a single workstation's NAS mounts"""
        self.log_message(f"Checking workstation: {workstation}")
        
        report = {
            'workstation': workstation,
            'timestamp': datetime.now().isoformat(),
            'online': False,
            'mounts_ok': False,
            'active_users': 0,
            'mount_details': [],
            'software_issues': [],
            'actions_taken': []
        }
        
        # Check if workstation is online
        if not self.check_workstation_online(workstation):
            self.log_message(f"{workstation} is offline", "WARNING")
            self.update_workstation_status(workstation, is_online=False)
            return report
        
        report['online'] = True
        report['active_users'] = self.count_active_users(workstation)
        
        # Get mount status
        success, mounts, error_msg = self.get_mount_status(workstation)
        
        if not success:
            self.log_message(
                f"Failed to get mount status from {workstation}: {error_msg}", 
                "ERROR"
            )
            report['error'] = error_msg
            
            if attempt_fix:
                self.log_message(f"Attempting to fix mounts on {workstation}")
                fix_success, fix_msg = self.attempt_remount(workstation)
                report['actions_taken'].append(f"Remount attempt: {fix_msg}")
                
                if fix_success:
                    # Re-check after fix
                    success, mounts, error_msg = self.get_mount_status(workstation)
                    report['mounts_ok'] = success
                    report['mount_details'] = mounts
        else:
            report['mounts_ok'] = True
            report['mount_details'] = mounts
        
        # Log to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for mount in mounts:
            cursor.execute('''
                INSERT INTO workstation_mount_status 
                (workstation, mount_point, device, status, users_active, action_taken)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (workstation, mount['mount_point'], mount['device'], 
                  mount['status'], report['active_users'],
                  ', '.join(report['actions_taken']) if report['actions_taken'] else None))
        
        conn.commit()
        conn.close()
        
        # Check critical software if mounts are OK
        if report['mounts_ok']:
            for mount_point, software_list in CRITICAL_SOFTWARE_PATHS.items():
                software_status = self.verify_software_access(
                    workstation, mount_point, software_list
                )
                
                for software, accessible in software_status.items():
                    if not accessible:
                        report['software_issues'].append({
                            'software': software,
                            'mount': mount_point
                        })
                        self.log_message(
                            f"Software not accessible on {workstation}: "
                            f"{software} at {mount_point}",
                            "WARNING"
                        )
        
        self.update_workstation_status(workstation, is_online=True, 
                                      success=report['mounts_ok'])
        
        return report
    
    def update_workstation_status(self, workstation: str, 
                                 is_online: bool, success: bool = True):
        """Update workstation status in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO workstation_status 
            (workstation, is_online, last_seen, last_successful_check, 
             consecutive_failures)
            VALUES (?, ?, datetime('now'), 
                    CASE WHEN ? THEN datetime('now') 
                         ELSE (SELECT last_successful_check FROM workstation_status 
                               WHERE workstation = ?) 
                    END,
                    CASE WHEN ? THEN 0 
                         ELSE (SELECT COALESCE(consecutive_failures, 0) + 1 
                               FROM workstation_status WHERE workstation = ?) 
                    END)
        ''', (workstation, is_online, success, workstation, success, workstation))
        
        conn.commit()
        conn.close()
    
    def cleanup_old_records(self, keep_hours: int = 72, aggressive: bool = False):
        """
        Clean up old records from database
        
        Args:
            keep_hours: Hours of history to retain
            aggressive: If True, also delete old unresolved failures and inactive workstation status
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff_time = datetime.now() - timedelta(hours=keep_hours)
        
        # Clean up old mount status records
        cursor.execute('''
            DELETE FROM workstation_mount_status
            WHERE timestamp < ?
        ''', (cutoff_time,))
        mount_deleted = cursor.rowcount
        
        # Clean up old software availability records
        cursor.execute('''
            DELETE FROM software_availability
            WHERE timestamp < ?
        ''', (cutoff_time,))
        software_deleted = cursor.rowcount
        
        if aggressive:
            # Also clean up ALL old mount failures
            cursor.execute('''
                DELETE FROM mount_failures
                WHERE last_failure < ?
            ''', (cutoff_time,))
            failures_deleted = cursor.rowcount
            
            # Remove workstation status for inactive workstations
            cursor.execute('''
                DELETE FROM workstation_status
                WHERE last_seen < ?
            ''', (cutoff_time,))
            workstation_deleted = cursor.rowcount
        else:
            # Only clean up resolved mount failures
            cursor.execute('''
                DELETE FROM mount_failures
                WHERE resolved = 1 AND resolved_at < ?
            ''', (cutoff_time,))
            failures_deleted = cursor.rowcount
            workstation_deleted = 0
        
        conn.commit()
        cursor.execute('VACUUM')
        conn.close()
        
        total_deleted = mount_deleted + software_deleted + failures_deleted + workstation_deleted
        if total_deleted > 0:
            mode = "aggressive" if aggressive else "standard"
            self.log_message(
                f"Database cleanup ({mode}): removed {mount_deleted} mount records, "
                f"{software_deleted} software records, {failures_deleted} failure records"
                + (f", {workstation_deleted} workstation status records" if aggressive else "")
                + f" (older than {keep_hours}h)"
            )
        
        return total_deleted
    
    def monitor_all_workstations(self, attempt_fix: bool = False, 
                                 parallel: bool = False,
                                 cleanup_hours: int = 72,
                                 aggressive_cleanup: bool = False) -> List[Dict]:
        """Monitor all workstations"""
        self.log_message(
            f"Starting monitoring of {len(WORKSTATIONS)} workstations"
        )
        
        results = []
        
        for workstation in WORKSTATIONS:
            result = self.monitor_workstation(workstation, attempt_fix)
            results.append(result)
        
        # Clean up old records after monitoring
        if cleanup_hours > 0:
            self.cleanup_old_records(cleanup_hours, aggressive_cleanup)
        
        return results
    
    def generate_report(self, results: List[Dict]) -> str:
        """Generate human-readable report"""
        report_lines = [
            "=" * 70,
            "NAS Workstation Mount Status Report",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Control Host: {self.control_host}",
            f"Using hpclib: {'Yes' if HPCLIB_AVAILABLE else 'No (fallback mode)'}",
            "=" * 70,
            ""
        ]
        
        total_workstations = len(results)
        online_workstations = sum(1 for r in results if r['online'])
        workstations_with_issues = sum(
            1 for r in results if not r['mounts_ok'] or r['software_issues']
        )
        
        report_lines.extend([
            "SUMMARY:",
            f"  Total Workstations: {total_workstations}",
            f"  Online: {online_workstations}",
            f"  Offline: {total_workstations - online_workstations}",
            f"  With Mount/Software Issues: {workstations_with_issues}",
            ""
        ])
        
        if workstations_with_issues > 0:
            report_lines.append("WORKSTATIONS WITH ISSUES:")
            report_lines.append("-" * 70)
            
            for result in results:
                if not result['mounts_ok'] or result['software_issues']:
                    report_lines.append(f"\n{result['workstation']}:")
                    report_lines.append(f"  Online: {result['online']}")
                    report_lines.append(f"  Active Users: {result['active_users']}")
                    report_lines.append(f"  Mounts OK: {result['mounts_ok']}")
                    
                    if result.get('error'):
                        report_lines.append(f"  Error: {result['error']}")
                    
                    if result['software_issues']:
                        report_lines.append("  Software Issues:")
                        for issue in result['software_issues']:
                            report_lines.append(
                                f"    - {issue['software']} not accessible "
                                f"at {issue['mount']}"
                            )
                    
                    if result['actions_taken']:
                        report_lines.append("  Actions Taken:")
                        for action in result['actions_taken']:
                            report_lines.append(f"    - {action}")
        else:
            report_lines.append("✓ All workstations have healthy NAS mounts")
        
        report_lines.append("\n" + "=" * 70)
        
        return "\n".join(report_lines)
    
    def send_email_notification(self, subject: str, body: str):
        """Send email notification"""
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_FROM
            msg['To'] = EMAIL_TO
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.send_message(msg)
            
            self.log_message(f"Email notification sent: {subject}")
        except Exception as e:
            self.log_message(f"Failed to send email: {e}", "ERROR")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor NAS mounts on workstations"
    )
    parser.add_argument(
        '--workstations',
        nargs='+',
        help='Specific workstations to monitor (default: all)'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Attempt to fix mount issues with mount -a'
    )
    parser.add_argument(
        '--notify',
        action='store_true',
        help='Send email notification if issues found'
    )
    parser.add_argument(
        '--db',
        default=DB_PATH,
        help='Database path'
    )
    parser.add_argument(
        '--keep-hours',
        type=int,
        default=72,
        help='Hours of history to keep in database (default: 72 = 3 days, 0 = disable cleanup)'
    )
    parser.add_argument(
        '--aggressive-cleanup',
        action='store_true',
        help='Also remove old unresolved failures and inactive workstation status entries'
    )
    
    args = parser.parse_args()
    
    monitor = WorkstationMountMonitor(args.db)
    
    # Set workstations to monitor
    if args.workstations:
        global WORKSTATIONS
        WORKSTATIONS = args.workstations
    
    # Monitor workstations
    results = monitor.monitor_all_workstations(
        attempt_fix=args.fix,
        cleanup_hours=args.keep_hours,
        aggressive_cleanup=args.aggressive_cleanup
    )
    
    # Generate report
    report = monitor.generate_report(results)
    print(report)
    
    # Send notification if requested and issues found
    if args.notify:
        workstations_with_issues = sum(
            1 for r in results 
            if not r['mounts_ok'] or r['software_issues']
        )
        
        if workstations_with_issues > 0:
            subject = f"NAS Mount Issues on {workstations_with_issues} Workstation(s)"
            monitor.send_email_notification(subject, report)


if __name__ == "__main__":
    main()
