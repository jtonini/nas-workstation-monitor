-- =====================================================================
-- NAS Workstation Mount Monitor Database Schema - Version 2.0
-- Enhanced with connectivity issue tracking
-- =====================================================================

-- Configuration table
CREATE TABLE IF NOT EXISTS monitor_config (
    id INTEGER PRIMARY KEY CHECK (id=1),
    keep_hours INTEGER NOT NULL CHECK (keep_hours BETWEEN 1 AND 720),
    aggressive_cleanup INTEGER NOT NULL CHECK (aggressive_cleanup IN (0, 1))
);

-- Insert default config if not exists
INSERT OR IGNORE INTO monitor_config (id, keep_hours, aggressive_cleanup) 
VALUES (1, 168, 0);

-- Main fact table: mount status checks
CREATE TABLE IF NOT EXISTS workstation_mount_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    workstation TEXT NOT NULL,
    mount_point TEXT NOT NULL,
    device TEXT,
    filesystem TEXT,
    status TEXT NOT NULL,
    response_time_ms REAL,
    error_message TEXT,
    action_taken TEXT,
    users_active INTEGER DEFAULT 0,
    monitored_by TEXT,
    slurm_job_id TEXT
);

-- Workstation status table with enhanced connectivity tracking
CREATE TABLE IF NOT EXISTS workstation_status (
    workstation TEXT PRIMARY KEY,
    is_online INTEGER DEFAULT 1 CHECK (is_online IN (0, 1)),
    connectivity_status TEXT DEFAULT 'unknown',  -- connected, ssh_failed, unreachable
    last_check DATETIME,
    last_connectivity_issue DATETIME,
    active_users INTEGER DEFAULT 0,
    user_list TEXT,
    mount_status TEXT,  -- healthy, issues, unknown
    checked_by TEXT,
    last_successful_check DATETIME
);

-- NEW: Connectivity issues table (separate from mount failures)
CREATE TABLE IF NOT EXISTS connectivity_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    workstation TEXT NOT NULL,
    issue_type TEXT NOT NULL,  -- ssh_failed, host_unreachable, timeout, network_error
    error_message TEXT,
    resolved INTEGER DEFAULT 0 CHECK (resolved IN (0, 1)),
    resolved_at DATETIME,
    duration_minutes REAL
);

-- Software availability checks
CREATE TABLE IF NOT EXISTS software_availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    workstation TEXT NOT NULL,
    software_name TEXT NOT NULL,
    software_path TEXT NOT NULL,
    is_accessible INTEGER CHECK (is_accessible IN (0, 1)),
    check_time_ms REAL,
    error_message TEXT
);

-- Mount failures table (for actual mount issues, not connectivity)
CREATE TABLE IF NOT EXISTS mount_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workstation TEXT NOT NULL,
    mount_point TEXT NOT NULL,
    first_failure DATETIME NOT NULL,
    last_failure DATETIME NOT NULL,
    failure_count INTEGER DEFAULT 1,
    resolved INTEGER DEFAULT 0 CHECK (resolved IN (0, 1)),
    resolved_at DATETIME,
    UNIQUE(workstation, mount_point, resolved)
);

-- Off-hours issues for batched notifications
CREATE TABLE IF NOT EXISTS off_hours_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    workstation TEXT NOT NULL,
    issue_type TEXT NOT NULL,  -- mount_failure, connectivity, software_missing
    details TEXT,
    notified INTEGER DEFAULT 0 CHECK (notified IN (0, 1)),
    notification_sent_at DATETIME
);

-- =====================================================================
-- Indexes for performance
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_mount_status_time
    ON workstation_mount_status(workstation, mount_point, timestamp);

CREATE INDEX IF NOT EXISTS idx_mount_status_workstation
    ON workstation_mount_status(workstation, timestamp);

CREATE INDEX IF NOT EXISTS idx_mount_timestamp
    ON workstation_mount_status(timestamp);

CREATE INDEX IF NOT EXISTS idx_software_time
    ON software_availability(workstation, timestamp);

CREATE INDEX IF NOT EXISTS idx_mount_failures
    ON mount_failures(workstation, resolved, last_failure);

CREATE INDEX IF NOT EXISTS idx_off_hours
    ON off_hours_issues(notified, detected_at);

