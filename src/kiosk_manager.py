import os, sys, time, subprocess, re, signal, threading, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass
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
CURRENT_WIFI_GUI_ACTIVE = None
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
    global WIFI_GUI_PROC
    with STATE_LOCK:
        if WIFI_GUI_PROC is None or WIFI_GUI_PROC.poll() is not None:
            print("[Kiosk] Launching/ensuring unified Standby & Wi-Fi Kiosk UI...")
            env = dict(os.environ, DISPLAY=":0")
            WIFI_GUI_PROC = subprocess.Popen(["python3", "/opt/airplay/wifi_gui.py"], env=env)


def get_uxplay_tcp_connections(pid):
    """
    Returns (estab_count, close_wait_count) for the given UxPlay PID.
    Uses 'ss -t -p' to inspect active TCP sockets.
    """
    if not pid:
        return 0, 0
    try:
        out = subprocess.check_output(f"ss -t -p 2>/dev/null | grep -E 'pid={pid}[,)]'", shell=True).decode()
        estab = 0
        close_wait = 0
        for line in out.splitlines():
            parts = line.split()
            if parts:
                state = parts[0].upper()
                if state == 'ESTAB':
                    estab += 1
                elif 'CLOSE' in state or 'WAIT' in state:
                    close_wait += 1
        return estab, close_wait
    except Exception:
        return 0, 0

def window_watcher():
    """
    Monitors active X11 windows & TCP connection health:
    - Locks inputs during stream
    - Forces screen awake on stream start
    - Detects client disconnect (window closed OR TCP socket teardown/CLOSE_WAIT)
    - Automatically terminates zombie UxPlay on disconnect and restores standby wallpaper
    """
    def _watch():
        was_active = False
        no_estab_ticks = 0

        while True:
            active = has_active_video_window()

            # Active stream health check: if window is open but TCP connection closed/hung
            if active:
                with STATE_LOCK:
                    proc = CURRENT_PROC
                if proc and proc.poll() is None:
                    estab, close_wait = get_uxplay_tcp_connections(proc.pid)
                    if estab == 0 or close_wait > 0:
                        no_estab_ticks += 1
                        # If no established connection or lingering in CLOSE_WAIT for >= 1s (~3 ticks)
                        if no_estab_ticks >= 3:
                            print(f"[Kiosk] Client disconnected (ESTAB={estab}, CLOSE_WAIT={close_wait}). Resetting UxPlay...")
                            stop_uxplay(reason="Client disconnected (socket closed)")
                            no_estab_ticks = 0
                            time.sleep(0.3)
                            continue
                    else:
                        no_estab_ticks = 0
            else:
                no_estab_ticks = 0

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

def is_physical_display_connected():
    """Checks if at least one physical display is connected via DRM sysfs or xrandr."""
    # 1. Fast check via kernel DRM sysfs (< 1ms)
    try:
        status_files = glob.glob("/sys/class/drm/card*-*/status")
        if status_files:
            for sf in status_files:
                try:
                    with open(sf, "r") as f:
                        if f.read().strip() == "connected":
                            return True
                except Exception:
                    pass
            return False
    except Exception:
        pass

    # 2. Fallback check via xrandr
    try:
        out = subprocess.check_output("DISPLAY=:0 xrandr 2>/dev/null", shell=True).decode()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == 'connected':
                return True
    except Exception:
        pass

    return False

def stop_uxplay(reason="Display disconnected"):
    """Gracefully terminates running UxPlay."""
    global CURRENT_PROC
    with STATE_LOCK:
        if CURRENT_PROC and CURRENT_PROC.poll() is None:
            print(f"[Kiosk] {reason}. Terminating UxPlay server...")
            try:
                CURRENT_PROC.terminate()
                CURRENT_PROC.wait(timeout=2.0)
            except Exception:
                if CURRENT_PROC and CURRENT_PROC.poll() is None:
                    CURRENT_PROC.kill()

def restart_uxplay_for_display(new_display_info):
    """Gracefully terminates running UxPlay and Kiosk UI so they restart with new display profile."""
    global WIFI_GUI_PROC
    print(f"[Hotplug] Display change detected! New target: {new_display_info}")
    stop_uxplay(reason="Display configuration changed")
    with STATE_LOCK:
        if WIFI_GUI_PROC is not None:
            try:
                WIFI_GUI_PROC.terminate()
            except Exception:
                pass
            WIFI_GUI_PROC = None

def hotplug_and_network_watcher():
    """Watches for display hotplug (via udev/DRM + RandR polling) and network state changes."""
    def _watch():
        global CURRENT_DISPLAY, CURRENT_NET_TYPE, CURRENT_WIFI_GUI_ACTIVE

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

            # 1. Ensure unified Standby & Wi-Fi Kiosk UI is alive
            try:
                manage_wifi_gui()
            except Exception as e:
                print("[Kiosk] UI watcher error:", e)


            # 2. Check Display changes
            try:
                display_connected = is_physical_display_connected()
                if not display_connected:
                    stop_uxplay(reason="Physical display disconnected")
                else:
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

