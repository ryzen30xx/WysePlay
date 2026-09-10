import os, sys, time, subprocess, re, signal, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_wallpaper

try:
    import pyudev
    HAS_PYUDEV = True
except ImportError:
    HAS_PYUDEV = False

CURRENT_LOCKED = False
CURRENT_PROC = None
WIFI_GUI_PROC = None
CURRENT_DISPLAY = None
CURRENT_NET_TYPE = None
STATE_LOCK = threading.Lock()

def set_inputs(locked: bool):
    global CURRENT_LOCKED
    if CURRENT_LOCKED == locked:
        return
    CURRENT_LOCKED = locked
    try:
        out = subprocess.check_output('DISPLAY=:0 xinput list', shell=True).decode()
        for line in out.splitlines():
            if 'slave  pointer' in line or 'slave  keyboard' in line or 'floating slave' in line:
                if 'XTEST' in line or 'Power' in line:
                    continue
                m = re.search(r'id=(\d+)', line)
                if m:
                    dev_id = m.group(1)
                    action = 'disable' if locked else 'enable'
                    subprocess.run(f'DISPLAY=:0 xinput {action} {dev_id} 2>/dev/null', shell=True)
        if locked:
            subprocess.run('unclutter -idle 0 -root &', shell=True)
            subprocess.run('DISPLAY=:0 xsetroot -cursor_name blank 2>/dev/null', shell=True)
            print("[Kiosk] Streaming active: Mouse & Keyboard LOCKED.")
        else:
            subprocess.run('pkill -9 unclutter 2>/dev/null', shell=True)
            subprocess.run('DISPLAY=:0 xsetroot -cursor_name left_ptr 2>/dev/null', shell=True)
            print("[Kiosk] Standby: Mouse & Keyboard UNLOCKED.")
    except Exception as e:
        print("[Kiosk] Input error:", e)

def has_active_video_window():
    """Returns True ONLY when an active UxPlay video streaming window is mapped."""
    try:
        out = subprocess.check_output('DISPLAY=:0 xprop -root _NET_CLIENT_LIST 2>/dev/null', shell=True).decode()
        parts = out.split('#')
        if len(parts) > 1:
            win_ids = parts[1].replace(',', ' ').split()
            for wid in win_ids:
                wid = wid.strip()
                if not wid or wid == '0x0':
                    continue
                try:
                    c_out = subprocess.check_output(f'DISPLAY=:0 xprop -id {wid} WM_CLASS 2>/dev/null', shell=True).decode().lower()
                    if 'uxplay' in c_out or 'gst' in c_out or 'ximagesink' in c_out:
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False

def manage_wifi_gui():
    global WIFI_GUI_PROC, CURRENT_NET_TYPE
    with STATE_LOCK:
        if CURRENT_NET_TYPE == "NONE":
            # Need wifi setup GUI
            if WIFI_GUI_PROC is None or WIFI_GUI_PROC.poll() is not None:
                print("[Kiosk] No network: Launching interactive Wi-Fi Setup GUI...")
                env = dict(os.environ, DISPLAY=":0")
                WIFI_GUI_PROC = subprocess.Popen(["python3", "/opt/airplay/wifi_gui.py"], env=env)
        else:
            # Connected to LAN or Wi-Fi -> close wifi setup GUI
            if WIFI_GUI_PROC is not None and WIFI_GUI_PROC.poll() is None:
                print(f"[Kiosk] Network connected ({CURRENT_NET_TYPE}): Closing Wi-Fi Setup GUI...")
                try:
                    WIFI_GUI_PROC.terminate()
                    WIFI_GUI_PROC.wait(timeout=1.0)
                except Exception:
                    if WIFI_GUI_PROC and WIFI_GUI_PROC.poll() is None:
                        WIFI_GUI_PROC.kill()
                WIFI_GUI_PROC = None

def window_watcher():
    """Monitors active X11 windows: locks inputs, forces screen awake on stream, restores wallpaper on end."""
    def _watch():
        was_active = False
        while True:
            active = has_active_video_window()
            if active != was_active:
                set_inputs(active)
                if active and not was_active:
                    # Stream started: instantly wake up monitor and disable DPMS sleep while streaming
                    subprocess.run('DISPLAY=:0 xset dpms force on 2>/dev/null', shell=True)
                    subprocess.run('DISPLAY=:0 xset -dpms s off 2>/dev/null', shell=True)
                    print("[Kiosk] AirPlay stream started: Woke up monitor & kept screen awake.")
                elif not active and was_active:
                    # Stream ended: repaint clean standby wallpaper and re-enable 30s DPMS
                    subprocess.run('DISPLAY=:0 feh --no-fehbg --bg-fill /opt/airplay/standby.png 2>/dev/null', shell=True)
                    subprocess.run('DISPLAY=:0 xset +dpms dpms 30 30 30 s 30 30 2>/dev/null', shell=True)
                    print("[Kiosk] AirPlay stream ended: Restored standby wallpaper & re-enabled 30s DPMS sleep.")
                was_active = active
            time.sleep(0.3)
    t = threading.Thread(target=_watch, daemon=True, name="WindowWatcher")
    t.start()

