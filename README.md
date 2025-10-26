# NAS Workstation Mount Monitor

Automated monitoring and maintenance of NAS mounts across chemistry lab workstations.

## Features

- **Automated Monitoring**: Hourly checks of all workstation NAS mounts
- **User Tracking**: Monitors and displays logged-in users (up to 3 usernames per workstation)
- **Auto-Remediation**: Automatic remounting attempts when issues detected
- **Database Tracking**: SQLite with views, triggers, and proper locking
- **Database Diagnostics**: Built-in health checks and configuration inspection
- **Software Verification**: Checks critical software accessibility (Amber, Columbus, Gaussian)
- **Email Notifications**: Alerts for persistent issues
- **Query Tools**: Rich command-line interface for status and analysis
- **Utility Libraries**: Uses local copies of utility modules (SQLiteDB, dorunrun, urlogger, etc.)

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/jtonini/nas-workstation-monitor.git
cd nas-workstation-monitor

# 2. Edit configuration
vi nas_monitor.toml
# Update: notification_addresses, workstations list, critical_software

# 3. Test with one workstation
python3 nas_monitor.py --once --verbose

# 4. Set up bash functions (recommended for sysadmins)
echo 'source ~/nas-workstation-monitor/nas_functions.sh' >> ~/.bashrc
source ~/.bashrc

# 5. Deploy to cron
crontab -e
# Add: 0 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py >> /home/zeus/nas_workstation_monitor.log 2>&1
```

## Usage

### Bash Helper Functions (Recommended)

These provide simple commands for sysadmins:

```bash
# Run monitor once
nas_monitor

# Check current status (now shows logged-in users)
nas_status

# Show failures
nas_failures

# Show reliability stats (7-day default)
nas_reliability

# Show detail for specific workstation (now includes user list)
nas_detail adam

# Show software availability
nas_software

# Database health check
nas_dbcheck

# Show recent failures (24 hours)
nas_recent

# Show configuration
nas_config

# Show all available functions
nas_help
```

### Database Diagnostics

The `nas_dbcheck` function provides quick database health checks:

```bash
# Quick health check (default)
nas_dbcheck

# Show configuration only
nas_dbcheck config

# Check data retention status
nas_dbcheck retention

# Show record counts by table
nas_dbcheck records

# Run all diagnostics
nas_dbcheck all
```

**Example Output:**
```
======================================================================
DATABASE HEALTH CHECK
======================================================================
Configuration:
  Retention: 168 hours (7.0 days)
  Cleanup: Auto
Record Counts:
  Mount records: 1248
  Workstation status: 17
  Software checks: 51
  Failures: 0
Data Age (Local Time):
  Oldest: 2025-10-19 15:30:00 (168.2 hours old)
  Newest: 2025-10-26 15:30:18 (0.1 hours old)
Database File:
  Size: 280K
  Modified: Oct 26 15:30
```

### Command Line Interface

All scripts have built-in `--help`:

```bash
# Monitor help
python3 nas_monitor.py --help

# Query help
python3 nas_query.py --help
```

#### Monitoring Commands

```bash
# Run once (no daemon mode)
python3 nas_monitor.py --once

# Run as daemon (continuous monitoring)
python3 nas_monitor.py

# Specify custom config
python3 nas_monitor.py --config /path/to/config.toml

# Verbose output
python3 nas_monitor.py --once --verbose

# Set process priority
python3 nas_monitor.py --nice 10
```

#### Query Commands

```bash
# Current status of all workstations
python3 nas_query.py status

# Show unresolved failures
python3 nas_query.py failures

# Show recent failures (24 hours)
python3 nas_query.py recent

# Show 7-day reliability statistics
python3 nas_query.py reliability

# Show software availability
python3 nas_query.py software

# Show detailed history for a workstation
python3 nas_query.py detail --workstation adam --hours 48

# Show database configuration
python3 nas_query.py config

# Update database configuration
python3 nas_query.py update-config --keep-hours 168 --aggressive

# Clean up old records (dry run)
python3 nas_query.py cleanup

# Clean up old records (actually delete)
python3 nas_query.py cleanup --confirm

# Database health check
nas_dbcheck
```

## Configuration

All settings are in `nas_monitor.toml`:

```toml
# Database and logging
database = '/home/zeus/nas_workstation_monitor.db'
log_file = '/home/zeus/nas_workstation_monitor.log'

# Email notifications
notification_addresses = ['hpc@richmond.edu']
notification_source = 'zeus@jonimitchell'

# Monitoring behavior
time_interval = 3600  # 1 hour
attempt_fix = true
send_notifications = true

# Data retention (7 days) - stored in database
keep_hours = 168

# Track active users on workstations
track_users = true

