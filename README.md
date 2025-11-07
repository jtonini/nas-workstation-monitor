# NAS Workstation Monitor

Automated monitoring system for NAS mount points across multiple workstations with intelligent alerting and comprehensive tracking.

## Features

### Core Monitoring
- **Hourly automated checks** of all workstation NAS mounts
- **17 workstations** monitored simultaneously
- **SSH-based remote monitoring** with 30-second timeout protection
- **Mount status tracking** for all NFS mount points
- **Software availability checks** (Gaussian, Maestro, Schrödinger)
- **User activity tracking** on each workstation
- **7-day data retention** with automatic cleanup

### Smart Alerting
- **Off-hours suppression** (6 PM - 6 AM): No email alerts during nights/weekends
- **Morning summary email** (6 AM): Single daily report of any off-hours issues
- **Immediate alerts** during business hours for critical failures
- **Email notifications** via Richmond's SMTP relay
- **Issue deduplication**: Won't spam you with repeat alerts

### Data Management
- **SQLite database** for all monitoring data
- **Automatic cleanup** of records older than 7 days
- **Timestamp indexes** for fast queries
- **Database export** to tab-delimited CSV/TSV format
- **VACUUM optimization** during cleanup

### Query Tools
- **Bash functions** for quick status checks
- **Command-line interface** for detailed queries
- **Real-time status** of all workstations
- **Reliability statistics** (7-day success rates)
- **Failure history** with duration tracking
- **Workstation detail** views

## Installation

### Prerequisites
- Python 3.9+
- SSH access to all monitored workstations
- SQLite3
- Git

### Setup on jonimitchell

```bash
# Clone repository
cd /home/zeus
git clone https://github.com/jtonini/nas-workstation-monitor.git
cd nas-workstation-monitor

# Initialize git submodule (hpclib)
git submodule init
git submodule update

# Configure monitoring
cp nas_monitor.toml.example nas_monitor.toml
vi nas_monitor.toml  # Edit configuration

# Initialize database
sqlite3 ~/nas_workstation_monitor.db < nas_monitor_schema.sql

# Load bash functions
source nas_functions.sh

# Add to your .bashrc for persistence
echo "source /home/zeus/nas-workstation-monitor/nas_functions.sh" >> ~/.bashrc
```

### Configure Cron

```bash
# Edit crontab
crontab -e

# Add hourly monitoring
0 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py --once >> /home/zeus/nas_workstation_monitor.log 2>&1

# Add 6 AM off-hours summary (optional - monitoring handles this automatically)
0 6 * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py --send-off-hours-summary >> /home/zeus/nas_workstation_monitor.log 2>&1
```

## Configuration

### nas_monitor.toml

Key settings:
- `database`: Path to SQLite database
- `log_file`: Monitoring log location
- `email.recipients`: Alert email addresses
- `off_hours`: Configure quiet hours (default: 18:00-06:00)
- `workstations`: List of workstations to monitor

## Usage

### Bash Functions (Quick Commands)

```bash
# Check current status of all workstations
nas_status

# View 7-day reliability statistics
nas_reliability

# Show unresolved failures + recent failure history
nas_failures

# Show recent failures (last 24 hours)
nas_recent

# Database health check
nas_dbcheck

# View detailed workstation history
nas_detail <workstation> [hours]

# Export database to TSV files
nas_db_export

# Show help
nas_help
```

### Command Line Interface

```bash
# Current status
python3 nas_query.py status

# Failures (unresolved + 7-day history with durations)
python3 nas_query.py failures

# Recent failures (24 hours)
python3 nas_query.py recent

# Reliability stats
python3 nas_query.py reliability

# Software availability
python3 nas_query.py software

# Workstation detail
python3 nas_query.py detail --workstation adam --hours 48

# Database configuration
python3 nas_query.py config

# Manual cleanup
python3 nas_query.py cleanup --confirm
```

### Manual Monitoring

```bash
# Run monitoring once (manual check)
python3 nas_monitor.py --once

# Run in daemon mode (not recommended - use cron instead)
python3 nas_monitor.py --daemon

# Send off-hours summary (usually automatic at 6 AM)
python3 nas_monitor.py --send-off-hours-summary
```

