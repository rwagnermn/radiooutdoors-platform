RADIO OUTDOORS PROJECT MANAGER v1

Copy these files into:
C:\Users\rwagn\Development\radiooutdoors-platform\

Then double-click:
Start-RadioOutdoors-Project-Manager.bat

Recommended .gitignore additions:
local-backups/
project-manager-logs/

Dashboard metrics:
- Git branch
- Working tree
- GitHub ahead/behind
- Last commit
- Django check
- Applied/unapplied migrations
- Missing migrations
- Last recorded test result
- Port 8000 / Django server PID
- Extra Radio Outdoors runserver processes
- Python / .venv
- Django version
- Secret-file protection
- Database backup age
- Media backup age
- Disk space
- Overall checkpoint safety

Buttons:
- Refresh Status
- Full Checkpoint & Push
- Quick Checkpoint
- Run Tests
- Apply Migrations
- Start Server
- Stop Server
- Backup Database
- Backup Media
- Project Folder
- Logs

Full Checkpoint & Push blocks when:
- Django check fails
- models need migrations
- migrations are unapplied
- secrets/local files are unsafe
- git diff --check fails

It stages only after your approval, rechecks staged safety, commits with a timestamp,
pushes main to origin, and logs the result.

The manager never displays the contents of API keys or passwords.
