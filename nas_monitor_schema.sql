-- NAS Workstation Monitor Database Schema
-- Following newdfstat pattern with views, triggers, and constraints


-- Configuration table (like konstants in newdfstat)
CREATE TABLE IF NOT EXISTS monitor_config (
    id INTEGER PRIMARY KEY CHECK (id=1),
    keep_hours INTEGER NOT NULL CHECK (keep_hours BETWEEN 1 AND 720),
    aggressive_cleanup INTEGER NOT NULL CHECK (aggressive_cleanup IN (0, 1))
) WITHOUT ROWID;

-- Default configuration
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

-- Workstation current state
CREATE TABLE IF NOT EXISTS workstation_status (
    workstation TEXT PRIMARY KEY,
    is_online INTEGER DEFAULT 1 CHECK (is_online IN (0, 1)),
    last_seen DATETIME,
    active_users INTEGER DEFAULT 0,
    user_list TEXT DEFAULT NULL,
    checked_by TEXT,
    slurm_job_id TEXT
) WITHOUT ROWID;


-- Mount failure tracking
CREATE TABLE IF NOT EXISTS mount_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workstation TEXT NOT NULL,
    mount_point TEXT NOT NULL,
    first_failure DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_failure DATETIME DEFAULT CURRENT_TIMESTAMP,
    failure_count INTEGER DEFAULT 1,
    resolved INTEGER DEFAULT 0 CHECK (resolved IN (0, 1)),
    resolved_at DATETIME,
    resolved_by TEXT,
    UNIQUE(workstation, mount_point, resolved)
);

-- Software availability checks
CREATE TABLE IF NOT EXISTS software_availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    workstation TEXT NOT NULL,
    software_name TEXT NOT NULL,
    mount_point TEXT NOT NULL,
    is_accessible INTEGER CHECK (is_accessible IN (0, 1)),
    check_time_ms REAL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_mount_status_time 
    ON workstation_mount_status(workstation, mount_point, timestamp);

CREATE INDEX IF NOT EXISTS idx_mount_status_workstation 
    ON workstation_mount_status(workstation, timestamp);

CREATE INDEX IF NOT EXISTS idx_software_time 
    ON software_availability(workstation, timestamp);

CREATE INDEX IF NOT EXISTS idx_failures_workstation 
    ON mount_failures(workstation, mount_point, resolved);

-- View: Recent mount checks (based on config)

-- Table: Off-hours issue tracking
CREATE TABLE IF NOT EXISTS off_hours_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workstation TEXT NOT NULL,
    issue_type TEXT NOT NULL,  -- 'offline', 'mount_failure', 'software_issue'
    details TEXT,              -- JSON or text description
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    notified INTEGER DEFAULT 0 CHECK (notified IN (0, 1)),
    notified_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_off_hours_notified 
    ON off_hours_issues(notified, detected_at);

CREATE VIEW IF NOT EXISTS recent_mount_checks AS
    SELECT * FROM workstation_mount_status
    WHERE timestamp >= datetime('now', 
        printf('-%d hours', (SELECT keep_hours FROM monitor_config WHERE id=1))
    );

-- View: Old mount checks (for cleanup)
CREATE VIEW IF NOT EXISTS old_mount_checks AS
    SELECT * FROM workstation_mount_status
    WHERE timestamp < datetime('now',
        printf('-%d hours', (SELECT keep_hours FROM monitor_config WHERE id=1))
    );

-- View: Recent software checks
CREATE VIEW IF NOT EXISTS recent_software_checks AS
    SELECT * FROM software_availability
    WHERE timestamp >= datetime('now',
        printf('-%d hours', (SELECT keep_hours FROM monitor_config WHERE id=1))
    );

-- View: Old software checks (for cleanup)
CREATE VIEW IF NOT EXISTS old_software_checks AS
    SELECT * FROM software_availability
    WHERE timestamp < datetime('now',
        printf('-%d hours', (SELECT keep_hours FROM monitor_config WHERE id=1))
    );