# Workstations to monitor
workstations = [
    {host = 'adam', mounts = ['/usr/local/chem.sw']},
    {host = 'sarah', mounts = ['/usr/local/chem.sw']},
    # ... add more workstations
]

# Critical software to verify
critical_software = [
    {mount = '/usr/local/chem.sw', software = ['amber', 'Columbus', 'gaussian']}
]
```

See `nas_monitor.toml` for all options.

## Output Examples

### Status Output (with users):
```
======================================================================
CURRENT WORKSTATION STATUS
======================================================================
Workstation     Mount                     Status     Online   Users  User List
----------------------------------------------------------------------------------
camryn          /usr/local/chem.sw        mounted    1        3      jburke3,kr7dh,ystarodubets
adam            /usr/local/chem.sw        mounted    1        1      kr7dh
aamy            /usr/local/chem.sw        mounted    1        0
```

### Detail Output (with users):
```
======================================================================
WORKSTATION DETAIL: camryn (Last 24 hours)
======================================================================
Timestamp            Mount Point               Status     Users  User List
----------------------------------------------------------------------------------
2025-10-26 19:21:10  /usr/local/chem.sw        mounted    3      jburke3,kr7dh,ystarodubets
2025-10-26 18:21:10  /usr/local/chem.sw        mounted    2      kr7dh,ystarodubets
```

## Database Schema

The monitor uses SQLite with:
- **Tables**: workstation_mount_status, workstation_status, mount_failures, software_availability, monitor_config
- **Views**: current_workstation_summary, unresolved_failures, workstation_reliability, software_summary, recent_failure_summary
- **Triggers**: Auto-cleanup of old data, auto-resolve failures
- **Config table**: Runtime configuration stored in database (keep_hours, cleanup_mode)

**New Features:**
- **User Tracking**: `workstation_status` table includes `active_users` (count) and `user_list` (up to 3 usernames)
- **Timestamps**: All times displayed in local timezone (Eastern US) while stored as UTC
- **Views Updated**: `current_workstation_summary` view includes user information

Schema is automatically loaded from `nas_monitor_schema.sql`.

## Architecture

Following the dfstat pattern:

```
nas_monitor.py              # Main monitoring script
├── nas_monitor_dbclass.py  # Database class
├── nas_monitor_schema.sql  # SQL schema with views/triggers
├── nas_monitor.toml        # TOML configuration
└── Utility modules:
    ├── sqlitedb.py         # Base SQLite class
    ├── dorunrun.py         # Command execution
    ├── urdecorators.py     # @trap decorator
    ├── urlogger.py         # Logging
    └── linuxutils.py       # Linux utilities
```

Query tool:
```
nas_query.py               # Query interface
├── nas_monitor_dbclass.py # Uses same DB class
└── nas_functions.sh       # Bash wrapper functions
```

## Files

**Core Scripts:**
- `nas_monitor.py` - Main monitoring daemon
- `nas_monitor_dbclass.py` - Database class (inherits from SQLiteDB)
- `nas_query.py` - Query and reporting tool

**Utility Modules:**
- `sqlitedb.py` - Base SQLite database class
- `dorunrun.py` - Safe command execution wrapper
- `urdecorators.py` - Exception handling decorators
- `urlogger.py` - Logging utilities
- `linuxutils.py` - Linux system utilities

**Database:**
- `nas_monitor_schema.sql` - Database schema with views and triggers

**Configuration:**
- `nas_monitor.toml` - Main configuration file
- `nas_functions.sh` - Bash helper functions

## Requirements

- Python 3.9+
- SSH access to all workstations with key-based authentication
- SQLite3 (command-line tool for manual queries)
- Standard Python libraries:
  - `tomli` or `tomllib` (for TOML config parsing)
  - All other dependencies are Python standard library

### Installing Python Dependencies

```bash
# For Python 3.9-3.10 (tomllib not in stdlib yet)
pip install tomli --break-system-packages

# Python 3.11+ has tomllib built-in (no install needed)
```

## Deployment

### Initial Setup

```bash
# 1. Clone to monitoring host (e.g., jonimitchell)
git clone https://github.com/jtonini/nas-workstation-monitor.git
cd nas-workstation-monitor

# 2. Configure SSH keys for passwordless access
ssh-keygen -t ed25519 -C "monitoring@jonimitchell"
for host in adam sarah cooper evan; do
    ssh-copy-id $host
done

# 3. Edit configuration
vi nas_monitor.toml
# Update workstations list, notification emails, paths

# 4. Test monitoring
python3 nas_monitor.py --once --verbose

# 5. Check database was created
ls -lh ~/nas_workstation_monitor.db

# 6. Verify user tracking is working
sqlite3 ~/nas_workstation_monitor.db "SELECT workstation, active_users, user_list FROM workstation_status WHERE active_users > 0;"
```

### Cron Setup

```bash
# Edit crontab
crontab -e

