#!/bin/bash
# Read password from hidden file and type it
PASSWORD=$(cat /Users/jacobphillips/Desktop/email-assistant/.dotloop-pw)
cliclick t:"$PASSWORD"
sleep 0.2
cliclick kp:return
