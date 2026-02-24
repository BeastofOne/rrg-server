tell application "Google Chrome"
    activate
end tell
delay 0.5
tell application "System Events"
    keystroke "YOUR_PASSWORD_HERE"
    delay 0.2
    keystroke return
end tell
