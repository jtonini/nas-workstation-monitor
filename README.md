# NAS Workstation Mount Monitor

Automated monitoring and maintenance of NAS mounts across chemistry lab workstations.

## Features

- **Automated Monitoring**: Hourly checks of all workstation NAS mounts
- **Auto-Remediation**: Automatic remounting attempts when issues detected
- **Database Tracking**: SQLite with views, triggers, and proper locking
- **Software Verification**: Checks critical software accessibility (Amber, Gaussian, etc.)
- **Email Notifications**: Alerts for persistent issues
- **Query Tools**: Rich command-line interface for status and analysis
- **HPC Integration**: Built on hpclib

## Quick Start

```bash
# 1. Clone repository with submodules
git clone --recurse-submodules https://github.com/jtonini/nas-workstation-monitor.git
cd nas-workstation-monitor

# If you already cloned without submodules:
git submodule init
git submodule update

# 2. Edit configuration
vi nas_monitor.toml
# Update: notification_addresses, workstations list

# 3. Test with one workstation
python3 nas_monitor.py --once --verbose

# 4. Set up bash functions (recommended for sysadmins)
echo 'source ~/nas-workstation-monitor/nas_functions.sh' >> ~/.bashrc
source ~/.bashrc

# 5. Deploy to cron
crontab -e
# Add: 0 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py
```

## Usage

### Bash Helper Functions (Recommended)

These provide simple commands for sysadmins:

```bash
# Run monitor once
nas_monitor

# Check current status
nas_status

# Show failures
nas_failures

# Show reliability stats
nas_reliability

# Show detail for specific workstation
nas_detail adam

# Show software availability
nas_query software
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

# Workstations to monitor
workstations = [
    {host = 'adam', mounts = ['/usr/local/chem.sw']},
    {host = 'sarah', mounts = ['/usr/local/chem.sw']},
    # ... add more workstations
]

# Critical software to verify
critical_software = [
    {mount = '/usr/local/chem.sw', software = ['amber', 'gaussian']}
]
```

See `nas_monitor.toml` for all options.

## Database Schema

The monitor uses SQLite with:
- **Tables**: workstation_mount_status, workstation_status, mount_failures, software_availability
- **Views**: current_workstation_summary, unresolved_failures, workstation_reliability, software_summary
- **Triggers**: Auto-cleanup of old data, auto-resolve failures
- **Config table**: Runtime configuration stored in database

Schema is automatically loaded from `nas_monitor_schema.sql`.

## Architecture

Following the dfstat pattern:

```
nas_monitor.py              # Main daemon (like dfstat.py)
├── nas_monitor_dbclass.py  # Database class (like dfdata.py)
├── nas_monitor_schema.sql  # SQL schema with views/triggers
├── nas_monitor.toml        # TOML configuration
└── hpclib/                 # Git submodule
    ├── sqlitedb.py         # Base SQLite class
    ├── dorunrun.py         # Command execution
    ├── urdecorators.py     # @trap decorator
    ├── urlogger.py         # Logging
    └── linuxutils.py       # Linux utilities
```

Query tool:
```
nas_query.py               # Query interface
└── nas_monitor_dbclass.py # Uses same DB class
```

## Files

**Core Scripts:**
- `nas_monitor.py` - Main monitoring daemon
- `nas_monitor_dbclass.py` - Database class
- `nas_query.py` - Query and reporting tool

**Database:**
- `nas_monitor_schema.sql` - Database schema with views/triggers

**Configuration:**
- `nas_monitor.toml` - Main configuration file
- `nas_functions.sh` - Bash helper functions

**HPC Library (git submodule):**
- `hpclib/` - Git submodule pointing to [hpclib](https://github.com/georgeflanagin/hpclib)
  - Automatically pulls latest versions
  - Run `git submodule update --remote` to update

## Requirements

- Python 3.8+
- SSH access to all workstations with key-based auth
- SQLite3
- Standard Python libraries (no pip installs required)

## Deployment

### Cron Setup

```bash
# Edit crontab
crontab -e

# Add hourly monitoring
0 * * * * cd /home/zeus/nas-workstation-monitor && python3 nas_monitor.py >> /home/zeus/nas_cron.log 2>&1
```

### Testing

```bash
# Test with single workstation
python3 nas_monitor.py --once --verbose

# Test without notifications
python3 nas_monitor.py --once --no-notifications

# Check database
python3 nas_query.py status
```

## Troubleshooting

### Common Issues

**"No module named 'tomli'"**
```bash
pip install tomli --break-system-packages
```

**"No module named 'hpclib' or 'sqlitedb'"**
```bash
# Initialize submodules if not already done
git submodule init
git submodule update

# Or if hpclib folder is empty
git submodule update --init --recursive
```

**"Config file not found"**
```bash
# Specify full path
python3 nas_monitor.py --config /home/zeus/nas-workstation-monitor/nas_monitor.toml
```

**"Permission denied" on SSH**
```bash
# Verify SSH key access
ssh adam 'mount -av'
```

### Updating hpclib

```bash
# Update to latest hpclib version
cd nas-workstation-monitor
git submodule update --remote hpclib
git add hpclib
git commit -m "Update hpclib submodule"
```

### Logs

```bash
# View monitor log
tail -f /home/zeus/nas_workstation_monitor.log

# View cron log
tail -f /home/zeus/nas_cron.log
```

## Development

This project follows the coding pattern from [dfstat](https://github.com/georgeflanagin/newdfstat):

- Global variables: `myconfig`, `logger`, `db`
- `@trap` decorator on all functions
- TOML configuration
- SQL schema in separate file
- Database class inherits from SQLiteDB
- URLogger for logging
- dorunrun for subprocess management

See `dfanalysis.py` in the dfstat repo for the reference pattern.

## Credits

- Pattern based on [newdfstat](https://github.com/georgeflanagin/newdfstat) by George Flanagin
- HPC library from [hpclib](https://github.com/georgeflanagin/hpclib) by George Flanagin
- University of Richmond HPC Team

## License

MIT License - See LICENSE file for details

## Support

For issues or questions:
- Email: hpc@richmond.edu
- Create an issue on GitHub
