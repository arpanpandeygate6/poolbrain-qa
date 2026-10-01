#!/bin/bash
# Schedules ./backup.sh every night at 02:00 (Mac local time) with launchd.
# If the Mac is asleep at 02:00, macOS runs it when the Mac wakes.
# Undo: launchctl bootout gui/$(id -u)/com.poolbrain-qa.n8n-backup && rm ~/Library/LaunchAgents/com.poolbrain-qa.n8n-backup.plist
set -euo pipefail
cd "$(dirname "$0")"
label=com.poolbrain-qa.n8n-backup
plist="$HOME/Library/LaunchAgents/$label.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$PWD/backup.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/n8n-backup.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/n8n-backup.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "Nightly n8n backup scheduled at 02:00. Log: ~/Library/Logs/n8n-backup.log"
