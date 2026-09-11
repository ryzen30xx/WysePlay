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
        if locked:
            subprocess.run('DISPLAY=:0 xsetroot -cursor_name blank 2>/dev/null', shell=True)
            print("[Kiosk] Streaming active: Mouse cursor hidden.")
        else:
            subprocess.run('DISPLAY=:0 xsetroot -cursor_name left_ptr 2>/dev/null', shell=True)
            print("[Kiosk] Standby: Mouse cursor restored.")
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
                    if any(k in c_out for k in ('uxplay', 'gst', 'ximagesink', 'xvimagesink', 'glimagesink', 'autovideosink')):
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

def cleanup_and_exit(signum, frame):
    global CURRENT_PROC, WIFI_GUI_PROC
    print(f"[Kiosk] Received signal {signum}. Cleaning up processes and exiting...")
    with STATE_LOCK:
        if CURRENT_PROC and CURRENT_PROC.poll() is None:
            try:
                CURRENT_PROC.terminate()
                CURRENT_PROC.wait(timeout=1.0)
            except Exception:
                CURRENT_PROC.kill()
        if WIFI_GUI_PROC and WIFI_GUI_PROC.poll() is None:
            try:
                WIFI_GUI_PROC.terminate()
            except Exception:
                pass
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup_and_exit)
signal.signal(signal.SIGINT, cleanup_and_exit)