## Database Schema

### Tables

- **workstation_mount_status**: All mount check results with timestamps
- **workstation_status**: Online/offline status of workstations
- **software_availability**: Software accessibility checks
- **mount_failures**: Failure tracking with resolution status
- **off_hours_issues**: Issues detected during quiet hours (6 PM - 6 AM)
- **monitor_config**: System configuration (retention period, etc.)

### Views

- **current_workstation_summary**: Latest status of all mounts
- **workstation_reliability**: 7-day success rate statistics
- **software_summary**: Software availability summary
- **unresolved_failures**: Active unresolved mount failures
- **old_mount_checks**: Records eligible for cleanup (>7 days)
- **old_software_checks**: Software records eligible for cleanup
- **old_resolved_failures**: Resolved failures eligible for cleanup

## Email Alerts

### Alert Behavior

**Business Hours (6 AM - 6 PM):**
- Immediate email for workstation offline
- Immediate email for mount failures
- No emails for transient issues that resolve quickly

**Off Hours (6 PM - 6 AM):**
- Issues logged to `off_hours_issues` table
- No immediate emails sent
- Single summary email at 6 AM if any issues occurred

### Email Content
- Workstation name and mount point
- Issue type (offline, mount failed, etc.)
- Timestamp of detection
- User activity information

## Data Export

Export database to tab-delimited format for analysis in Excel, R, or Python:

```bash
nas_db_export
```

Creates timestamped directory with:
- **Raw tables**: workstation_mount_status.tsv, mount_failures.tsv, etc.
- **Summary views**: current_status_summary.tsv, reliability_summary.tsv
- **README.txt**: File descriptions and usage examples

### Using Exported Data

```r
# R
data <- read.delim("~/nas_monitor_export_*/workstation_mount_status.tsv")
```

```python
# Python/Pandas
import pandas as pd
df = pd.read_csv("~/nas_monitor_export_*/workstation_mount_status.tsv", sep="\t")
```

```excel
# Excel
File > Open > Select .tsv file > Import as tab-delimited
```

## Maintenance

### Database Cleanup

Automatic cleanup runs hourly during monitoring:
- Removes mount records older than 7 days
- Removes software checks older than 7 days  
- Removes resolved failures older than 7 days
- Keeps unresolved failures indefinitely
- Runs VACUUM to reclaim space

Manual cleanup:
```bash
nas_query cleanup --confirm
```

### Log Management

Monitor log location: `/home/zeus/nas_workstation_monitor.log`

```bash
# View recent activity
tail -100 /home/zeus/nas_workstation_monitor.log

# Monitor in real-time
tail -f /home/zeus/nas_workstation_monitor.log

# Rotate logs (if needed)
logrotate /etc/logrotate.d/nas_monitor
```

### Troubleshooting

**Monitoring not running:**
```bash
# Check cron
crontab -l

# Check for hung processes
ps aux | grep nas_monitor

# Check log for errors
tail -50 /home/zeus/nas_workstation_monitor.log
```

**Database locked:**
```bash
# Check for running processes
ps aux | grep nas_monitor

# Wait for monitoring to complete (takes ~30 seconds)
# Then retry query
```

**High database size:**
```bash
# Check database stats
nas_dbcheck

# Database will naturally shrink as old records age out
# Stabilizes at ~10-15MB for 7 days of data
```

## Architecture

### Monitoring Flow
1. Cron triggers `nas_monitor.py --once` every hour
2. Script checks all 17 workstations sequentially via SSH
3. Results stored in SQLite database
4. Cleanup removes records older than 7 days
5. Alerts sent based on time of day (business hours vs off-hours)
6. Off-hours issues logged for morning summary

### Database Updates
1. Every check inserts new records into `workstation_mount_status`
2. Triggers automatically update `mount_failures` table
3. Auto-resolve triggers mark failures as resolved when mounts return
4. Cleanup runs after monitoring completes
5. VACUUM reclaims disk space

