# NAS Workstation Monitor - File Manifest

This document describes each file in the NAS Workstation Monitor project, its purpose, dependencies, and key features.

## Project Overview

**Purpose:** Automated monitoring and maintenance of NAS mounts across chemistry lab workstations with email notifications, auto-remediation, and user tracking.

**Repository:** https://github.com/jtonini/nas-workstation-monitor

**Pattern:** Database-driven monitoring following the dfstat architecture pattern

---

## Core Application Files

### nas_monitor.py
**Type:** Main monitoring daemon/script  
**Lines:** ~800  
**Dependencies:** 
- `nas_monitor_dbclass.py` (database operations)
- `nas_monitor.toml` (configuration)
- `dorunrun.py` (command execution)
- `urlogger.py` (logging)
- `urdecorators.py` (@trap decorator)
- `linuxutils.py` (system utilities)

**Purpose:**
- Main monitoring script that checks workstation mount status via SSH
- Detects mount failures including missing directories
- Attempts automatic remount on failures
- Tracks logged-in users (up to 3 usernames)
- Sends email notifications for issues
- Can run as daemon (continuous) or once (testing)

**Key Functions:**
- `monitor_workstation()` - Check single workstation via SSH
- `monitor_all_workstations()` - Check all configured workstations
- `get_mount_status()` - Parse `mount -av` output, detect failures from stderr
- `attempt_remount()` - Try to remount failed mounts
- `get_active_users()` - Get logged-in users via `who` command
- `verify_software_access()` - Check critical software availability
- `send_email_notification()` - Send alerts via system mail command
- `generate_report()` - Create human-readable status report

**Command-line Options:**
- `--once` - Run once and exit (for testing/cron)
- `--verbose` - Detailed output
- `--config FILE` - Specify config file
- `--nice N` - Set process priority

**Special Features:**
- Parses stderr from `mount -av` to detect "mount point does not exist" errors
- Detects multiple failure types: failed, directory_missing, not_mounted
- Attempts remount for individual failed mounts (not just all-or-nothing)
- Email notifications include offline workstations, mount failures, and software issues
- Uses subprocess.run for email to properly handle stdin

---

### nas_monitor_dbclass.py
**Type:** Database class  
**Lines:** ~350  
**Dependencies:**
- `sqlitedb.py` (base class)
- `nas_monitor_schema.sql` (schema definition)

**Purpose:**
- Database abstraction layer for NAS monitoring
- Inherits from SQLiteDB base class
- Provides specialized methods for mount status tracking

**Key Methods:**
- `add_mount_status()` - Log mount check results
- `add_software_check()` - Log software availability
- `update_workstation_status()` - Update workstation online/user status
- `get_current_status()` - Query current status view
- `get_unresolved_failures()` - Get active mount failures
- `get_workstation_reliability()` - Calculate success rates
- `get_workstation_detail()` - Get detailed history with user_list
- `cleanup_old_records()` - Trigger automatic data retention cleanup
- `get_config()` - Get runtime configuration
- `update_config()` - Update retention settings

**Database Schema Integration:**
- Loads schema from external .sql file on initialization
- Executes schema to create tables, views, triggers
- Schema is idempotent (can run multiple times safely)

---

### nas_monitor_schema.sql
**Type:** SQL schema definition  
**Lines:** ~230  
**Dependencies:** None (pure SQL)

**Purpose:**
- Complete database schema with tables, views, triggers, and indexes
- Implements automatic failure tracking and data retention
- Provides query views for common operations

**Tables:**
1. **monitor_config** - Runtime configuration (keep_hours, aggressive_cleanup)
2. **workstation_mount_status** - Every mount check (timestamp, status, users)
3. **workstation_status** - Current workstation state (online, users, user_list)
4. **mount_failures** - Unresolved failure tracking (first_failure, count, resolved)
5. **software_availability** - Software accessibility checks

