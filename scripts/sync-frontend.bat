@echo off
echo Syncing frontend to docs/...
copy /Y frontend\index.html docs\index.html
powershell -Command "(Get-Content docs\index.html) -replace \"const API = ''\", \"const API = 'https://api.jsomics.com'\" | Set-Content docs\index.html"
echo Checking API constant in docs/index.html...
powershell -Command "Select-String -Path docs\index.html -Pattern 'const API'"
echo Done. Commit and push to deploy.
