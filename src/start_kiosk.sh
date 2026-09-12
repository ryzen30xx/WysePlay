#!/bin/bash
export DISPLAY=:0

# Load Xresources if available
if [ -f "$HOME/.Xresources" ]; then
    xrdb -merge "$HOME/.Xresources" 2>/dev/null || true
fi

# Disable all screen blanking & DPMS sleep so standby wallpaper is always visible
xset -dpms 2>/dev/null || true
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true
xset dpms force on 2>/dev/null || true

# Optimize network buffers & Wi-Fi bottom-half thread priority for zero-latency streaming
sudo sysctl -w net.core.rmem_max=16777216 2>/dev/null || true
sudo sysctl -w net.core.rmem_default=4194304 2>/dev/null || true
sudo sysctl -w net.core.wmem_max=16777216 2>/dev/null || true
sudo sysctl -w net.ipv4.udp_rmem_min=16384 2>/dev/null || true

PID_XRADIO=$(pgrep -f xradio_bh || true)
if [ -n "$PID_XRADIO" ]; then
    sudo chrt -f -p 50 $PID_XRADIO 2>/dev/null || true
    sudo renice -20 -p $PID_XRADIO 2>/dev/null || true
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