### Alert Logic
- **Business hours**: Immediate email for critical issues
- **Off hours**: Log to `off_hours_issues`, suppress email
- **6 AM summary**: Query `off_hours_issues` for previous night
- **Deduplication**: Won't alert on same issue multiple times

## Development

### Repository Structure
```
nas-workstation-monitor/
├── nas_monitor.py              # Main monitoring script
├── nas_monitor_dbclass.py      # Database class
├── nas_query.py                # Query interface
├── nas_db_export.sh            # Database export script
├── nas_monitor_schema.sql      # Database schema
├── nas_monitor.toml            # Configuration
├── nas_functions.sh            # Bash convenience functions
├── nas_help.txt                # Help text
├── README.md                   # This file
└── hpclib/                     # Git submodule (utilities)
```

### Git Workflow
```bash
# On badenpowell (development)
cd /NAS_mount
# Make changes, test
git add .
git commit -m "Description of changes"
git push

# On jonimitchell (production)
cd /home/zeus/nas-workstation-monitor
git pull
# Changes deployed automatically
```

### Adding a Workstation

Edit `nas_monitor.toml`:
```toml
[[workstations]]
name = "new_workstation"
user = "zeus"
mounts = ["/usr/local/chem.sw", "/franksinatra/logP"]
software_mounts = ["/usr/local/chem.sw"]
```

No restart needed - next hourly run will include it.

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

### Failures Output (with duration):
```
======================================================================
UNRESOLVED MOUNT FAILURES
======================================================================
No unresolved failures found.

======================================================================
RECENT FAILURES (Last 7 Days)
======================================================================
Workstation  Mount Point              Failed At            Resolved At          Duration
----------------------------------------------------------------------------------------------------
khanh        /franksinatra/logP       2025-10-27 15:19:05  2025-10-27 16:00:16  41m 11s
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

### Database Health Check:
```
======================================================================
DATABASE HEALTH CHECK
======================================================================
Configuration:
  Retention: 168 hours (7.0 days)
  Cleanup: Auto
Record Counts:
  Mount records: 21672
  Workstation status: 17
  Software checks: 8564
  Failures: 0
Data Age (Local Time):
  Oldest: 2025-10-27 14:00:32 (167.5 hours old)
  Newest: 2025-11-03 14:00:22 (0.5 hours old)
Database File:
  Size: 12M
  Modified: Nov 3 14:00
```

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
0 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py --once >> /home/zeus/nas_workstation_monitor.log 2>&1
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
nas_db_export
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
- Send email alerts during business hours only
- Log off-hours issues for morning summary

## Credits

- **Author**: University of Richmond HPC Team
- **Maintainer**: jtonini@richmond.edu, hpc@richmond.edu
- **Utility modules**: Adapted from hpclib by George Flanagin
- **License**: MIT

## Support

For issues, questions, or feature requests:
- Email: hpc@richmond.edu
- GitHub: https://github.com/jtonini/nas-workstation-monitor

## Version History

- **v0.1** (2025-10-27): Initial release
  - Basic monitoring and alerting
  - Database tracking with SQLite
  - Email notifications
  - User activity tracking

- **v0.2** (2025-11-03): Smart alerting
  - Off-hours suppression (6 PM - 6 AM)
  - Morning summary emails (6 AM)
  - Improved email logic

- **v0.3** (2025-11-03): Enhanced failure tracking
  - Failure duration display (e.g., "2m 34s", "1h 15m")
  - 7-day failure history in `nas_failures`
  - Better visibility into mount problems

- **v0.4** (2025-11-05): Database export
  - New `nas_db_export` function
  - Tab-delimited TSV format
  - Compatible with Excel, R, Python
  - Timestamped export directories

- **v0.5** (2025-11-06): Performance and cleanup
  - Timestamp indexes for fast queries
  - Automatic cleanup of resolved failures (>7 days)
  - Direct DELETE queries (sub-second cleanup)
  - Complete documentation (README, help file)
  - Bug fixes (zombie processes, SQL queries, bash functions)