def load_hardware_profile():
    """Loads benchmarked hardware profile to limit resolution & FPS for smooth decoding."""
    config_path = "/opt/airplay/hw_profile.json"
    if not os.path.isfile(config_path):
        alt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hw_profile.json")
        if os.path.isfile(alt_path):
            config_path = alt_path
        else:
            return None
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Kiosk] Error reading {config_path}: {e}")
        return None

def main():
    global CURRENT_PROC, CURRENT_DISPLAY, CURRENT_NET_TYPE, CURRENT_WIFI_GUI_ACTIVE
    os.environ['DISPLAY'] = ':0'

    # Clear root screen and configure DPMS monitor sleep (30s idle, wakes on stream)
    subprocess.run('DISPLAY=:0 xsetroot -solid "#000000"', shell=True)
    subprocess.run('DISPLAY=:0 xset +dpms dpms 30 30 30 s 30 30 2>/dev/null', shell=True)
    
    # Ensure inputs are unlocked in standby
    set_inputs(False)

    # Initial probe with xrandr --auto
    subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
    time.sleep(0.5)

    # Initial Network and Wi-Fi GUI status
    CURRENT_NET_TYPE, _, _ = make_wallpaper.check_network_status()
    CURRENT_WIFI_GUI_ACTIVE = make_wallpaper.is_wifi_gui_active()

    # Start background watcher threads
    window_watcher()
    hotplug_and_network_watcher()

    # Launch or close Wi-Fi GUI based on initial network state
    manage_wifi_gui()

    while True:
        # Check if at least one physical display is connected before starting UxPlay
        if not is_physical_display_connected():
            print("[Kiosk] No physical display connected. Pausing UxPlay server to prevent blind connections...")
            stop_uxplay(reason="No physical display connected")
            while not is_physical_display_connected():
                time.sleep(1.0)
            print("[Kiosk] Physical display detected! Resuming UxPlay server...")
            time.sleep(0.5)
            subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
            time.sleep(0.5)

        # 1. Detect display and generate wallpaper
        monitor_name, res, rate = make_wallpaper.generate_wallpaper()
        CURRENT_DISPLAY = (monitor_name, res, rate)

        # Apply wallpaper
        subprocess.run('DISPLAY=:0 feh --no-fehbg --bg-fill /opt/airplay/standby.png 2>/dev/null', shell=True)

        # 2. UxPlay streaming parameters are STRICTLY determined by hardware benchmark profile
        # (Independent of the connected display, preventing downgraded performance from inferior setup monitors)
        profile = load_hardware_profile()
        target_res = "1920x1080"
        target_fps = 60
        target_h265 = False
        decoder = "avdec_h264"
        video_sink = "ximagesink"

        if profile and "selected_profile" in profile:
            sp = profile["selected_profile"]
            target_res = sp.get("resolution", "1920x1080")
            target_fps = sp.get("max_fps", 60)
            target_h265 = sp.get("h265", False)
            decoder = profile.get("decoder", "avdec_h264")
            video_sink = profile.get("video_sink", "ximagesink")
            print(f"[Kiosk] Benchmark Profile active: {sp.get('tier', 'Custom')} -> Stream: {target_res}@{target_fps}fps (H.265: {target_h265}, Decoder: {decoder}, Sink: {video_sink})")
        else:
            print(f"[Kiosk] No benchmark profile found, using default: {target_res}@{target_fps}fps")

        # Check for 4K / H.265
        extra_flags = []
        try:
            w = int(target_res.split('x')[0])
            if target_h265 or w >= 3840:
                extra_flags.append('-h265')
        except Exception:
            pass

        if decoder and decoder not in ('avdec_h264', 'avdec_h265'):
            extra_flags.extend(['-vd', decoder])

        cmd = [
            'uxplay',
            '-nh',
            '-n', monitor_name,
            '-nohold',
            '-fs',
            '-s', f'{target_res}@{target_fps}',
            '-fps', str(target_fps),
            '-reset', '3',
            '-nofreeze',
            '-vs', video_sink
        ] + extra_flags

        print(f"[Kiosk] Starting UxPlay as '{monitor_name}' with {target_res}@{target_fps}Hz (Monitor: {res}@{rate}Hz)...")
        with STATE_LOCK:
            CURRENT_PROC = subprocess.Popen(cmd)

        start_time = time.time()
        # Block until UxPlay exits (either closed, crashed, or terminated by hotplug watcher)
        ret = CURRENT_PROC.wait()
        
        # When UxPlay exits, ensure inputs are unlocked and give brief pause
        set_inputs(False)

        # Defensive backoff: only wait if UxPlay crashed immediately (< 2.0s and non-zero exit)
        elapsed = time.time() - start_time
        if elapsed < 2.0 and ret != 0:
            if not is_physical_display_connected():
                continue
            print(f"[Kiosk] UxPlay exited prematurely (code {ret}, elapsed {elapsed:.1f}s). Waiting 2s before restart...")
            time.sleep(2.0)
        else:
            time.sleep(0.3)

if __name__ == '__main__':
    main()
