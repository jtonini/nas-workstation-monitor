#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database class for NAS Workstation Monitor
Inherits from SQLiteDB and provides NAS-specific methods
"""
import typing
from typing import *

###
# Standard imports, starting with os and sys
###
min_py = (3, 9)
import os
import sys
if sys.version_info < min_py:
    print(f"This program requires Python {min_py[0]}.{min_py[1]}, or higher.")
    sys.exit(os.EX_SOFTWARE)

###
# Other standard distro imports
###
import getpass
import logging
from datetime import datetime, timedelta

###
# Installed libraries
###
try:
    import pandas
    use_pandas = True
except:
    use_pandas = False

###
# From hpclib (local modules)
###
from sqlitedb import SQLiteDB
from urdecorators import show_exceptions_and_frames as trap
from urlogger import URLogger

###
# Global objects
###
mynetid = getpass.getuser()
logger = None  # Will be initialized by main script

###
# Credits
###
__author__ = 'University of Richmond HPC Team'
__copyright__ = 'Copyright 2025, University of Richmond'
__credits__ = None
__version__ = 0.1
__maintainer__ = 'University of Richmond HPC Team'
__email__ = ['hpc@richmond.edu', 'jtonini@richmond.edu']
__status__ = 'in progress'
__license__ = 'MIT'


class NASMonitorDB(SQLiteDB):
    """
    Database interface for NAS Workstation Monitor.
    
    This class inherits from SQLiteDB (hpclib) and provides NAS-specific
    methods for tracking mount status, failures, and software availability.
    
    Database Design:
        Tables:
        - workstation_mount_status: Historical mount check records
        - workstation_status: Current state of each workstation
        - mount_failures: Tracks unresolved mount issues
        - software_availability: Software accessibility checks
        - monitor_config: Runtime configuration (keep_hours, cleanup mode)
        
        Views (SQL-based):
        - current_workstation_summary: Latest status for all workstations
        - unresolved_failures: Mount issues needing attention
        - recent_failure_summary: 24-hour failure aggregation
        - workstation_reliability: 7-day success rate statistics
        - software_summary: 7-day software availability stats
        - recent_mount_checks/old_mount_checks: Time-windowed data access
        
        Triggers:
        - Auto-cleanup: DELETE on old_* views removes aged data
        - Auto-resolve: Successful mount check marks failures as resolved
    
    Usage Pattern (following dfstat/DFDB):
        db = NASMonitorDB('nas_monitor.db', 'nas_monitor_schema.sql')
        db.add_mount_status('adam', '/usr/local/chem.sw', 'device', 'mounted')
        reliability = db.get_reliability()  # Returns DataFrame or list
        db.cleanup_old_records()
        db.close()
    
    All SQL queries are defined as class constants (like DFDB pattern):
        NASMonitorDB.ADD_MOUNT_STATUS
        NASMonitorDB.GET_RELIABILITY
        etc.
    
    Inheritance:
        SQLiteDB provides:
        - Connection management with locking
        - Transaction handling
        - Pandas DataFrame support (if available)
        - execute_SQL() method with @trap error handling
    """

    ###
    # SQL statements as class constants
    ###
    
    ADD_MOUNT_STATUS = """INSERT INTO workstation_mount_status 
        (workstation, mount_point, device, status, users_active, 
         action_taken, monitored_by, slurm_job_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""

    ADD_SOFTWARE_CHECK = """INSERT INTO software_availability 
        (workstation, software_name, mount_point, is_accessible)
        VALUES (?, ?, ?, ?)"""

    UPDATE_WORKSTATION_STATUS = """
    INSERT INTO workstation_status 
        (workstation, is_online, last_seen, active_users, user_list, checked_by, slurm_job_id)
    VALUES (?, ?, datetime('now'), ?, ?, ?, ?)
    ON CONFLICT(workstation) DO UPDATE SET
        is_online = excluded.is_online,
        last_seen = excluded.last_seen,
        active_users = excluded.active_users,
        user_list = excluded.user_list,
        checked_by = excluded.checked_by,
        slurm_job_id = excluded.slurm_job_id
    WHERE workstation = excluded.workstation;
    """

    GET_CURRENT_STATUS = """SELECT * FROM current_workstation_summary 
        ORDER BY workstation"""

    GET_UNRESOLVED_FAILURES = """SELECT * FROM unresolved_failures"""

    GET_RECENT_FAILURES = """SELECT * FROM recent_failure_summary"""

    GET_RELIABILITY = """SELECT * FROM workstation_reliability"""

    GET_SOFTWARE_SUMMARY = """SELECT * FROM software_summary"""

    CLEANUP_OLD_MOUNTS = """DELETE FROM old_mount_checks"""

    CLEANUP_OLD_SOFTWARE = """DELETE FROM old_software_checks"""

    GET_CONFIG = """SELECT * FROM monitor_config WHERE id = 1"""

    UPDATE_CONFIG = """UPDATE monitor_config 
        SET keep_hours = ?, aggressive_cleanup = ? 
        WHERE id = 1"""


    def __init__(self, name: str, schema_file: str = None) -> None:
        """
        Initialize database and load schema if needed
        
        Args:
            name: Path to database file
            schema_file: Path to SQL schema file (optional)
        """
        super().__init__(name, use_pandas=use_pandas)
        
        if schema_file and os.path.exists(schema_file):
            self._load_schema(schema_file)


    @trap
    def _load_schema(self, schema_file: str) -> None:
        """Load database schema from SQL file"""
        with open(schema_file, 'r') as f:
            schema_sql = f.read()
        
        # Execute schema (may have multiple statements)
        self.cursor.executescript(schema_sql)
        self.commit()


    @trap
    def add_mount_status(self, workstation: str, mount_point: str, 
                        device: str, status: str, users_active: int = 0,
                        action_taken: str = None, monitored_by: str = None,
                        slurm_job_id: str = None) -> int:
        """
        Add a mount status record to the database.
        
        This is called for each mount point on each workstation during every
        monitoring cycle. Records accumulate to provide historical trends and
        enable reliability calculations via the workstation_reliability view.
        
        Args:
            workstation: Hostname (e.g., 'adam', 'sarah')
            mount_point: Mount target path (e.g., '/usr/local/chem.sw')
            device: Source device/NFS path (e.g., '141.166.186.35:/mnt/usrlocal/8')
            status: Mount status ('mounted', 'newly_mounted', 'failed')
            users_active: Number of logged-in users (default: 0)
            action_taken: Remediation action if any (e.g., 'Remount attempt: successful')
            monitored_by: Username running monitor (e.g., 'zeus')
            slurm_job_id: SLURM job ID if running on compute cluster
        
        Returns:
            Number of rows affected (should be 1 on success)
            
        Database:
            Inserts into workstation_mount_status table
            Timestamp is auto-generated (CURRENT_TIMESTAMP)
            
        Triggers:
            If status='mounted', auto_resolve_failures trigger marks any
            unresolved failures for this workstation/mount as resolved.
        """
        return self.execute_SQL(
            NASMonitorDB.ADD_MOUNT_STATUS,
            workstation, mount_point, device, status, users_active,
            action_taken, monitored_by, slurm_job_id
        )


    @trap
    def add_software_check(self, workstation: str, software: str,
                          mount_point: str, is_accessible: bool) -> int:
        """
        Add a software availability check record
        
        Returns:
            Number of rows affected
        """
        return self.execute_SQL(
            NASMonitorDB.ADD_SOFTWARE_CHECK,
            workstation, software, mount_point, int(is_accessible)
        )


    @trap
    def update_workstation_status(self, workstation: str, is_online: bool,
                                  success: bool = True, active_users: int = 0,
                                  user_list: str = None, checked_by: str = None) -> int:
        """
        Update workstation status
        
        Args:
            workstation: Hostname
            is_online: Whether workstation is online
            success: Whether mounts are successful
            active_users: Number of active users
            user_list: Comma-separated list of usernames (up to 3)
            checked_by: Username of checker
        
        Returns:
            Number of rows affected
        """
        return self.execute_SQL(
            NASMonitorDB.UPDATE_WORKSTATION_STATUS,
            workstation, int(is_online), active_users, user_list, checked_by,
            os.getenv('SLURM_JOB_ID')
        )


    @trap
    def get_current_status(self) -> List:
        """
        Get current status of all workstations
        
        Returns:
            List of tuples
        """
        return self.execute_SQL(NASMonitorDB.GET_CURRENT_STATUS)


    @trap
    def get_unresolved_failures(self) -> List:
        """
        Get all unresolved mount failures
        
        Returns:
            List of tuples
        """
        return self.execute_SQL(NASMonitorDB.GET_UNRESOLVED_FAILURES)


    @trap
    def get_recent_failures(self) -> List:
        """
        Get summary of recent failures (last 24 hours)
        
        Returns:
            List of tuples
        """
        return self.execute_SQL(NASMonitorDB.GET_RECENT_FAILURES)


    @trap
    def get_reliability(self) -> List:
        """
        Get 7-day reliability statistics for all workstations
        
        Returns:
            List of tuples
        """
        return self.execute_SQL(NASMonitorDB.GET_RELIABILITY)


    @trap
    def get_software_summary(self) -> List:
        """
        Get software availability summary (last 7 days)
        
        Returns:
            List of tuples
        """
        return self.execute_SQL(NASMonitorDB.GET_SOFTWARE_SUMMARY)


    @trap
    def cleanup_old_records(self) -> Tuple[int, int]:
        """
        Clean up old records using database triggers
        
        Returns:
            Tuple of (mount_records_deleted, software_records_deleted)
        """
        mount_deleted = self.execute_SQL(NASMonitorDB.CLEANUP_OLD_MOUNTS)
        software_deleted = self.execute_SQL(NASMonitorDB.CLEANUP_OLD_SOFTWARE)
        self.execute_SQL('VACUUM')
        return (mount_deleted, software_deleted)


    @trap
    def get_config(self) -> dict:
        """
        Get configuration from database
        
        Returns:
            Dictionary with config values (keys: keep_hours, aggressive_cleanup)
        """
        if use_pandas:
            df = self.execute_SQL(NASMonitorDB.GET_CONFIG)
            return dict(zip(df.columns.tolist(), df.iloc[0].tolist()))
        else:
            result = self.execute_SQL(NASMonitorDB.GET_CONFIG)
            if result:
                # Assuming columns: id, keep_hours, aggressive_cleanup
                return {
                    'keep_hours': result[0][1],
                    'aggressive_cleanup': result[0][2]
                }
            return {}


    @trap
    def update_config(self, keep_hours: int, aggressive_cleanup: bool = False) -> int:
        """
        Update configuration in database
        
        Args:
            keep_hours: Hours of history to keep
            aggressive_cleanup: Whether to use aggressive cleanup mode
            
        Returns:
            Number of rows affected
        """
        return self.execute_SQL(
            NASMonitorDB.UPDATE_CONFIG,
            keep_hours, int(aggressive_cleanup)
        )


    @trap
    def get_workstation_detail(self, workstation: str, hours: int = 24) -> List:
        """
        Get detailed history for a specific workstation
        
        Args:
            workstation: Workstation name
            hours: Hours of history to retrieve
            
        Returns:
            List of tuples including user_list from workstation_status
        """
        SQL = f"""
            SELECT 
                m.timestamp, 
                m.mount_point, 
                m.device, 
                m.status, 
                m.users_active, 
                w.user_list,
                m.action_taken
            FROM workstation_mount_status m
            LEFT JOIN workstation_status w ON m.workstation = w.workstation
            WHERE m.workstation = ?
              AND m.timestamp >= datetime('now', '-{hours} hours')
            ORDER BY m.timestamp DESC
        """
        return self.execute_SQL(SQL, workstation)


    @trap
    def get_mount_history(self, workstation: str, mount_point: str, hours: int = 168) -> List:
        """
        Get history for a specific mount on a workstation
        
        Args:
            workstation: Workstation name
            mount_point: Mount point path
            hours: Hours of history (default: 168 = 7 days)
            
        Returns:
            List of tuples
        """

    def log_off_hours_issue(self, workstation: str, issue_type: str, details: str) -> None:
        """Log an issue detected during off-hours for summary email"""
        SQL = """
            INSERT INTO off_hours_issues (workstation, issue_type, details, detected_at, notified)
            VALUES (?, ?, ?, datetime('now'), 0)
        """
        self.execute_SQL(SQL, (workstation, issue_type, details))
        self.commit()
    
    def get_off_hours_issues(self, unnotified_only: bool = True) -> List:
        """Get off-hours issues for summary email"""
        if unnotified_only:
            SQL = """
                SELECT id, workstation, issue_type, details, detected_at
                FROM off_hours_issues
                WHERE notified = 0
                ORDER BY detected_at DESC
            """
        else:
            SQL = """
                SELECT id, workstation, issue_type, details, detected_at, notified_at
                FROM off_hours_issues
                ORDER BY detected_at DESC
                LIMIT 100
            """
        return self.execute_SQL(SQL).fetchall()
    
    def mark_off_hours_issues_notified(self) -> int:
        """Mark all unnotified off-hours issues as notified"""
        SQL = """
            UPDATE off_hours_issues
            SET notified = 1, notified_at = datetime('now')
            WHERE notified = 0
        """
        cursor = self.execute_SQL(SQL)
        self.commit()
        return cursor.rowcount


        SQL = f"""
            SELECT timestamp, device, status, users_active
            FROM workstation_mount_status
            WHERE workstation = ?
              AND mount_point = ?
              AND timestamp >= datetime('now', '-{hours} hours')
            ORDER BY timestamp DESC
        """
        return self.execute_SQL(SQL, workstation, mount_point)


if __name__ == '__main__':
    # Test database operations
    db = NASMonitorDB('/tmp/test_nas.db', './nas_monitor_schema.sql')
    print(f"Database initialized: {db}")
    print(f"Using pandas: {use_pandas}")
    
    # Test adding data
    db.add_mount_status('adam', '/usr/local/chem.sw', '141.166.186.35:/mnt/usrlocal/8', 
                       'mounted', 2, None, mynetid, None)
    
    # Test queries
    print("\nCurrent status:")
    print(db.get_current_status())
    
    print("\nReliability:")
    print(db.get_reliability())
    
    db.close()
