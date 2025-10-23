# Database Cleanup Modes

## Overview

The NAS workstation monitor includes automatic database cleanup to prevent unlimited data growth. Two cleanup modes are available to match your monitoring needs.

## The Two Modes

### STANDARD Mode (Default)

**Philosophy:** Keep recent data plus awareness of ongoing problems.

**What it deletes:**
- Mount status records older than retention period
- Software availability checks older than retention period
- Mount failures that were **resolved** longer ago than retention period

**What it keeps:**
- Current workstation status (always)
- **Unresolved** mount failures (always, no matter how old)
- Recent records within retention period

**Example with 3-day retention:**
```
Day 1: Sarah's mount fails → Recorded as unresolved
Day 2: Still failing → Count increases, still unresolved → KEPT
Day 3: Fixed! → Marked as resolved
Day 6: Cleanup runs → Resolved 3 days ago → DELETED

But if never fixed:
Day 10: Still unresolved → KEPT (active problem needs visibility)
```

**Use when:**
- Students report recurring mount issues
- You want to track which workstations have chronic problems
- You need to verify if fixes actually worked
- Historical problem awareness is valuable

**Command:**
```bash
./nas_workstation_monitor_full_hpclib.py --fix --keep-hours 72
```

---

### AGGRESSIVE Mode

**Philosophy:** Database is just a current snapshot - no historical tracking.

**What it deletes:**
- Mount status records older than retention period
- Software availability checks older than retention period
- **ALL** mount failures older than retention period (resolved AND unresolved)
- Workstation status for workstations not seen within retention period

**What it keeps:**
- **ONLY** data within retention period
- Nothing else

**Example with 24-hour retention:**
```
Any data older than 24 hours → DELETED
Even unresolved problems → DELETED if older than 24 hours
Inactive workstations → DELETED if not seen in 24 hours

Database contains ONLY:
- Last 24 hours of mount checks
- Last 24 hours of software checks
- Recent failures (within 24 hours only)
- Recently active workstations only
```

**Use when:**
- You only need "is it working RIGHT NOW?"
- Database size is a concern
- You don't care about mount history or patterns
- Each monitoring run is independent
- Minimal data retention required

**Command:**
```bash
./nas_workstation_monitor_full_hpclib.py --fix --keep-hours 24 --aggressive-cleanup
```

## Comparison Table

| Feature | STANDARD | AGGRESSIVE |
|---------|----------|------------|
| Old mount checks | ✗ Deleted | ✗ Deleted |
| Old software checks | ✗ Deleted | ✗ Deleted |
| Resolved failures (old) | ✗ Deleted | ✗ Deleted |
| Unresolved failures (old) | ✓ **Kept** | ✗ **Deleted** |
| Current workstation status | ✓ **Kept** | ✗ **Deleted if inactive** |
| Recent data | ✓ Kept | ✓ Kept |
| Database size | Small | **Smallest** |
| Historical tracking | Some | **None** |
| Problem awareness | Long-term | Short-term only |

## Configuration Examples

### Conservative (Track problems)
```bash
# Keep 7 days, preserve unresolved issues
./nas_workstation_monitor_full_hpclib.py --fix --keep-hours 168
```

### Balanced (Default)
```bash
# Keep 3 days, preserve current state
./nas_workstation_monitor_full_hpclib.py --fix --keep-hours 72
```

### Minimal (Snapshot only)
```bash
# Keep 1 day, no historical tracking
./nas_workstation_monitor_full_hpclib.py --fix --keep-hours 24 --aggressive-cleanup
```

### Ultra-Minimal (Current results only)
```bash
# Keep only last 6 hours
./nas_workstation_monitor_full_hpclib.py --fix --keep-hours 6 --aggressive-cleanup
```

## Automatic vs Manual Cleanup

### Automatic Cleanup
Runs after each monitoring cycle:
```bash
# In your cron job:
0 * * * * /home/zeus/nas-monitor/nas_workstation_monitor_full_hpclib.py --fix --keep-hours 72
```

### Manual Cleanup
Use the query tool for one-time cleanup:
```bash
# Preview STANDARD cleanup
./nas_workstation_query.py cleanup --keep-hours 72

# Preview AGGRESSIVE cleanup
./nas_workstation_query.py cleanup --keep-hours 72 --aggressive

# Perform STANDARD cleanup
./nas_workstation_query.py cleanup --keep-hours 72 --confirm

# Perform AGGRESSIVE cleanup
./nas_workstation_query.py cleanup --keep-hours 24 --aggressive --confirm
```