def restart_uxplay_for_display(new_display_info):
    """Gracefully terminates running UxPlay so supervisor loop restarts with new display profile."""
    global CURRENT_PROC
    print(f"[Hotplug] Display change detected! New target: {new_display_info}")
    with STATE_LOCK:
        if CURRENT_PROC and CURRENT_PROC.poll() is None:
            print("[Hotplug] Terminating UxPlay to apply new display profile...")
            try:
                CURRENT_PROC.terminate()
                CURRENT_PROC.wait(timeout=2.0)
            except Exception:
                if CURRENT_PROC and CURRENT_PROC.poll() is None:
                    CURRENT_PROC.kill()

def hotplug_and_network_watcher():
    """Watches for display hotplug (via udev/DRM + RandR polling) and network state changes."""
    def _watch():
        global CURRENT_DISPLAY, CURRENT_NET_TYPE

        udev_monitor = None
        if HAS_PYUDEV:
            try:
                context = pyudev.Context()
                udev_monitor = pyudev.Monitor.from_netlink(context)
                udev_monitor.filter_by(subsystem='drm')
            except Exception as e:
                print("[Hotplug] pyudev init error:", e)

        while True:
            event_triggered = False
            if udev_monitor:
                try:
                    dev = udev_monitor.poll(timeout=1.0)
                    if dev is not None:
                        event_triggered = True
                        print(f"[Hotplug] Kernel DRM event received ({dev.action})")
                except Exception:
                    time.sleep(1.0)
            else:
                time.sleep(1.0)

            # 1. Check Network changes
            try:
                net_type, _, _ = make_wallpaper.check_network_status()
                if CURRENT_NET_TYPE is not None and net_type != CURRENT_NET_TYPE:
                    print(f"[Network] Network state changed: {CURRENT_NET_TYPE} -> {net_type}")
                    CURRENT_NET_TYPE = net_type
                    make_wallpaper.generate_wallpaper()
                    subprocess.run('DISPLAY=:0 feh --no-fehbg --bg-fill /opt/airplay/standby.png 2>/dev/null', shell=True)
                    manage_wifi_gui()
            except Exception as e:
                print("[Network] Watcher error:", e)

            # 2. Check Display changes
            try:
                if event_triggered:
                    time.sleep(0.5)
                    subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
                    time.sleep(0.5)

                res, rate, name = make_wallpaper.get_display_info()
                new_info = (name, res, rate)

                if CURRENT_DISPLAY is not None and new_info != CURRENT_DISPLAY:
                    time.sleep(0.5)
                    subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
                    time.sleep(0.5)
                    res2, rate2, name2 = make_wallpaper.get_display_info()
                    stable_info = (name2, res2, rate2)

                    if stable_info != CURRENT_DISPLAY:
                        restart_uxplay_for_display(stable_info)
            except Exception as e:
                print("[Hotplug] Check error:", e)

    t = threading.Thread(target=_watch, daemon=True, name="HotplugWatcher")
    t.start()

def main():
    global CURRENT_PROC, CURRENT_DISPLAY, CURRENT_NET_TYPE
    os.environ['DISPLAY'] = ':0'

    # Clear root screen and configure DPMS monitor sleep (30s idle, wakes on stream)
    subprocess.run('DISPLAY=:0 xsetroot -solid "#000000"', shell=True)
    subprocess.run('DISPLAY=:0 xset +dpms dpms 30 30 30 s 30 30 2>/dev/null', shell=True)
    
    # Ensure inputs are unlocked in standby
    set_inputs(False)

    # Initial probe with xrandr --auto
    subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
    time.sleep(0.5)

    # Initial Network status
    CURRENT_NET_TYPE, _, _ = make_wallpaper.check_network_status()

    # Start background watcher threads
    window_watcher()
    hotplug_and_network_watcher()

    # Launch or close Wi-Fi GUI based on initial network state
    manage_wifi_gui()

    while True:
        # 1. Detect display and generate wallpaper
        monitor_name, res, rate = make_wallpaper.generate_wallpaper()
        CURRENT_DISPLAY = (monitor_name, res, rate)

        # Apply wallpaper
        subprocess.run('DISPLAY=:0 feh --no-fehbg --bg-fill /opt/airplay/standby.png 2>/dev/null', shell=True)

        # Check for 4K
        extra_flags = []
        try:
            w = int(res.split('x')[0])
            if w >= 3840:
                extra_flags.append('-h265')
        except Exception:
            pass

        cmd = [
            'uxplay',
            '-nh',
            '-n', monitor_name,
            '-fs',
            '-s', f'{res}@{rate}',
            '-fps', str(rate),
            '-reset', '1',
            '-nofreeze',
            '-vs', 'ximagesink'
        ] + extra_flags

        print(f"[Kiosk] Starting UxPlay as '{monitor_name}' with {res}@{rate}Hz...")
        with STATE_LOCK:
            CURRENT_PROC = subprocess.Popen(cmd)

        start_time = time.time()
        # Block until UxPlay exits (either closed, crashed, or terminated by hotplug watcher)
        ret = CURRENT_PROC.wait()
        
        # When UxPlay exits, ensure inputs are unlocked and give brief pause
        set_inputs(False)

        # Defensive backoff: if UxPlay crashed or exited too quickly, avoid tight busy loop
        elapsed = time.time() - start_time
        if elapsed < 2.0 or ret != 0:
            print(f"[Kiosk] UxPlay exited (code {ret}, elapsed {elapsed:.1f}s). Waiting 2s before restart...")
            time.sleep(2.0)
        else:
            time.sleep(0.5)

if __name__ == '__main__':
    main()