# Add hourly monitoring
0 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py >> /home/zeus/nas_workstation_monitor.log 2>&1

# Or every 15 minutes for more frequent checks
*/15 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py >> /home/zeus/nas_workstation_monitor.log 2>&1
```

### Bash Functions Setup

```bash
# Add to your .bashrc
echo 'source ~/nas-workstation-monitor/nas_functions.sh' >> ~/.bashrc
source ~/.bashrc

# Test the functions
nas_status
nas_reliability
nas_dbcheck
```

## Monitoring

The system will:
- Check all configured workstations every hour (or per cron schedule)
- Verify NAS mounts are accessible
- Track logged-in users (up to 3 usernames displayed per workstation)
- Check critical software packages are available
- Attempt automatic remount if issues detected
- Track all checks in SQLite database
- Keep 7 days (168 hours) of history by default
- Auto-cleanup old records to prevent database growth
- Send email alerts for persistent issues

## Troubleshooting

### Common Issues

**"No module named 'tomli'"**
```bash
# Python 3.9-3.10 needs tomli package
pip install tomli --break-system-packages

# Or use system package manager
sudo dnf install python3-tomli
```

**"Config file not found"**
```bash
# Specify full path
python3 nas_monitor.py --config /home/zeus/nas-workstation-monitor/nas_monitor.toml
```

**"Permission denied" on SSH**
```bash
# Verify SSH key access
ssh adam echo "test"

# If fails, copy SSH key
ssh-copy-id adam
```

**Database Shows No Records**
```bash
# Check if database was created
ls -lh ~/nas_workstation_monitor.db

# Run monitor once to populate
python3 nas_monitor.py --once --verbose

# Check record counts
sqlite3 ~/nas_workstation_monitor.db "SELECT COUNT(*) FROM workstation_mount_status;"
```

**Workstation Shows Offline But Is Online**
```bash
# Check if ICMP is blocked (ping fails but SSH works)
ping -c 1 workstation
ssh workstation echo "test"

# If ping blocked, allow ICMP from monitoring host on target workstation:
ssh workstation "sudo firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source address=<monitoring_host_IP> accept'"
ssh workstation "sudo firewall-cmd --reload"
```

### Database Configuration Issues

**Retention Period Not Matching Config File**
```bash
# Check current database setting
nas_config

# Update database to match TOML config (168 hours = 7 days)
sqlite3 ~/nas_workstation_monitor.db "UPDATE monitor_config SET keep_hours = 168 WHERE id = 1;"

# Verify the change
nas_dbcheck
```

**User Lists Not Showing**
```bash
# Check if user data is being captured
sqlite3 ~/nas_workstation_monitor.db "SELECT workstation, active_users, user_list FROM workstation_status WHERE active_users > 0;"

# If data exists but not showing in nas_status, recreate the view
sqlite3 ~/nas_workstation_monitor.db << 'SQL'
DROP VIEW IF EXISTS current_workstation_summary;
SQL

# Then re-run monitor to recreate from schema
python3 nas_monitor.py --once
```

### Logs

```bash
# View monitor log
tail -f /home/zeus/nas_workstation_monitor.log

# View cron log (if using separate log)
tail -f /home/zeus/nas_cron.log

# Check for errors
grep -i error /home/zeus/nas_workstation_monitor.log

# View recent monitoring runs
tail -100 /home/zeus/nas_workstation_monitor.log
```

### Database Queries

```bash
# Check database configuration
sqlite3 ~/nas_workstation_monitor.db "SELECT * FROM monitor_config;"

# View recent mount checks with user info
sqlite3 ~/nas_workstation_monitor.db "SELECT m.timestamp, m.workstation, m.mount_point, m.status, w.user_list FROM workstation_mount_status m LEFT JOIN workstation_status w ON m.workstation = w.workstation ORDER BY m.timestamp DESC LIMIT 20;"

# Check workstation reliability
sqlite3 ~/nas_workstation_monitor.db "SELECT * FROM workstation_reliability;"

# View all tables and views
sqlite3 ~/nas_workstation_monitor.db ".tables"

# Show which users are currently logged in
sqlite3 ~/nas_workstation_monitor.db "SELECT workstation, active_users, user_list FROM workstation_status WHERE active_users > 0;"
```

## Credits

- Utility modules adapted from [hpclib](https://github.com/georgeflanagin/hpclib) by George Flanagin
- University of Richmond HPC Team

## License

MIT License - See LICENSE file for details

## Support

For issues or questions:
- Email: hpc@richmond.edu
- Create an issue on GitHub: https://github.com/jtonini/nas-workstation-monitor/issues

