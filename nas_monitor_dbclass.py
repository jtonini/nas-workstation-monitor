#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS Monitor Database Class - Enhanced Version 2.0
Database operations for NAS mount monitoring
Now includes connectivity issue tracking separate from mount failures
"""

import os
import sqlite3
import datetime
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
from contextlib import contextmanager

class NASMonitorDB:
    """
    Database interface for NAS mount monitoring with enhanced error tracking.
    
    Separates connectivity issues from mount failures for better diagnostics.
    """
    
    def __init__(self, db_path: str, schema_file: str = None):
        """
        Initialize database connection and ensure schema exists.
        
        Args:
            db_path: Path to SQLite database file
            schema_file: Optional path to schema SQL file
        """
        self.db_path = db_path
        self.schema_file = schema_file
        
        # Create database if it doesn't exist
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize database with enhanced schema including connectivity tracking."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if we need to apply schema
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            if not tables and self.schema_file and Path(self.schema_file).exists():
                # Apply schema from file
                with open(self.schema_file, 'r') as f:
                    schema_sql = f.read()
                conn.executescript(schema_sql)
            
            # Add connectivity tracking table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS connectivity_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    workstation TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    error_message TEXT,
                    resolved BOOLEAN DEFAULT 0,
                    resolved_at DATETIME,
                    duration_minutes REAL
                )
            ''')
            
            # Add index for connectivity issues
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_connectivity_workstation_time
                ON connectivity_issues(workstation, timestamp DESC)
            ''')
            
            # Add connectivity status to workstation_status if not exists
            cursor.execute("PRAGMA table_info(workstation_status)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'connectivity_status' not in columns:
                cursor.execute('''
                    ALTER TABLE workstation_status 
                    ADD COLUMN connectivity_status TEXT DEFAULT 'unknown'
                ''')
            
            if 'last_connectivity_issue' not in columns:
                cursor.execute('''
                    ALTER TABLE workstation_status 
                    ADD COLUMN last_connectivity_issue DATETIME
                ''')
            
            conn.commit()
    
    def record_mount_status(self, workstation: str, mount_point: str, 
                           device: str, filesystem: str, status: str,
                           response_time_ms: float = None,
                           error_message: str = None,
                           action_taken: str = None):
        """
        Record mount status check result.
        
        Args:
            workstation: Hostname
            mount_point: Mount point path
            device: Device/NFS source
            filesystem: Filesystem type
            status: Status (mounted, not_mounted, newly_mounted, etc.)
            response_time_ms: Optional response time
            error_message: Optional error message
            action_taken: Optional action taken
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO workstation_mount_status
                (workstation, mount_point, device, filesystem, status,
                 response_time_ms, error_message, action_taken, monitored_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (workstation, mount_point, device, filesystem, status,
                  response_time_ms, error_message, action_taken,
                  os.environ.get('USER', 'unknown')))
            
            conn.commit()
    
    def record_connectivity_issue(self, workstation: str, issue_type: str, 
                                 error_message: str = None):
        """
        Record a connectivity issue separate from mount failures.
        
        Args:
            workstation: Hostname
            issue_type: Type of issue (ssh_failed, host_unreachable, timeout, etc.)
            error_message: Detailed error message
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if there's an unresolved issue for this workstation
            cursor.execute('''
                SELECT id FROM connectivity_issues 
                WHERE workstation = ? AND resolved = 0
                ORDER BY timestamp DESC LIMIT 1
            ''', (workstation,))
            
            existing = cursor.fetchone()
            
            if not existing:
                # Create new issue record
                cursor.execute('''
                    INSERT INTO connectivity_issues
                    (workstation, issue_type, error_message)
                    VALUES (?, ?, ?)
                ''', (workstation, issue_type, error_message))
            else:
                # Update existing issue
                cursor.execute('''
                    UPDATE connectivity_issues
                    SET timestamp = CURRENT_TIMESTAMP,
                        issue_type = ?,
                        error_message = ?
                    WHERE id = ?
                ''', (issue_type, error_message, existing[0]))
            
            # Update workstation status
            cursor.execute('''
                UPDATE workstation_status
                SET connectivity_status = ?,
                    last_connectivity_issue = CURRENT_TIMESTAMP
                WHERE workstation = ?
            ''', (issue_type, workstation))
            
            conn.commit()
    
    def resolve_connectivity_issues(self, workstation: str):
        """
        Mark connectivity issues as resolved for a workstation.
        
        Args:
            workstation: Hostname
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Calculate duration and mark resolved
            cursor.execute('''
                UPDATE connectivity_issues
                SET resolved = 1,
                    resolved_at = CURRENT_TIMESTAMP,
                    duration_minutes = (julianday(CURRENT_TIMESTAMP) - julianday(timestamp)) * 24 * 60
                WHERE workstation = ? AND resolved = 0
            ''', (workstation,))
            
            # Update workstation status
            cursor.execute('''
                UPDATE workstation_status
                SET connectivity_status = 'connected'
                WHERE workstation = ?
            ''', (workstation,))
            
            conn.commit()
    
    def update_workstation_status(self, workstation: str, is_online: bool,
                                 connectivity: str = None,
                                 active_users: int = 0,
                                 user_list: str = None,
                                 mount_status: str = None,
                                 checked_by: str = None):
        """
        Update or insert workstation status with connectivity info.
        
        Args:
            workstation: Hostname
            is_online: Whether workstation is reachable
            connectivity: Connectivity status (connected, ssh_failed, unreachable)
            active_users: Number of active users
            user_list: Comma-separated list of users
            mount_status: Overall mount status
            checked_by: User running the check
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO workstation_status
                (workstation, is_online, connectivity_status, last_check, 
                 active_users, user_list, mount_status, checked_by)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
            ''', (workstation, is_online, connectivity or 'unknown',
                  active_users, user_list, mount_status, checked_by))
            
            conn.commit()
    
    def record_software_check(self, workstation: str, software_name: str,
                            mount_point: str, is_accessible: bool,
                            error_message: str = None):
        """
        Record software accessibility check.
        
        Args:
            workstation: Hostname
            software_name: Name of software
            mount_point: Full path to software
            is_accessible: Whether software is accessible
            error_message: Optional error message
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get check time
            start_time = datetime.datetime.now()
            
            cursor.execute('''
                INSERT INTO software_availability
                (workstation, software_name, mount_point, is_accessible,
                 check_time_ms, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (workstation, software_name, mount_point, is_accessible,
                  0, error_message))
            
            conn.commit()
    
    def store_off_hours_issue(self, issue_details: str):
        """
        Store issues detected during off-hours for later notification.
        
        Args:
            issue_details: Description of the issue
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Parse issue details to extract workstation and type
            workstation = 'unknown'
            issue_type = 'general'
            
            # Simple parsing - you might want to enhance this
            if ':' in issue_details:
                parts = issue_details.split(':', 1)
                workstation = parts[0].strip()
                
                if 'mount' in issue_details.lower():
                    issue_type = 'mount_failure'
                elif 'ssh' in issue_details.lower() or 'connect' in issue_details.lower():
                    issue_type = 'connectivity'
            
            cursor.execute('''
                INSERT INTO off_hours_issues
                (workstation, issue_type, details)
                VALUES (?, ?, ?)
            ''', (workstation, issue_type, issue_details))
            
            conn.commit()
    
    def get_off_hours_issues(self) -> List[Tuple]:
        """
        Get all unnotified off-hours issues.
        
        Returns:
            List of (id, workstation, issue_type, details, detected_at) tuples
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, workstation, issue_type, details, detected_at
                FROM off_hours_issues
                WHERE notified = 0
                ORDER BY detected_at
            ''')
            
            return cursor.fetchall()
    
    def clear_off_hours_issues(self):
        """Mark all off-hours issues as notified."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE off_hours_issues
                SET notified = 1
                WHERE notified = 0
            ''')
            
            conn.commit()
    
    def cleanup_old_records(self, keep_hours: int = None) -> Tuple[int, int, int]:
        """
        Clean up old records from the database.
        
        Args:
            keep_hours: Hours of history to keep (from config if not specified)
            
        Returns:
            Tuple of (mount_records_deleted, software_records_deleted, failure_records_deleted)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get keep_hours from config if not specified
            if keep_hours is None:
                cursor.execute('SELECT keep_hours FROM monitor_config WHERE id = 1')
                result = cursor.fetchone()
                keep_hours = result[0] if result else 168  # Default to 7 days
            
            cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=keep_hours)
            
            # Delete old mount status records
            cursor.execute('''
                DELETE FROM workstation_mount_status
                WHERE timestamp < ?
            ''', (cutoff_time,))
            mount_deleted = cursor.rowcount
            
            # Delete old software checks
            cursor.execute('''
                DELETE FROM software_availability
                WHERE timestamp < ?
            ''', (cutoff_time,))
            software_deleted = cursor.rowcount
            
            # Delete old resolved connectivity issues
            cursor.execute('''
                DELETE FROM connectivity_issues
                WHERE resolved = 1 AND resolved_at < ?
            ''', (cutoff_time,))
            conn_deleted = cursor.rowcount
            
            # Delete old resolved mount failures
            cursor.execute('''
                DELETE FROM mount_failures
                WHERE resolved = 1 AND resolved_at < ?
            ''', (cutoff_time,))
            failures_deleted = cursor.rowcount
            
            conn.commit()
            
            return mount_deleted, software_deleted, failures_deleted + conn_deleted
    
    def get_recent_connectivity_issues(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get recent connectivity issues for reporting.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of connectivity issue dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            since_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
            
            cursor.execute('''
                SELECT workstation, issue_type, error_message, timestamp,
                       resolved, resolved_at, duration_minutes
                FROM connectivity_issues
                WHERE timestamp > ?
                ORDER BY timestamp DESC
            ''', (since_time,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'workstation': row['workstation'],
                    'issue_type': row['issue_type'],
                    'error_message': row['error_message'],
                    'timestamp': row['timestamp'],
                    'resolved': bool(row['resolved']),
                    'resolved_at': row['resolved_at'],
                    'duration_minutes': row['duration_minutes']
                })
            
            return results
