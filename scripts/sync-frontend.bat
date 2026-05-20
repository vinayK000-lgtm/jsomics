@echo off
echo Syncing frontend to docs/...
copy /Y frontend\index.html docs\index.html
powershell -Command "(Get-Content docs\index.html) -replace \"const API = ''\", \"const API = 'https://api.jsomics.com'\" | Set-Content docs\index.html"
echo Done.
git add docs\index.html
git status