-- View: Current workstation status summary
CREATE VIEW IF NOT EXISTS current_workstation_summary AS
    WITH latest AS (
        SELECT m.* FROM workstation_mount_status m
        JOIN (
            SELECT workstation, mount_point, MAX(timestamp) AS max_t
            FROM workstation_mount_status
            GROUP BY workstation, mount_point
        ) l ON m.workstation = l.workstation 
           AND m.mount_point = l.mount_point 
           AND m.timestamp = l.max_t
    )
    SELECT 
        l.workstation,
        l.mount_point,
        l.timestamp AS last_check,
        l.status,
        l.users_active,
        w.is_online,
        w.user_list
    FROM latest l
    LEFT JOIN workstation_status w ON l.workstation = w.workstation;

-- View: Unresolved mount failures
CREATE VIEW IF NOT EXISTS unresolved_failures AS
    SELECT 
        workstation,
        mount_point,
        first_failure,
        last_failure,
        failure_count,
        julianday('now') - julianday(first_failure) AS days_failing
    FROM mount_failures
    WHERE resolved = 0
    ORDER BY failure_count DESC, first_failure ASC;

-- View: Recent failure summary
CREATE VIEW IF NOT EXISTS recent_failure_summary AS
    SELECT 
        workstation,
        COUNT(*) AS failure_count,
        COUNT(DISTINCT mount_point) AS affected_mounts,
        MIN(first_failure) AS earliest_failure,
        MAX(last_failure) AS latest_failure
    FROM mount_failures
    WHERE last_failure >= datetime('now', '-24 hours')
    GROUP BY workstation
    ORDER BY failure_count DESC;

-- View: Workstation reliability (7-day)
CREATE VIEW IF NOT EXISTS workstation_reliability AS
    WITH checks AS (
        SELECT 
            workstation,
            COUNT(*) AS total_checks,
            SUM(CASE WHEN status = 'mounted' THEN 1 ELSE 0 END) AS successful_checks
        FROM workstation_mount_status
        WHERE timestamp >= datetime('now', '-7 days')
        GROUP BY workstation
    )
    SELECT 
        workstation,
        total_checks,
        successful_checks,
        successful_checks * 100.0 / total_checks AS success_rate
    FROM checks
    WHERE total_checks > 0
    ORDER BY success_rate ASC, workstation;

-- View: Software availability summary
CREATE VIEW IF NOT EXISTS software_summary AS
    SELECT 
        software_name,
        mount_point,
        COUNT(*) AS total_checks,
        SUM(CASE WHEN is_accessible = 1 THEN 1 ELSE 0 END) AS accessible_count,
        SUM(CASE WHEN is_accessible = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS availability_pct
    FROM software_availability
    WHERE timestamp >= datetime('now', '-7 days')
    GROUP BY software_name, mount_point
    ORDER BY availability_pct ASC;

-- Trigger: Delete old mount checks
CREATE TRIGGER IF NOT EXISTS cleanup_old_mount_checks
    INSTEAD OF DELETE ON old_mount_checks
    BEGIN
        DELETE FROM workstation_mount_status
        WHERE timestamp IN (SELECT timestamp FROM old_mount_checks);
    END;

-- Trigger: Delete old software checks
CREATE TRIGGER IF NOT EXISTS cleanup_old_software_checks
    INSTEAD OF DELETE ON old_software_checks
    BEGIN
        DELETE FROM software_availability
        WHERE timestamp IN (SELECT timestamp FROM old_software_checks);
    END;

-- Trigger: Auto-resolve mount failures when successful check comes in
CREATE TRIGGER IF NOT EXISTS auto_resolve_failures
    AFTER INSERT ON workstation_mount_status
    WHEN NEW.status = 'mounted'
    BEGIN
        UPDATE mount_failures
        SET resolved = 1, resolved_at = datetime('now')
        WHERE workstation = NEW.workstation 
          AND mount_point = NEW.mount_point 
          AND resolved = 0;
    END;

-- Trigger: Track mount failures automatically
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


-- View for old resolved failures (for cleanup)
CREATE VIEW IF NOT EXISTS old_resolved_failures AS
    SELECT * FROM mount_failures
    WHERE resolved = 1
    AND resolved_at < datetime('now',
        printf('-%d hours', (SELECT keep_hours FROM monitor_config WHERE id=1))
    );

-- Indexes for faster cleanup queries
CREATE INDEX IF NOT EXISTS idx_mount_timestamp 
    ON workstation_mount_status(timestamp);

CREATE INDEX IF NOT EXISTS idx_software_timestamp 
    ON software_availability(timestamp);
