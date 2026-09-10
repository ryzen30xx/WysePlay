#!/bin/bash
export DISPLAY=:0

# Load Xresources if available
if [ -f "$HOME/.Xresources" ]; then
    xrdb -merge "$HOME/.Xresources" 2>/dev/null || true
fi

# 1. Start clean Openbox in background
OPENBOX_RC="${XDG_CONFIG_HOME:-$HOME/.config}/openbox/rc.xml"
if [ -f "$OPENBOX_RC" ]; then
    openbox --config-file "$OPENBOX_RC" &
else
    openbox &
fi

# 2. Run Kiosk Manager
exec python3 /opt/airplay/kiosk_manager.py
