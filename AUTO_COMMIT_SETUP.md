# Auto-Commit Setup Guide

This guide explains how to set up automatic GitHub commits for maintainers who have write access to the repository.

## Overview

The auto-commit feature automatically commits and pushes updated food inspection data to GitHub when changes are detected. This is useful for:
- Automated daily scrapes via Task Scheduler
- Keeping the public dataset up-to-date automatically
- Avoiding manual git commands after each run

## Files (Local Only - Not Committed)

These files are in `.gitignore` and won't be committed to the repository:

1. **`auto_commit.py`** - Python script that commits/pushes changes
2. **`run_pipeline_with_commit.bat`** - Batch file that runs pipeline + auto-commit

## Setup Instructions

### 1. Copy the Template Files

The files should already exist in your local directory. If not, create them:

**`auto_commit.py`** - See the actual file in your working directory

**`run_pipeline_with_commit.bat`** - See the actual file in your working directory

### 2. Test the Auto-Commit

Run manually to test:

```bash
# Run pipeline with auto-commit
run_pipeline_with_commit.bat
```

Expected behavior:
- Runs the full pipeline
- If CSV changed: commits and pushes to GitHub
- If no changes: exits gracefully

### 3. Update Task Scheduler (Optional)

If you have Task Scheduler set up, update it to use the auto-commit version:

1. Open Task Scheduler
2. Find your existing "Food Inspection Data Update" task
3. Edit the Action:
   - **Old:** `C:\PythonCode\LexKYFoodScores\run_pipeline.bat`
   - **New:** `C:\PythonCode\LexKYFoodScores\run_pipeline_with_commit.bat --no-pause`
4. Save

The `--no-pause` flag prevents the "Press any key" prompt when running unattended.

## How It Works

### Pipeline Flow

```
run_pipeline_with_commit.bat
    ↓
Calls run_pipeline.bat
    ↓ (if successful)
Calls auto_commit.py
    ↓
Checks if joined_scores_violations.csv changed
    ↓ (if changed)
Commits with scrape date in message
    ↓
Pushes to GitHub
```

### Commit Message Format

```
Update food inspection data - Scrape: YYYY-MM-DD

Updated dataset with latest food inspection records.

Statistics:
- Total records: 12,030
- Unique establishments: 1,687
- Scrape date: 2025-10-06

🤖 Auto-committed by pipeline automation
```

## Security Considerations

### Git Credentials

The auto-commit feature requires git credentials to be configured. Options:

**Option 1: Credential Manager (Recommended for Windows)**
```bash
# Git will use Windows Credential Manager automatically
# Just do a manual git push once and save credentials when prompted
git push
```

**Option 2: SSH Keys**
```bash
# Set up SSH key authentication
# See: https://docs.github.com/en/authentication/connecting-to-github-with-ssh
```

**Option 3: Personal Access Token**
```bash
# Create a PAT with repo permissions
# See: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token
git config credential.helper store
# Then git push once and enter PAT as password
```

### Why These Files Aren't Committed

1. **Security**: Prevents accidental credential exposure
2. **Access Control**: Only maintainers with write access should auto-commit
3. **Flexibility**: Each maintainer can customize their setup
4. **Clean Repo**: Other users get a clean pipeline without commit logic

## Troubleshooting

### "Git push failed: Authentication failed"

- **Cause**: Git credentials not configured
- **Fix**: Set up credential helper (see Security Considerations above)

### "Auto-commit encountered an issue"

- **Check**: Run `python auto_commit.py` manually to see detailed error
- **Common causes**:
  - Git credentials not configured
  - No internet connection
  - CSV file doesn't exist

### Script runs but doesn't commit

- **Cause**: No changes detected by git
- **Check**: Run `git status` to see if CSV actually changed
- **Note**: Git is smart - if content is identical, no commit is needed

## For Other Users (Without Auto-Commit)

Users without write access should use:
- `run_pipeline.bat` - Standard pipeline without auto-commit
- They won't have `auto_commit.py` or `run_pipeline_with_commit.bat`
- They can still contribute by opening pull requests

## Disabling Auto-Commit

To disable auto-commit:
1. Delete `auto_commit.py` and `run_pipeline_with_commit.bat`
2. Use `run_pipeline.bat` instead
3. Or update Task Scheduler to use `run_pipeline.bat`

Simple!
