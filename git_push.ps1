Set-Location "C:\Users\Greg\Documents\Claude\Projects\Trading"

# Remove any stale lock files
Remove-Item -Force ".git\config.lock" -ErrorAction SilentlyContinue
Remove-Item -Force ".git\index.lock" -ErrorAction SilentlyContinue

# Initialize git if needed
if (-not (Test-Path ".git")) {
    git init
}

# Set remote
$remotes = git remote
if ($remotes -notcontains "origin") {
    git remote add origin https://github.com/captsulu/Robinhood-Options.git
} else {
    git remote set-url origin https://github.com/captsulu/Robinhood-Options.git
}

# Fetch from GitHub
Write-Host "Fetching from GitHub..." -ForegroundColor Cyan
git fetch origin

# Create local main branch tracking origin/main
git checkout -B main origin/main

# Stage all local files on top
Write-Host "Staging all files..." -ForegroundColor Cyan
git add --all

# Check if there's anything to commit
$status = git status --porcelain
if ($status) {
    $date = Get-Date -Format "yyyy-MM-dd"
    git commit -m "Update Robinhood monitoring system - $date"
    Write-Host "`nCommit created. Now pushing..." -ForegroundColor Cyan
    git push -u origin main
    Write-Host "`nAll done! Changes pushed to GitHub." -ForegroundColor Green
} else {
    Write-Host "`nNothing to commit - already up to date." -ForegroundColor Yellow
}

Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
