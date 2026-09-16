#!/bin/bash
export DISPLAY="${DISPLAY:-:0}"
export LIBGL_DRI3_DISABLE=1

# Ensure framebuffer and DRM display engine are unblanked and active at startup
echo 0 | sudo tee /sys/class/graphics/fb0/blank >/dev/null 2>&1 || true
modetest -M sun4i-drm -w 49:DPMS:0 >/dev/null 2>&1 || true

# Optimize network buffers & Wi-Fi bottom-half thread priority for zero-latency streaming
sudo sysctl -w net.core.rmem_max=16777216 2>/dev/null || true
sudo sysctl -w net.core.rmem_default=4194304 2>/dev/null || true
sudo sysctl -w net.core.wmem_max=16777216 2>/dev/null || true
sudo sysctl -w net.ipv4.udp_rmem_min=16384 2>/dev/null || true
sudo sysctl -w net.ipv4.tcp_autocorking=0 2>/dev/null || true
sudo sysctl -w net.ipv4.tcp_low_latency=1 2>/dev/null || true
sudo sysctl -w net.ipv4.tcp_notsent_lowat=16384 2>/dev/null || true

# Disable Wi-Fi power saving so latency stays constant and NTP/UDP packets aren't dropped
export PATH=$PATH:/sbin:/usr/sbin
sudo iw dev wlan0 set power_save off 2>/dev/null || true
sudo iwconfig wlan0 power off 2>/dev/null || true

# Prevent CPU frequency dropping below 1.0 GHz (prevents SDIO missed interrupts on XR819 Wi-Fi)
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_min_freq; do
    echo 1008000 | sudo tee "$f" >/dev/null 2>&1 || true
done

# Ensure multicast route exists on active interface so mDNS announcements reach all AirPlay clients
DEF_IFACE=$(ip route 2>/dev/null | awk '/default/ {print $5; exit}')
if [ -n "$DEF_IFACE" ]; then
    sudo ip route replace 224.0.0.0/4 dev "$DEF_IFACE" 2>/dev/null || true
fi
if ip link show wlan0 >/dev/null 2>&1 && [ "$DEF_IFACE" != "wlan0" ]; then
    sudo ip route add 224.0.0.0/4 dev wlan0 2>/dev/null || true
fi

PID_XRADIO=$(pgrep -f xradio_bh || true)
if [ -n "$PID_XRADIO" ]; then
    sudo chrt -f -p 50 $PID_XRADIO 2>/dev/null || true
    sudo renice -20 -p $PID_XRADIO 2>/dev/null || true
fi

# If X11 DISPLAY is present (legacy X11 setup), start Openbox
if [ -n "$DISPLAY" ]; then
    if [ -f "$HOME/.Xresources" ]; then
        xrdb -merge "$HOME/.Xresources" 2>/dev/null || true
    fi
    xset +dpms 2>/dev/null || true
    xset s off 2>/dev/null || true
    xset s 0 0 2>/dev/null || true
    xset s noblank 2>/dev/null || true
    xset dpms force on 2>/dev/null || true
    OPENBOX_RC="${XDG_CONFIG_HOME:-$HOME/.config}/openbox/rc.xml"
    if [ -f "$OPENBOX_RC" ]; then
        openbox --config-file "$OPENBOX_RC" &
    else
        openbox &
    fi
fi

# Run Kiosk Manager in native DRM or X11 mode
exec python3 -u /opt/airplay/kiosk_manager.py 2>&1 | tee -a /tmp/kiosk.log
