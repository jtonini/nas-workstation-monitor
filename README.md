# NAS Workstation Mount Monitor

Automated monitoring and maintenance of NAS mounts across lab workstations.

## Overview

This system monitors NAS mounts on all lab workstations from a central server (jonimitchell). When students report "software is missing," this helps quickly identify if it's a mount issue.

**Key Features:**
- Hourly automated checks of all workstation mounts
- Automatic remounting attempts when issues detected
- SQLite database tracking of mount history
- Software accessibility verification
- Email notifications for persistent issues
- User activity awareness (won't disrupt active users)
- Full integration with hpclib tools (optional)

## Script Version

**nas_workstation_monitor.py**

Uses hpclib modules for production-ready HPC monitoring:
- `dorunrun` - Reliable subprocess management
- `sqlitedb` - Database with proper locking
- `urlogger` - Unified logging framework
- `linuxutils` - System utilities (whoami, process checking)
- `slurmutils` - SLURM job tracking
- `sloppytree` - Flexible data structures

**Automatic Fallback:** If hpclib is not installed, automatically uses standard Python libraries.

## Workstation vs. Compute Node Design

This system is designed for **workstations** (interactive user machines):

- **Lightweight monitoring** - doesn't impact user experience
- **User-aware** - tracks active users during checks
- **Interactive focus** - prioritizes quick resolution for productivity
- **Software verification** - ensures critical applications are accessible
- **Runs from central server** - no agents on workstations

## Architecture

```
jonimitchell (control server)
    └─ zeus user runs cron job hourly
        ├─ SSH to each workstation
        ├─ Check mount status (mount -av)
        ├─ Verify software accessibility
        ├─ Attempt fixes if needed
        └─ Log everything to database
```

## Prerequisites

### 1. Install hpclib (Recommended)

```bash
# Clone the repository
cd /usr/local/
sudo git clone https://github.com/georgeflanagin/hpclib.git

# Add to Python path
echo 'export PYTHONPATH="/usr/local/hpclib:$PYTHONPATH"' >> ~/.bashrc
source ~/.bashrc

# Verify installation
python3 -c "from dorunrun import dorunrun; print('✓ hpclib available')"
```

### 2. SSH Key Setup

```bash
# Ensure zeus@jonimitchell can SSH to all workstations without password
ssh-keygen -t ed25519  # If no key exists

# Copy key to all workstations
for host in aamy adam alexis boyi camryn cooper evan hamilton irene2 josh justin kevin khanh mayer michael sarah thais; do
    ssh-copy-id $host
done

# Test SSH access
for host in aamy adam alexis boyi camryn cooper evan hamilton irene2 josh justin kevin khanh mayer michael sarah thais; do
    echo "Testing $host..."
    ssh -o ConnectTimeout=5 $host "hostname"
done
```

### 3. Sudo Configuration

If zeus connects to the workstations as root, nothing needs to be done. If not, on each workstation, add to `/etc/sudoers.d/nas-monitor`:
```bash
zeus ALL=(ALL) NOPASSWD: /bin/mount, /usr/bin/mount
```

## Installation

```bash
# 1. Create installation directory
mkdir -p /home/zeus/nas-monitor
cd /home/zeus/nas-monitor

# 2. Copy script
cp nas_workstation_monitor.py .
chmod +x nas_workstation_monitor.py

# 3. Copy query tool
cp nas_workstation_query.py .
chmod +x nas_workstation_query.py

# 4. Configure email settings
vi nas_workstation_monitor.py
# Update: EMAIL_TO = "your-email@domain.com"
# Update: SMTP_SERVER = "your-smtp-server"

# 5. Configure critical software paths
vi nas_workstation_monitor.py
# Update the CRITICAL_SOFTWARE_PATHS dictionary with your actual paths

# 6. Test manual run (with just 2 workstations)
export my_computers="aamy adam"
./nas_workstation_monitor.py --fix

# 7. Add to crontab (runs hourly at minute 0)
crontab -e
# Add this line:
0 * * * * export my_computers="aamy adam alexis boyi camryn cooper evan hamilton irene2 josh justin kevin khanh mayer michael sarah thais"; /home/zeus/nas-monitor/nas_workstation_monitor.py --fix --notify --keep-hours 72
```

## Usage

### Manual Monitoring

```bash
# Monitor all workstations (check only)
./nas_workstation_monitor.py

# Monitor specific workstations
./nas_workstation_monitor.py --workstations adam sarah michael

# Monitor and attempt fixes
./nas_workstation_monitor.py --fix

# Monitor, fix, and send email if issues found
./nas_workstation_monitor.py --fix --notify

# Keep only last 24 hours
./nas_workstation_monitor.py --fix --keep-hours 24

# Aggressive cleanup: remove ALL old data including unresolved failures
./nas_workstation_monitor.py --fix --keep-hours 24 --aggressive-cleanup
```

### Querying History

```bash
# Show current status of all workstations
./nas_workstation_query.py status

# Show mount failures in last 24 hours
./nas_workstation_query.py failures

# Show software accessibility issues
./nas_workstation_query.py software

# Show reliability statistics (7-day)
./nas_workstation_query.py stats

# Show detailed history for a specific workstation
./nas_workstation_query.py detail adam

# Show database information
./nas_workstation_query.py dbinfo

# Preview cleanup (dry run) - STANDARD mode
./nas_workstation_query.py cleanup --keep-hours 72

# Preview cleanup (dry run) - AGGRESSIVE mode
./nas_workstation_query.py cleanup --keep-hours 72 --aggressive

# Perform cleanup - STANDARD mode
./nas_workstation_query.py cleanup --keep-hours 72 --confirm

# Perform cleanup - AGGRESSIVE mode
./nas_workstation_query.py cleanup --keep-hours 24 --aggressive --confirm
```

## Database Cleanup Modes

### STANDARD Mode (Default)
Keeps recent data plus current state and unresolved issues.

**Deletes:**
- Mount status records older than retention period
- Software availability checks older than retention period
- Mount failures that were **resolved** longer ago than retention period

**Keeps:**
- Current workstation status (always)
- **Unresolved** mount failures (always, no matter how old)
- Recent data within retention period

**Use when:** You want to track persistent problems over time.

### AGGRESSIVE Mode
Truly "no historical record" - only keeps recent data.

**Deletes:**
- Mount status records older than retention period
- Software availability checks older than retention period
- **ALL** mount failures older than retention period (resolved AND unresolved)
- Workstation status for workstations not seen within retention period

**Keeps:**
- Only data within retention period

**Use when:** You only care about current/recent status with no historical tracking.

### Configuration

```bash
# Standard mode (default) - keeps 3 days
./nas_workstation_monitor.py --fix --keep-hours 72

# Aggressive mode - keeps only 1 day
./nas_workstation_monitor.py --fix --keep-hours 24 --aggressive-cleanup

# Disable automatic cleanup
./nas_workstation_monitor.py --fix --keep-hours 0
```

## Database Schema

### workstation_mount_status
Records each mount check:
- timestamp, workstation, mount_point, device, filesystem
- status, response_time_ms, error_message, action_taken
- users_active, monitored_by, slurm_job_id

### workstation_status
Current state of each workstation:
- workstation, is_online, last_seen
- last_successful_check, consecutive_failures
- last_checked_by

### mount_failures
Tracks persistent mount issues:
- workstation, mount_point, failure_count
- first_failure, last_failure
- resolved, resolved_at, resolved_by

### software_availability
Software accessibility checks:
- workstation, software_name, mount_point
- is_accessible, check_time_ms

## Common Scenarios

### When a student reports "software is missing"

```bash
# 1. Check current status
./nas_workstation_query.py status

# 2. Check specific workstation history
./nas_workstation_query.py detail <workstation>

# 3. Check software issues
./nas_workstation_query.py software

# 4. Manually trigger check and fix
./nas_workstation_monitor_full_hpclib.py --workstations <workstation> --fix
```

### Reviewing weekly mount reliability

```bash
# View 7-day statistics
./nas_workstation_query.py stats

# Identify problematic workstations
./nas_workstation_query.py failures --hours 168
```

## Troubleshooting

### "Permission denied" when running mount -a remotely

Ensure sudo is configured on workstations:
```bash
# On each workstation
echo "zeus ALL=(ALL) NOPASSWD: /bin/mount, /usr/bin/mount" | sudo tee /etc/sudoers.d/nas-monitor
```

### SSH connections timing out

Check SSH configuration:
```bash
# Test connectivity
ping -c 3 adam

# Test SSH with verbose output
ssh -vvv adam hostname
```

### Database locked errors

Should not occur with hpclib's SQLiteDB, but if you see them:
```bash
# Check for multiple running instances
ps aux | grep nas_workstation_monitor
```

### hpclib not found

```bash
# Check Python path
echo $PYTHONPATH

# Verify hpclib location
ls /usr/local/src/hpclib/

# Test import
python3 -c "from dorunrun import dorunrun; print('OK')"
```

## Maintenance

### Log Cleanup
Logs older than 30 days are automatically cleaned up by the cron script.

### Manual Database Cleanup
```bash
# Check database size and stats
./nas_workstation_query.py dbinfo

# Preview cleanup
./nas_workstation_query.py cleanup --keep-hours 72

# Perform cleanup
./nas_workstation_query.py cleanup --keep-hours 72 --confirm
```

### Database Backup
```bash
# Backup database
cp /home/zeus/nas_workstation_monitor.db \
   /home/zeus/nas_workstation_monitor.db.backup-$(date +%Y%m%d)

# Restore from backup if needed
cp /home/zeus/nas_workstation_monitor.db.backup-20250101 \
   /home/zeus/nas_workstation_monitor.db
```

## File Locations

- Script: `/home/zeus/nas-monitor/nas_workstation_monitor_full_hpclib.py`
- Query tool: `/home/zeus/nas-monitor/nas_workstation_query.py`
- Database: `/home/zeus/nas_workstation_monitor.db`
- Logs: `/home/zeus/nas_workstation_monitor.log`

## Support

For issues or questions:
1. Check logs: `/home/zeus/nas_workstation_monitor.log`
2. Review database with query tool
3. Test SSH connectivity to affected workstation
4. Verify NAS server is accessible
5. Check workstation system logs: `ssh <workstation> "tail -50 /var/log/messages"`

## HPC Library Integration

The script uses these hpclib modules:
- **dorunrun**: Subprocess management with timeout and error handling
- **sqlitedb**: Database with proper locking for concurrent access
- **urlogger**: Unified logging framework
- **linuxutils**: System utilities (whoami, process checking)
- **slurmutils**: SLURM job ID tracking (if run via SLURM)
- **sloppytree**: Flexible data structures

If hpclib is not installed, the script automatically falls back to standard Python libraries.