**Views:**
1. **current_workstation_summary** - Latest status per workstation/mount (includes user_list)
2. **unresolved_failures** - Active mount failures with duration
3. **workstation_reliability** - 7-day success rate statistics
4. **software_summary** - Current software availability
5. **recent_failure_summary** - Last 24 hours of failures
6. **old_mount_checks** - Records older than keep_hours (for cleanup)
7. **old_software_checks** - Old software checks (for cleanup)

**Triggers:**
1. **cleanup_old_mount_checks** - Delete old mount records
2. **cleanup_old_software_checks** - Delete old software records
3. **auto_resolve_failures** - Mark failures resolved when mount succeeds
4. **track_mount_failures** - Auto-populate mount_failures table on any non-mounted status

**Key Features:**
- UNIQUE constraint on (workstation, mount_point, resolved) for proper ON CONFLICT handling
- Default retention: 168 hours (7 days)
- All times stored as UTC, displayed in local timezone
- Automatic failure tracking via triggers
- Auto-resolution when mounts succeed

---

### nas_query.py
**Type:** Query and reporting tool  
**Lines:** ~500  
**Dependencies:**
- `nas_monitor_dbclass.py` (database access)
- Optional: `pandas` for pretty display

**Purpose:**
- Command-line interface for querying monitoring data
- Provides various reports and health checks
- Database configuration and maintenance

**Commands:**
- `status` - Current status of all workstations (includes user_list)
- `failures` - Unresolved mount failures
- `recent` - Recent failures (last 24 hours)
- `reliability` - 7-day success rate per workstation
- `software` - Software availability report
- `detail --workstation NAME --hours N` - Detailed history (includes user_list)
- `config` - Show database configuration
- `update-config --keep-hours N [--aggressive]` - Update retention
- `cleanup [--confirm]` - Manual cleanup of old records
- `dbcheck [MODE]` - Database health diagnostics

**Display Options:**
- Uses pandas DataFrames if available for pretty output
- Falls back to fixed-width column formatting
- All timestamps displayed in local timezone (Eastern US)

**Database Diagnostics (dbcheck modes):**
- `config` - Show retention and cleanup settings
- `retention` - Show data age and span
- `records` - Show record counts by table
- `all` - Comprehensive health check (default)

---

### nas_monitor.toml
**Type:** Configuration file  
**Format:** TOML  
**Dependencies:** None

**Purpose:**
- Centralized configuration for all monitoring settings
- Easy to edit without touching code
- Sections for database, email, monitoring, workstations, software

**Configuration Sections:**

1. **Database and Logging:**
   ```toml
   database = '/home/zeus/nas_workstation_monitor.db'
   log_file = '/home/zeus/nas_workstation_monitor.log'
   schema_file = 'nas_monitor_schema.sql'
   ```

2. **Email Notifications:**
   ```toml
   notification_addresses = ['hpc@richmond.edu', 'admin@example.edu']
   notification_source = 'zeus@jonimitchell'
   send_notifications = true
   ```

3. **Monitoring Behavior:**
   ```toml
   time_interval = 3600  # Seconds between checks (hourly)
   attempt_fix = true    # Try to remount on failure
   track_users = true    # Capture logged-in users
   keep_hours = 168      # 7 days data retention
   ```

4. **SSH Configuration:**
   ```toml
   ssh_timeout = 30
   ssh_options = ['-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=no']
   ```

5. **Workstations to Monitor:**
   ```toml
   [[workstations]]
   host = 'adam'
   mounts = ['/usr/local/chem.sw']
   
   [[workstations]]
   host = 'sarah'
   mounts = ['/usr/local/chem.sw', '/opt/intel']
   ```

6. **Critical Software:**
   ```toml
   [[critical_software]]
   mount = '/usr/local/chem.sw'
   software = ['amber', 'Columbus', 'gaussian']
   ```

---

### nas_functions.sh
**Type:** Bash wrapper functions  
**Lines:** ~400  
**Dependencies:**
- `nas_monitor.py` (monitoring)
- `nas_query.py` (queries)