## Decision Guide

### Choose STANDARD Mode If:

**Yes to any of these:**
- ✓ Students report recurring mount issues on same workstations
- ✓ You want to identify which workstations are problematic
- ✓ You need to verify if fixes resolved problems
- ✓ You want to see mount failure patterns over time
- ✓ Historical problem awareness helps your troubleshooting

**Example scenario:**
> "Adam's workstation keeps having mount issues. I want to know if this started after the last NAS update or if it's been ongoing."

### Choose AGGRESSIVE Mode If:

**Yes to any of these:**
- ✓ You only care about "is it working right now?"
- ✓ Database size is a concern
- ✓ Each monitoring run is independent
- ✓ You don't need historical context
- ✓ You want minimal data retention

**Example scenario:**
> "I just need to know current mount status. If it was broken yesterday but works today, I don't care about yesterday."

## What "Resolved" Means

A mount failure is marked as **resolved** when:
1. The mount was failing
2. A subsequent check shows it's working
3. System automatically marks it: `resolved=TRUE, resolved_at=<timestamp>`

**STANDARD mode:** Keeps resolved failures for retention period (e.g., 3 days), then deletes them.

**AGGRESSIVE mode:** Deletes ALL old failures regardless of resolved status.

## Real-World Examples

### Example 1: Recurring Problem Tracking (STANDARD)
```
Monday: Adam's /usr/local/chem.sw fails
Tuesday: Still failing → failure_count=2
Wednesday: Fixed by remount
Thursday: Working fine
Friday: Fails again! → New failure record

With STANDARD mode: You can see Adam had 2 separate failure episodes
With AGGRESSIVE mode: You'd only see if it's failing RIGHT NOW
```

### Example 2: Database Size Management (AGGRESSIVE)
```
Current database: 500MB with 6 months of data

After AGGRESSIVE cleanup with 24-hour retention:
- Database shrinks to ~5MB
- Only contains last 24 hours
- Much faster queries
- Minimal disk usage

Trade-off: No historical context
```

### Example 3: Weekly Review (STANDARD)
```
Friday afternoon: Review the week's mount issues

./nas_workstation_query.py stats

Shows:
- Adam: 85% success rate (3 failures this week)
- Sarah: 100% success rate
- Michael: 92% success rate (2 failures this week)

Action: Investigate why Adam has chronic issues

With AGGRESSIVE mode: Can't see weekly patterns
```

## Switching Between Modes

You can switch anytime:

### From STANDARD to AGGRESSIVE
```bash
# Do one-time aggressive cleanup
./nas_workstation_query.py cleanup --keep-hours 24 --aggressive --confirm

# Update cron to use aggressive mode
crontab -e
# Change to:
0 * * * * ... --keep-hours 24 --aggressive-cleanup
```

### From AGGRESSIVE back to STANDARD
```bash
# Just remove --aggressive-cleanup flag
crontab -e
# Change to:
0 * * * * ... --keep-hours 72
```

**Note:** Switching from AGGRESSIVE to STANDARD doesn't recover deleted data. It just changes future cleanup behavior.

## Monitoring Database Size

```bash
# Check database statistics
./nas_workstation_query.py dbinfo

Output:
Database file: /home/zeus/nas_workstation_monitor.db
Database size: 15.3 MB
Record counts:
  Mount status records:    12,450
  Workstation records:     17
  Failure records:         23
  Software check records:  8,320
Data range:
  Oldest record: 2025-10-01 08:00:00
  Newest record: 2025-10-23 14:30:00
```

If database is growing too large, consider:
1. Reducing retention period (`--keep-hours`)
2. Switching to aggressive mode (`--aggressive-cleanup`)
3. More frequent cleanups

## Recommendation for Your Use Case

**Start with STANDARD mode (default):**
```bash
./nas_workstation_monitor_full_hpclib.py --fix --keep-hours 72
```

**Why:**
- Students report "software is missing" → You need context
- Seeing patterns helps identify root causes
- 3 days of history is enough for most troubleshooting
- Unresolved issues stay visible until fixed

**Switch to AGGRESSIVE only if:**
- Database grows too large (>100MB)
- You never look at historical data
- You're confident in current monitoring

## Summary

**STANDARD Mode:**
- Keeps recent data + current state + unresolved problems
- Good for troubleshooting and pattern recognition
- Small database size
- **Recommended for most users**

**AGGRESSIVE Mode:**
- Keeps ONLY recent data
- Truly "no historical record"
- Smallest database size
- Use when historical context isn't needed