def window_watcher():
    """
    Monitors active X11 windows:
    - Automatically hides Kiosk UI when streaming starts and wakes up screen
    - Restores Kiosk UI when streaming ends and restores DPMS sleep
    """
    def _watch():
        was_active = False

        while True:
            active = has_active_video_window()

            if active != was_active:
                set_inputs(active)
                if active and not was_active:
                    # Stream started: notify wifi_gui to withdraw and unmap window
                    try:
                        open("/tmp/airplay_streaming", "w").close()
                    except Exception:
                        pass
                    subprocess.run("DISPLAY=:0 xdotool search --class WifiKiosk windowunmap 2>/dev/null", shell=True)
                    subprocess.run('DISPLAY=:0 xsetroot -solid "#000000" 2>/dev/null', shell=True)
                    subprocess.run('DISPLAY=:0 xset dpms force on 2>/dev/null', shell=True)
                    subprocess.run('DISPLAY=:0 xset -dpms s off 2>/dev/null', shell=True)
                    print("[Kiosk] AirPlay stream started: Woke up monitor & kept screen awake.")
                elif not active and was_active:
                    # Stream ended: notify wifi_gui to restore and re-enable 30s DPMS
                    try:
                        os.remove("/tmp/airplay_streaming")
                    except OSError:
                        pass
                    subprocess.run("DISPLAY=:0 xdotool search --class WifiKiosk windowmap 2>/dev/null", shell=True)
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
    try:
        if os.path.exists("/tmp/airplay_streaming"):
            os.remove("/tmp/airplay_streaming")
    except OSError:
        pass

    # Clear root screen and configure DPMS monitor sleep (30s idle, wakes on stream)
    subprocess.run('DISPLAY=:0 xsetroot -solid "#000000"', shell=True)
    subprocess.run('DISPLAY=:0 xset +dpms dpms 30 30 30 s 30 30 2>/dev/null', shell=True)
    
    # Ensure inputs are unlocked in standby
    set_inputs(False)

    # Initial probe with xrandr --auto
    subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
    time.sleep(0.5)

    # Initial Network status synchronized at kernel level
    CURRENT_NET_TYPE, _, _ = make_wallpaper.check_network_status(wait_sync=True)
    CURRENT_WIFI_GUI_ACTIVE = make_wallpaper.is_wifi_gui_active()

    # Pre-generate standby wallpaper immediately with verified kernel network state
    monitor_name, res, rate = make_wallpaper.generate_wallpaper(
        wifi_gui_showing=(CURRENT_NET_TYPE == "NONE"),
        wait_sync=False
    )
    CURRENT_DISPLAY = (monitor_name, res, rate)
    subprocess.run('DISPLAY=:0 feh --no-fehbg --bg-fill /opt/airplay/standby.png 2>/dev/null', shell=True)

    # Start background watcher threads
    window_watcher()
    hotplug_and_network_watcher()

    # Launch or close Wi-Fi GUI based on verified initial network state
    manage_wifi_gui()

    hw_fallback_active = False
    consecutive_crashes = 0

    while True:
        # Check if physical display is connected before starting UxPlay
        if not is_physical_display_connected():
            print("[Kiosk] No physical display connected at startup. Waiting for monitor...")
            while not is_physical_display_connected():
                time.sleep(1.0)
            print("[Kiosk] Physical display detected! Resuming UxPlay server...")
            time.sleep(0.5)
            subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)

        # 1. Detect display and generate wallpaper
        monitor_name, res, rate = make_wallpaper.generate_wallpaper(wait_sync=False)
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
        video_sink = "autovideosink"

        if profile and "selected_profile" in profile:
            sp = profile["selected_profile"]
            target_res = sp.get("resolution", "1920x1080")
            target_fps = sp.get("max_fps", 60)
            target_h265 = sp.get("h265", False)
            decoder = profile.get("decoder", "avdec_h264")
            raw_sink = profile.get("video_sink", "autovideosink")
            video_sink = "autovideosink" if raw_sink in ("ximagesink", "", None) else raw_sink
            print(f"[Kiosk] Benchmark Profile active: {sp.get('tier', 'Custom')} -> Stream: {target_res}@{target_fps}fps (H.265: {target_h265}, Decoder: {decoder}, Sink: {video_sink})")
        else:
            print(f"[Kiosk] No benchmark profile found, using default: {target_res}@{target_fps}fps")

        # Automatic Fail-Safe: If hardware decoder previously crashed, force CPU decoder
        if hw_fallback_active:
            decoder = "avdec_h264"
            print("[Kiosk] Chế độ Fail-Safe đang bật: Sử dụng bộ giải mã CPU tiêu chuẩn (avdec_h264)")

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
            '-vs', video_sink,
            '-d'
        ] + extra_flags

        print(f"[Kiosk] Starting UxPlay as '{monitor_name}' with {target_res}@{target_fps}Hz (Monitor: {res}@{rate}Hz)...")
        with open("/tmp/uxplay.log", "w") as ux_log:
            with STATE_LOCK:
                CURRENT_PROC = subprocess.Popen(cmd, stdout=ux_log, stderr=subprocess.STDOUT)

            start_time = time.time()
            # Block until UxPlay exits (either closed, crashed, or terminated by hotplug watcher)
            ret = CURRENT_PROC.wait()
        
        # When UxPlay exits, ensure inputs are unlocked and give brief pause
        set_inputs(False)

        # Defensive backoff & Fail-Safe Auto-Recovery
        elapsed = time.time() - start_time
        if elapsed < 3.0 and ret != 0:
            consecutive_crashes += 1
            if not is_physical_display_connected():
                continue
            
            # If a custom hardware decoder caused 2 consecutive crashes, automatically drop to CPU decoder
            if consecutive_crashes >= 2 and decoder not in ('avdec_h264', 'avdec_h265') and not hw_fallback_active:
                print(f"[Kiosk] CẢNH BÁO: Bộ giải mã '{decoder}' gặp lỗi khi chạy UxPlay. Tự động chuyển sang CPU an toàn (avdec_h264)!")
                hw_fallback_active = True
                consecutive_crashes = 0

            print(f"[Kiosk] UxPlay exited prematurely (code {ret}, elapsed {elapsed:.1f}s, crashes: {consecutive_crashes}). Waiting 2s before restart...")
            time.sleep(2.0)
        else:
            consecutive_crashes = 0
            time.sleep(0.3)

if __name__ == '__main__':
    main()