**Purpose:**
- Provide convenient bash functions for sysadmins
- Simpler interface than full Python commands
- Handles common queries with short commands

**Functions:**
- `nas_monitor` - Run monitoring once
- `nas_status` - Show current status
- `nas_failures` - Show unresolved failures
- `nas_recent` - Show recent failures (24h)
- `nas_reliability` - Show 7-day reliability stats
- `nas_software` - Show software availability
- `nas_detail WORKSTATION [HOURS]` - Show detailed history
- `nas_config` - Show database configuration
- `nas_dbcheck [MODE]` - Database health check
- `nas_help` - Show all available functions

**Usage:**
```bash
# Add to .bashrc
source ~/nas-workstation-monitor/nas_functions.sh

# Then use:
nas_status
nas_detail adam
nas_dbcheck all
```

---

## Utility Library Files

These are reusable utility modules adapted from the hpclib project.

### sqlitedb.py
**Type:** Base database class  
**Lines:** ~250  
**Dependencies:** Standard library only (sqlite3, os, sys)

**Purpose:**
- Generic SQLite database abstraction
- Thread-safe operations with proper locking
- Transaction management
- Schema loading support

**Key Features:**
- Context manager support (`with` statement)
- Automatic table creation
- Safe SQL execution with parameter binding
- Error handling and logging

**Methods:**
- `execute_SQL()` - Execute query with parameters
- `load_schema()` - Load schema from file
- `table_exists()` - Check if table exists
- Transaction management (commit, rollback)

---

### dorunrun.py
**Type:** Command execution utility  
**Lines:** ~150  
**Dependencies:** subprocess, shlex

**Purpose:**
- Safe subprocess execution wrapper
- Timeout support
- Captures stdout, stderr, exit code
- Handles command string or list format

**Returns:** Dictionary with:
```python
{
    'code': exit_code,
    'stdout': output_string,
    'stderr': error_string,
    'timeout': boolean
}
```

**Key Features:**
- Automatic timeout handling
- Proper shell escaping
- Error capture
- Used extensively for SSH commands

---

### urdecorators.py
**Type:** Python decorators  
**Lines:** ~180  
**Dependencies:** Standard library

**Purpose:**
- `@trap` decorator for comprehensive error handling
- Catches all exceptions
- Writes crash dumps with full context
- Creates dated dump directories

**@trap Decorator Features:**
- Captures function arguments and local variables
- Writes stack trace to file
- Creates dumps in `YYYY-MM-DD/pidNNNNN` format
- Allows program to continue after errors
- Used on all major functions

---

### urlogger.py
**Type:** Logging utility  
**Lines:** ~175  
**Dependencies:** Standard library logging

**Purpose:**
- Structured logging with consistent format
- File and console output
- Configurable log levels
- Thread-safe

**Log Format:**
```
#LEVEL    [YYYY-MM-DD HH:MM:SS,mmm] (PID module function: message)
```

**Example:**
```
#INFO     [2025-10-27 11:36:02,467] (44376 nas_monitor monitor_workstation: Checking workstation: adam)
#ERROR    [2025-10-27 11:36:03,588] (44376 nas_monitor send_email_notification: Failed to send email: ...)
```

---

### linuxutils.py
**Type:** Linux system utilities  
**Lines:** ~450  
**Dependencies:** Standard library

**Purpose:**
- Linux-specific utility functions
- Process management
- File operations
- Network utilities

**Key Functions:**
- `dump_cmdline()` - Display command-line arguments
- `get_hostname()` - Get system hostname
- `is_process_running()` - Check if process exists
- File locking utilities
- Various system checks

---

## Documentation Files

### README.md
**Type:** Markdown documentation  
**Lines:** ~450  

**Contents:**
- Project overview and features
- Quick start guide
- Installation instructions
- Usage examples (bash functions and CLI)
- Configuration guide with examples
- Output examples (status, detail views)
- Database schema documentation
- Architecture diagram
- Deployment checklist
- Troubleshooting section
- Support information

