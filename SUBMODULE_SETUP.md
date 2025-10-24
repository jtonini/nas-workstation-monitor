# Git Submodule Setup Instructions

## Initial Setup (for repository maintainer)

When setting up the repository for the first time:

```bash
# Navigate to your repository
cd nas-workstation-monitor

# Add hpclib as a submodule
git submodule add https://github.com/georgeflanagin/hpclib.git hpclib

# Commit the submodule
git add .gitmodules hpclib
git commit -m "Add hpclib as git submodule"
git push
```

## For Users Cloning the Repository

### Option 1: Clone with submodules (recommended)

```bash
git clone --recurse-submodules https://github.com/YOUR_USERNAME/nas-workstation-monitor.git
```

### Option 2: Clone then initialize submodules

```bash
git clone https://github.com/YOUR_USERNAME/nas-workstation-monitor.git
cd nas-workstation-monitor
git submodule init
git submodule update
```

## Updating hpclib

To pull the latest changes from hpclib:

```bash
cd nas-workstation-monitor

# Update submodule to latest
git submodule update --remote hpclib

# Commit the update
git add hpclib
git commit -m "Update hpclib to latest version"
git push
```

## Verifying Submodule

```bash
# Check submodule status
git submodule status

# Should show something like:
# +abc1234 hpclib (heads/main)

# Verify files are present
ls -la hpclib/
# Should see: sqlitedb.py, dorunrun.py, urdecorators.py, etc.
```

## Troubleshooting

**Empty hpclib folder:**
```bash
git submodule update --init --recursive
```

**Submodule not tracking latest:**
```bash
cd hpclib
git checkout main
git pull
cd ..
git add hpclib
git commit -m "Update hpclib"
```

**Remove submodule (if needed to fallback to copying files):**
```bash
git submodule deinit hpclib
git rm hpclib
rm -rf .git/modules/hpclib
```

## Fallback: Copy Files Directly

If submodules don't work in your environment, copy files directly:

```bash
# Copy required files from hpclib
cp /usr/local/src/hpclib/sqlitedb.py .
cp /usr/local/src/hpclib/dorunrun.py .
cp /usr/local/src/hpclib/urdecorators.py .
cp /usr/local/src/hpclib/urlogger.py .
cp /usr/local/src/hpclib/linuxutils.py .

# Update imports in Python files (remove 'hpclib.' prefix)
# In nas_monitor.py, nas_monitor_dbclass.py, nas_query.py:
# Change: from hpclib.sqlitedb import SQLiteDB
# To:     from sqlitedb import SQLiteDB
```