-- NEW: Index for connectivity issues
CREATE INDEX IF NOT EXISTS idx_connectivity_workstation_time
    ON connectivity_issues(workstation, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_connectivity_unresolved
    ON connectivity_issues(resolved, workstation);

-- =====================================================================
-- Views for common queries
-- =====================================================================

-- View: Recent mount checks (based on config)
CREATE VIEW IF NOT EXISTS recent_mount_checks AS
SELECT 
    ms.*,
    ws.is_online,
    ws.connectivity_status,
    ws.active_users
FROM workstation_mount_status ms
LEFT JOIN workstation_status ws ON ms.workstation = ws.workstation
WHERE ms.timestamp > datetime('now', '-' || (SELECT keep_hours FROM monitor_config) || ' hours');

-- View: Current workstation health
CREATE VIEW IF NOT EXISTS current_workstation_health AS
SELECT 
    ws.workstation,
    ws.is_online,
    ws.connectivity_status,
    ws.last_check,
    ws.mount_status,
    ws.active_users,
    COUNT(DISTINCT mf.mount_point) as failed_mounts,
    COUNT(DISTINCT ci.id) as connectivity_issues
FROM workstation_status ws
LEFT JOIN mount_failures mf ON ws.workstation = mf.workstation AND mf.resolved = 0
LEFT JOIN connectivity_issues ci ON ws.workstation = ci.workstation AND ci.resolved = 0
GROUP BY ws.workstation;

-- View: Issues summary (both connectivity and mount)
CREATE VIEW IF NOT EXISTS issues_summary AS
SELECT 
    'mount_failure' as issue_type,
    workstation,
    mount_point as details,
    last_failure as timestamp
FROM mount_failures
WHERE resolved = 0
UNION ALL
SELECT 
    'connectivity' as issue_type,
    workstation,
    issue_type || ': ' || COALESCE(error_message, 'No details') as details,
    timestamp
FROM connectivity_issues
WHERE resolved = 0
ORDER BY timestamp DESC;

-- View: Workstation reliability metrics
CREATE VIEW IF NOT EXISTS workstation_reliability AS
SELECT 
    workstation,
    COUNT(*) as total_checks,
    SUM(CASE WHEN status = 'mounted' THEN 1 ELSE 0 END) as successful_checks,
    SUM(CASE WHEN status != 'mounted' THEN 1 ELSE 0 END) as failed_checks,
    ROUND(100.0 * SUM(CASE WHEN status = 'mounted' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate,
    MAX(timestamp) as last_check
FROM workstation_mount_status
WHERE timestamp > datetime('now', '-7 days')
GROUP BY workstation;

-- =====================================================================
-- Triggers for automatic actions
-- =====================================================================

-- Trigger: Auto-resolve mount failures when successful check comes in
CREATE TRIGGER IF NOT EXISTS auto_resolve_mount_failures
    AFTER INSERT ON workstation_mount_status
    WHEN NEW.status = 'mounted'
    BEGIN
        UPDATE mount_failures
        SET resolved = 1, resolved_at = datetime('now')
        WHERE workstation = NEW.workstation
          AND mount_point = NEW.mount_point
          AND resolved = 0;
    END;

-- Trigger: Track mount failures
CREATE TRIGGER IF NOT EXISTS track_mount_failures
    AFTER INSERT ON workstation_mount_status
    WHEN NEW.status NOT IN ('mounted', 'newly_mounted')
    BEGIN
        INSERT INTO mount_failures (workstation, mount_point, first_failure, last_failure, failure_count, resolved)
        VALUES (NEW.workstation, NEW.mount_point, NEW.timestamp, NEW.timestamp, 1, 0)
        ON CONFLICT(workstation, mount_point, resolved)
        DO UPDATE SET
            last_failure = NEW.timestamp,
            failure_count = failure_count + 1
        WHERE resolved = 0;
    END;

-- Trigger: Update workstation last successful check
CREATE TRIGGER IF NOT EXISTS update_last_successful_check
    AFTER INSERT ON workstation_mount_status
    WHEN NEW.status = 'mounted'
    BEGIN
        UPDATE workstation_status
        SET last_successful_check = NEW.timestamp
        WHERE workstation = NEW.workstation;
    END;

-- =====================================================================
-- Stored procedures (as views since SQLite doesn't support them)
-- =====================================================================

-- View to identify workstations needing attention
CREATE VIEW IF NOT EXISTS workstations_needing_attention AS
SELECT 
    workstation,
    CASE 
        WHEN connectivity_status != 'connected' THEN 'Check connectivity'
        WHEN mount_status = 'issues' THEN 'Check mounts'
        ELSE 'Monitor'
    END as action_needed,
    last_check,
    last_connectivity_issue
FROM workstation_status
WHERE connectivity_status != 'connected' 
   OR mount_status = 'issues'
   OR last_check < datetime('now', '-2 hours');