**Key Sections:**
- Features list with user tracking and diagnostics
- Bash helper functions documentation
- Database diagnostics documentation
- Output examples showing user_list
- Troubleshooting for common issues
- Database configuration problems

---

### LICENSE
**Type:** MIT License  
**Purpose:** Open source license

---

## File Dependencies Diagram

```
nas_monitor.py
├── nas_monitor_dbclass.py
│   ├── sqlitedb.py
│   └── nas_monitor_schema.sql
├── nas_monitor.toml
├── dorunrun.py
├── urlogger.py
├── urdecorators.py
└── linuxutils.py

nas_query.py
├── nas_monitor_dbclass.py
│   ├── sqlitedb.py
│   └── nas_monitor_schema.sql
└── (optional) pandas

nas_functions.sh
├── nas_monitor.py
└── nas_query.py
```

---

## Deployment Files

When deployed on a monitoring host (e.g., jonimitchell):

### Generated Files:
- `~/nas_workstation_monitor.db` - SQLite database (grows to ~50-100MB)
- `~/nas_workstation_monitor.log` - Application log file
- `~/nas-workstation-monitor/YYYY-MM-DD/pidNNNNN/` - Crash dumps (if errors occur)

### System Integration:
- **Cron job:** Runs `nas_monitor.py --once` hourly
- **Bash functions:** Sourced in `~/.bashrc` for sysadmin convenience
- **Postfix:** Required for email notifications

---

## File Modification History

**Key Updates During Development:**

1. **nas_monitor_schema.sql**
   - Added UNIQUE constraint on mount_failures table
   - Added track_mount_failures trigger
   - Updated current_workstation_summary view to include user_list
   - Changed default retention from 72 to 168 hours
   - Made schema idempotent (IF NOT EXISTS everywhere)

2. **nas_monitor.py**
   - Added stderr parsing for mount.nfs errors
   - Updated attempt_remount() to handle specific mount points
   - Fixed remount logic to handle individual mount failures
   - Changed email to use subprocess.run instead of smtplib
   - Fixed email recipients from comma-separated to space-separated
   - Added email notifications to --once mode
   - Added notification logic to include offline workstations
   - Removed SMTP imports (smtplib, email.mime.*)

3. **nas_monitor_dbclass.py**
   - Updated get_workstation_detail() to include user_list via JOIN
   - Fixed type hints to avoid pandas import errors

4. **nas_query.py**
   - Updated show_status() to display user_list column
   - Updated show_workstation_detail() to display user_list column
   - Fixed hpclib imports to use local modules

5. **nas_functions.sh**
   - Added nas_dbcheck function with multiple modes

---

## Testing Notes

**Manual Testing Performed:**
- Mount failure detection (unmounted, missing directory)
- Email notification system (postfix integration)
- User tracking and display
- Database triggers (failure tracking, auto-resolution)
- Automatic remount attempts
- Data retention and cleanup
- All query functions

**Test Workstation:** khanh
- Created artificial failure by renaming `/franksinatra/logP` directory
- Verified detection, remount attempts, email notifications
- Verified auto-resolution when fixed

---

## Production Deployment

**Current Status:**
- Deployed on: jonimitchell (monitoring host)
- Monitors: 17 chemistry lab workstations
- Schedule: Hourly via cron
- Email recipients: hpc@richmond.edu, gflanagin@richmond.edu, jtonini@richmond.edu
- Data retention: 7 days (168 hours)

**Cron Entry:**
```bash
0 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py >> /home/zeus/nas_workstation_monitor.log 2>&1
```

---

## Version Information

**Python Version:** 3.9+  
**SQLite Version:** 3.x  
**OS:** Rocky Linux 9 / RHEL-based systems

**Optional Dependencies:**
- pandas (for prettier query output)
- postfix/sendmail (for email notifications)

---
## Contact

For issues or questions:
- Email: hpc@richmond.edu
- GitHub: https://github.com/jtonini/nas-workstation-monitor

