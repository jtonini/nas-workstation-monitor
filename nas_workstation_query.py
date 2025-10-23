#!/usr/bin/env python3
"""
NAS Workstation Mount Query Tool
Query and analyze mount history from the monitoring database
"""

import sqlite3
import argparse
from datetime import datetime, timedelta
from typing import List, Dict
import sys

DB_PATH = "/home/zeus/nas_workstation_monitor.db"


class WorkstationMountQuery:
    """Query workstation mount monitoring data"""
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
    
    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def get_current_status(self) -> List[Dict]:
        """Get current status of all workstations"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                workstation,
                is_online,
                datetime(last_seen) as last_seen,
                datetime(last_successful_check) as last_successful_check,
                consecutive_failures,
                notes
            FROM workstation_status
            ORDER BY workstation
        ''')
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_workstation_history(self, workstation: str, hours: int = 24) -> List[Dict]:
        """Get mount history for a specific workstation"""
        cursor = self.conn.cursor()
        since = datetime.now() - timedelta(hours=hours)
        
        cursor.execute('''
            SELECT 
                datetime(timestamp) as timestamp,
                mount_point,
                device,
                status,
                response_time_ms,
                error_message,
                action_taken,
                users_active
            FROM workstation_mount_status
            WHERE workstation = ? AND timestamp >= ?
            ORDER BY timestamp DESC
        ''', (workstation, since))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_mount_point_failures(self, hours: int = 24) -> List[Dict]:
        """Get all mount failures in the last N hours"""
        cursor = self.conn.cursor()
        since = datetime.now() - timedelta(hours=hours)
        
        cursor.execute('''
            SELECT 
                workstation,
                mount_point,
                COUNT(*) as failure_count,
                GROUP_CONCAT(DISTINCT error_message, '; ') as errors,
                MAX(datetime(timestamp)) as last_failure
            FROM workstation_mount_status
            WHERE status != 'mounted' 
              AND status != 'newly_mounted'
              AND timestamp >= ?
            GROUP BY workstation, mount_point
            ORDER BY failure_count DESC
        ''', (since,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_software_issues(self, hours: int = 24) -> List[Dict]:
        """Get software accessibility issues"""
        cursor = self.conn.cursor()
        since = datetime.now() - timedelta(hours=hours)
        
        cursor.execute('''
            SELECT 
                workstation,
                software_name,
                mount_point,
                COUNT(*) as check_count,
                SUM(CASE WHEN is_accessible THEN 1 ELSE 0 END) as accessible_count,
                MAX(datetime(timestamp)) as last_checked
            FROM software_availability
            WHERE timestamp >= ?
            GROUP BY workstation, software_name, mount_point
            HAVING accessible_count < check_count
            ORDER BY workstation, software_name
        ''', (since,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_workstation_uptime_stats(self) -> List[Dict]:
        """Get uptime statistics for workstations"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            WITH recent_checks AS (
                SELECT 
                    workstation,
                    status,
                    timestamp
                FROM workstation_mount_status
                WHERE timestamp >= datetime('now', '-7 days')
            )
            SELECT 
                workstation,
                COUNT(*) as total_checks,
                SUM(CASE WHEN status IN ('mounted', 'newly_mounted') 
                    THEN 1 ELSE 0 END) as successful_checks,
                ROUND(100.0 * SUM(CASE WHEN status IN ('mounted', 'newly_mounted') 
                    THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
            FROM recent_checks
            GROUP BY workstation
            ORDER BY success_rate ASC, workstation
        ''')
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_persistent_failures(self) -> List[Dict]:
        """Get mounts with persistent failures"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT 
                workstation,
                mount_point,
                failure_count,
                datetime(first_failure) as first_failure,
                datetime(last_failure) as last_failure,
                resolved,
                datetime(resolved_at) as resolved_at
            FROM mount_failures
            WHERE resolved = 0
            ORDER BY failure_count DESC, last_failure DESC
        ''')
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_busy_workstations(self, hours: int = 24) -> List[Dict]:
        """Get workstations with most active users during checks"""
        cursor = self.conn.cursor()
        since = datetime.now() - timedelta(hours=hours)
        
        cursor.execute('''
            SELECT 
                workstation,
                ROUND(AVG(users_active), 1) as avg_users,
                MAX(users_active) as max_users,
                COUNT(*) as check_count
            FROM workstation_mount_status
            WHERE timestamp >= ? AND users_active > 0
            GROUP BY workstation
            ORDER BY avg_users DESC
        ''', (since,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_database_stats(self) -> Dict:
        """Get database statistics"""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # Count records in each table
        cursor.execute('SELECT COUNT(*) FROM workstation_mount_status')
        stats['mount_status_records'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM workstation_status')
        stats['workstation_records'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM mount_failures')
        stats['failure_records'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM software_availability')
        stats['software_records'] = cursor.fetchone()[0]
        
        # Get date range
        cursor.execute('SELECT MIN(timestamp), MAX(timestamp) FROM workstation_mount_status')
        oldest, newest = cursor.fetchone()
        stats['oldest_record'] = oldest
        stats['newest_record'] = newest
        
        # Get database file size
        import os
        if os.path.exists(self.db_path):
            stats['db_size_mb'] = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
        
        return stats
    
    def cleanup_old_records(self, keep_hours: int = 72, dry_run: bool = False, 
                          aggressive: bool = False) -> Dict:
        """
        Clean up old records from database
        
        Args:
            keep_hours: Number of hours of history to retain
            dry_run: If True, only report what would be deleted
            aggressive: If True, also delete old unresolved failures and inactive workstation status
            
        Returns:
            Dictionary with cleanup statistics
        """
        cursor = self.conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=keep_hours)
        
        stats = {
            'cutoff_time': cutoff_time.isoformat(),
            'keep_hours': keep_hours,
            'dry_run': dry_run,
            'aggressive': aggressive
        }
        
        # Count records to be deleted
        cursor.execute('''
            SELECT COUNT(*) FROM workstation_mount_status
            WHERE timestamp < ?
        ''', (cutoff_time,))
        stats['mount_status_to_delete'] = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(*) FROM software_availability
            WHERE timestamp < ?
        ''', (cutoff_time,))
        stats['software_to_delete'] = cursor.fetchone()[0]
        
        if aggressive:
            # Count ALL old failures
            cursor.execute('''
                SELECT COUNT(*) FROM mount_failures
                WHERE last_failure < ?
            ''', (cutoff_time,))
            stats['failures_to_delete'] = cursor.fetchone()[0]
            
            # Count inactive workstation status
            cursor.execute('''
                SELECT COUNT(*) FROM workstation_status
                WHERE last_seen < ?
            ''', (cutoff_time,))
            stats['workstation_status_to_delete'] = cursor.fetchone()[0]
        else:
            # Count only resolved failures
            cursor.execute('''
                SELECT COUNT(*) FROM mount_failures
                WHERE resolved = 1 AND resolved_at < ?
            ''', (cutoff_time,))
            stats['failures_to_delete'] = cursor.fetchone()[0]
            stats['workstation_status_to_delete'] = 0
        
        stats['total_to_delete'] = (stats['mount_status_to_delete'] + 
                                    stats['software_to_delete'] + 
                                    stats['failures_to_delete'] +
                                    stats['workstation_status_to_delete'])
        
        if not dry_run and stats['total_to_delete'] > 0:
            # Actually delete records
            cursor.execute('''
                DELETE FROM workstation_mount_status
                WHERE timestamp < ?
            ''', (cutoff_time,))
            
            cursor.execute('''
                DELETE FROM software_availability
                WHERE timestamp < ?
            ''', (cutoff_time,))
            
            if aggressive:
                cursor.execute('''
                    DELETE FROM mount_failures
                    WHERE last_failure < ?
                ''', (cutoff_time,))
                
                cursor.execute('''
                    DELETE FROM workstation_status
                    WHERE last_seen < ?
                ''', (cutoff_time,))
            else:
                cursor.execute('''
                    DELETE FROM mount_failures
                    WHERE resolved = 1 AND resolved_at < ?
                ''', (cutoff_time,))
            
            self.conn.commit()
            
            # Vacuum to reclaim space
            cursor.execute('VACUUM')
            
            stats['deleted'] = True
        else:
            stats['deleted'] = False
        
        return stats
    
    def print_current_status(self):
        """Print current workstation status"""
        statuses = self.get_current_status()
        
        print("=" * 80)
        print("CURRENT WORKSTATION STATUS")
        print("=" * 80)
        print(f"{'Workstation':<15} {'Online':<10} {'Last Seen':<20} {'Failures':<10}")
        print("-" * 80)
        
        for status in statuses:
            online_str = "✓ Yes" if status['is_online'] else "✗ No"
            failures = status['consecutive_failures'] or 0
            failure_str = f"{failures}" if failures > 0 else "-"
            
            print(f"{status['workstation']:<15} {online_str:<10} "
                  f"{status['last_seen']:<20} {failure_str:<10}")
        
        print("=" * 80)
    
    def print_failure_summary(self, hours: int = 24):
        """Print mount failure summary"""
        failures = self.get_mount_point_failures(hours)
        
        print(f"\nMOUNT FAILURES (Last {hours} hours)")
        print("=" * 80)
        
        if not failures:
            print("✓ No mount failures detected")
        else:
            print(f"{'Workstation':<15} {'Mount Point':<30} {'Failures':<10}")
            print("-" * 80)
            for failure in failures:
                print(f"{failure['workstation']:<15} "
                      f"{failure['mount_point']:<30} "
                      f"{failure['failure_count']:<10}")
        
        print("=" * 80)
    
    def print_software_issues(self, hours: int = 24):
        """Print software accessibility issues"""
        issues = self.get_software_issues(hours)
        
        print(f"\nSOFTWARE ACCESSIBILITY ISSUES (Last {hours} hours)")
        print("=" * 80)
        
        if not issues:
            print("✓ All software accessible")
        else:
            print(f"{'Workstation':<15} {'Software':<20} {'Mount':<30}")
            print("-" * 80)
            for issue in issues:
                print(f"{issue['workstation']:<15} "
                      f"{issue['software_name']:<20} "
                      f"{issue['mount_point']:<30}")
                print(f"  Accessible: {issue['accessible_count']}/{issue['check_count']} checks")
        
        print("=" * 80)
    
    def print_uptime_stats(self):
        """Print workstation uptime statistics"""
        stats = self.get_workstation_uptime_stats()
        
        print("\nWORKSTATION MOUNT RELIABILITY (Last 7 days)")
        print("=" * 80)
        print(f"{'Workstation':<15} {'Total Checks':<15} {'Successful':<15} {'Success Rate':<15}")
        print("-" * 80)
        
        for stat in stats:
            print(f"{stat['workstation']:<15} "
                  f"{stat['total_checks']:<15} "
                  f"{stat['successful_checks']:<15} "
                  f"{stat['success_rate']:.2f}%")
        
        print("=" * 80)
    
    def print_workstation_detail(self, workstation: str, hours: int = 24):
        """Print detailed history for a workstation"""
        history = self.get_workstation_history(workstation, hours)
        
        print(f"\nDETAILED HISTORY FOR: {workstation} (Last {hours} hours)")
        print("=" * 90)
        
        if not history:
            print(f"No mount checks found for {workstation} in the last {hours} hours")
        else:
            print(f"{'Time':<20} {'Mount Point':<30} {'Status':<15} {'Users':<8}")
            print("-" * 90)
            
            for entry in history:
                users = entry['users_active'] if entry['users_active'] else 0
                print(f"{entry['timestamp']:<20} "
                      f"{entry['mount_point']:<30} "
                      f"{entry['status']:<15} "
                      f"{users:<8}")
                
                if entry['error_message']:
                    print(f"  Error: {entry['error_message']}")
                if entry['action_taken']:
                    print(f"  Action: {entry['action_taken']}")
        
        print("=" * 90)
    
    def print_database_info(self):
        """Print database statistics and information"""
        stats = self.get_database_stats()
        
        print("\nDATABASE INFORMATION")
        print("=" * 80)
        print(f"Database file: {self.db_path}")
        print(f"Database size: {stats.get('db_size_mb', 'N/A')} MB")
        print(f"\nRecord counts:")
        print(f"  Mount status records:    {stats['mount_status_records']:,}")
        print(f"  Workstation records:     {stats['workstation_records']:,}")
        print(f"  Failure records:         {stats['failure_records']:,}")
        print(f"  Software check records:  {stats['software_records']:,}")
        
        if stats['oldest_record'] and stats['newest_record']:
            print(f"\nData range:")
            print(f"  Oldest record: {stats['oldest_record']}")
            print(f"  Newest record: {stats['newest_record']}")
        
        print("=" * 80)
    
    def print_cleanup_preview(self, keep_hours: int = 72, aggressive: bool = False):
        """Preview what would be cleaned up"""
        stats = self.cleanup_old_records(keep_hours, dry_run=True, aggressive=aggressive)
        
        mode = "AGGRESSIVE" if aggressive else "STANDARD"
        print(f"\nCLEANUP PREVIEW - {mode} MODE (keeping last {keep_hours} hours)")
        print("=" * 80)
        print(f"Cutoff time: {stats['cutoff_time']}")
        print(f"\nRecords that would be deleted:")
        print(f"  Mount status records:    {stats['mount_status_to_delete']:,}")
        print(f"  Software check records:  {stats['software_to_delete']:,}")
        
        if aggressive:
            print(f"  Mount failures (ALL):    {stats['failures_to_delete']:,}")
            print(f"  Workstation status:      {stats['workstation_status_to_delete']:,}")
        else:
            print(f"  Resolved failures only:  {stats['failures_to_delete']:,}")
        
        print(f"  {'─' * 40}")
        print(f"  Total:                   {stats['total_to_delete']:,}")
        
        if stats['total_to_delete'] == 0:
            print("\n✓ No records to delete")
        else:
            cmd = f"./nas_workstation_query.py cleanup --keep-hours {keep_hours} --confirm"
            if aggressive:
                cmd += " --aggressive"
            print(f"\nTo actually delete these records, run:")
            print(f"  {cmd}")
        
        if aggressive:
            print("\n⚠️  AGGRESSIVE MODE will delete:")
            print("  - All old mount check results")
            print("  - All old software availability checks")
            print("  - ALL old mount failures (even unresolved ones)")
            print("  - Workstation status for workstations not seen recently")
        
        print("=" * 80)
    
    def perform_cleanup(self, keep_hours: int = 72, aggressive: bool = False):
        """Actually perform the cleanup"""
        stats = self.cleanup_old_records(keep_hours, dry_run=False, aggressive=aggressive)
        
        mode = "AGGRESSIVE" if aggressive else "STANDARD"
        print(f"\nCLEANUP COMPLETED - {mode} MODE (kept last {keep_hours} hours)")
        print("=" * 80)
        print(f"Deleted records:")
        print(f"  Mount status records:    {stats['mount_status_to_delete']:,}")
        print(f"  Software check records:  {stats['software_to_delete']:,}")
        
        if aggressive:
            print(f"  Mount failures (ALL):    {stats['failures_to_delete']:,}")
            print(f"  Workstation status:      {stats['workstation_status_to_delete']:,}")
        else:
            print(f"  Resolved failures only:  {stats['failures_to_delete']:,}")
        
        print(f"  {'─' * 40}")
        print(f"  Total:                   {stats['total_to_delete']:,}")
        print("\n✓ Database vacuumed and optimized")
        print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Query NAS workstation mount monitoring database"
    )
    parser.add_argument(
        '--db',
        default=DB_PATH,
        help='Database path'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Query commands')
    
    # Status command
    subparsers.add_parser('status', help='Show current workstation status')
    
    # Failures command
    failures_parser = subparsers.add_parser('failures', help='Show mount failures')
    failures_parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Hours to look back (default: 24)'
    )
    
    # Software command
    software_parser = subparsers.add_parser('software', help='Show software issues')
    software_parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Hours to look back (default: 24)'
    )
    
    # Stats command
    subparsers.add_parser('stats', help='Show workstation reliability statistics')
    
    # Detail command
    detail_parser = subparsers.add_parser('detail', help='Show detailed history for a workstation')
    detail_parser.add_argument('workstation', help='Workstation name')
    detail_parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Hours to look back (default: 24)'
    )
    
    # All command
    all_parser = subparsers.add_parser('all', help='Show all reports')
    all_parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Hours to look back (default: 24)'
    )
    
    # Database info command
    subparsers.add_parser('dbinfo', help='Show database statistics and information')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old database records')
    cleanup_parser.add_argument(
        '--keep-hours',
        type=int,
        default=72,
        help='Hours of history to keep (default: 72 = 3 days)'
    )
    cleanup_parser.add_argument(
        '--confirm',
        action='store_true',
        help='Actually perform cleanup (without this, just shows preview)'
    )
    cleanup_parser.add_argument(
        '--aggressive',
        action='store_true',
        help='Also delete old unresolved failures and inactive workstation status'
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    query = WorkstationMountQuery(args.db)
    
    if args.command == 'status':
        query.print_current_status()
    
    elif args.command == 'failures':
        query.print_failure_summary(args.hours)
    
    elif args.command == 'software':
        query.print_software_issues(args.hours)
    
    elif args.command == 'stats':
        query.print_uptime_stats()
    
    elif args.command == 'detail':
        query.print_workstation_detail(args.workstation, args.hours)
    
    elif args.command == 'all':
        query.print_current_status()
        query.print_failure_summary(args.hours)
        query.print_software_issues(args.hours)
        query.print_uptime_stats()
    
    elif args.command == 'dbinfo':
        query.print_database_info()
    
    elif args.command == 'cleanup':
        if args.confirm:
            query.perform_cleanup(args.keep_hours, args.aggressive)
        else:
            query.print_cleanup_preview(args.keep_hours, args.aggressive)


if __name__ == "__main__":
    main()
