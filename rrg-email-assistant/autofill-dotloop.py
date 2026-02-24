#!/usr/bin/env python3
import subprocess

# Read password from separate file (you'll create this)
with open('/Users/jacobphillips/Desktop/email-assistant/.dotloop-pw', 'r') as f:
    password = f.read().strip()

# Use AppleScript via Python to type the password
applescript = f'''
tell application "Google Chrome"
    activate
end tell
delay 0.3
tell application "System Events"
    keystroke "{password}"
    delay 0.2
    keystroke return
end tell
'''

subprocess.run(['osascript', '-e', applescript])
