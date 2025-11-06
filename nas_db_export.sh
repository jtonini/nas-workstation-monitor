#!/usr/bin/env bash
# Export NAS monitoring database to tab-delimited CSV files

DB_PATH="${HOME}/nas_workstation_monitor.db"
EXPORT_DIR="${HOME}/nas_monitor_export_$(date +%Y%m%d_%H%M%S)"

# Create export directory
mkdir -p "$EXPORT_DIR"

echo "Exporting NAS monitoring database to: $EXPORT_DIR"

# Export main tables
sqlite3 "$DB_PATH" <<SQL
.mode tabs
.headers on
.output ${EXPORT_DIR}/workstation_mount_status.tsv
SELECT * FROM workstation_mount_status ORDER BY timestamp DESC;
.output ${EXPORT_DIR}/workstation_status.tsv
SELECT * FROM workstation_status ORDER BY last_check DESC;
.output ${EXPORT_DIR}/software_availability.tsv
SELECT * FROM software_availability ORDER BY timestamp DESC;
.output ${EXPORT_DIR}/mount_failures.tsv
SELECT * FROM mount_failures ORDER BY first_failure DESC;
.output ${EXPORT_DIR}/off_hours_issues.tsv
SELECT * FROM off_hours_issues ORDER BY detected_at DESC;
.output ${EXPORT_DIR}/monitor_config.tsv
SELECT * FROM monitor_config;
SQL

# Export summary views
sqlite3 "$DB_PATH" <<SQL
.mode tabs
.headers on
.output ${EXPORT_DIR}/current_status_summary.tsv
SELECT * FROM current_workstation_summary;
.output ${EXPORT_DIR}/reliability_summary.tsv
SELECT * FROM workstation_reliability;
.output ${EXPORT_DIR}/software_summary.tsv
SELECT * FROM software_summary;
.output ${EXPORT_DIR}/unresolved_failures.tsv
SELECT * FROM unresolved_failures;
SQL

# Create README
cat > "${EXPORT_DIR}/README.txt" << 'README'
NAS Workstation Monitor - Database Export
==========================================
Export Date: $(date)
Database: nas_workstation_monitor.db

Files:
------
Raw Data Tables:
  - workstation_mount_status.tsv  : All mount status checks
  - workstation_status.tsv        : Workstation online/offline status
  - software_availability.tsv     : Software availability checks
  - mount_failures.tsv            : Mount failure tracking
  - off_hours_issues.tsv          : Issues detected during off-hours (6PM-6AM)
  - monitor_config.tsv            : Database configuration

Summary Views:
  - current_status_summary.tsv    : Current status of all workstations/mounts
  - reliability_summary.tsv       : 7-day reliability statistics
  - software_summary.tsv          : Software availability summary
  - unresolved_failures.tsv       : Active unresolved failures

Format:
  - Tab-delimited (TSV)
  - Headers included
  - Can be opened in Excel, imported into R/Python, etc.

Usage Examples:
  - Excel: File > Open > Select .tsv file
  - R: read.delim("workstation_mount_status.tsv")
  - Python: pd.read_csv("workstation_mount_status.tsv", sep="\t")
README

echo ""
echo "Export complete! Files created:"
ls -lh "$EXPORT_DIR"
echo ""
echo "Export location: $EXPORT_DIR"
