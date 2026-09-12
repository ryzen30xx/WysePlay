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

LAST_ACTIVITY = time.time()
MONITOR_ASLEEP = False
SLEEP_TIMEOUT = 30.0  # Seconds of standby idle before turning off display panel & backlight

def wake_display(reason="Activity"):
    global LAST_ACTIVITY, MONITOR_ASLEEP
    LAST_ACTIVITY = time.time()
    if MONITOR_ASLEEP:
        MONITOR_ASLEEP = False
        subprocess.run('DISPLAY=:0 xset dpms force on 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset -dpms s off s noblank 2>/dev/null', shell=True)
        print(f"[Kiosk] Display WOKEN UP ({reason}): Monitor panel & backlight ON.")

def sleep_display():
    global MONITOR_ASLEEP
    with STATE_LOCK:
        if MONITOR_ASLEEP:
            return
        if CURRENT_LOCKED:
            return
        if os.path.exists("/tmp/airplay_pin.txt"):
            return
        MONITOR_ASLEEP = True
        subprocess.run('DISPLAY=:0 xset +dpms 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset dpms force off 2>/dev/null', shell=True)
        print("[Kiosk] Idle 30s: Display entered DPMS SLEEP (monitor panel & backlight OFF).")

def display_power_manager():
    """
    Monitors system inactivity, mouse movement, and streaming state.
    Turns OFF monitor panel & backlight after 30s of inactivity in standby.
    Wakes monitor immediately upon network connection or mouse interaction.
    """
    global LAST_ACTIVITY, MONITOR_ASLEEP
    last_mouse_pos = None
    while True:
        time.sleep(1.0)
        # 1. Detect physical user interaction via mouse movement
        try:
            out = subprocess.check_output("DISPLAY=:0 xdotool getmouselocation 2>/dev/null || true", shell=True).decode()
            if "x:" in out and "y:" in out:
                parts = out.split()
                pos = (parts[0], parts[1])
                if last_mouse_pos is not None and pos != last_mouse_pos:
                    wake_display(reason="Mouse movement")
                last_mouse_pos = pos
        except Exception:
            pass

        # 2. If streaming or displaying PIN OTP, keep active and cancel sleep
        if CURRENT_LOCKED or os.path.exists("/tmp/airplay_pin.txt"):
            LAST_ACTIVITY = time.time()
            if MONITOR_ASLEEP:
                wake_display(reason="AirPlay streaming or PIN modal active")
            continue

        # 3. Check 30s idle timeout
        if not MONITOR_ASLEEP:
            idle_time = time.time() - LAST_ACTIVITY
            if idle_time >= SLEEP_TIMEOUT:
                sleep_display()

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

def on_stream_started():
    global CURRENT_LOCKED
    with STATE_LOCK:
        if CURRENT_LOCKED:
            return
        CURRENT_LOCKED = True
        wake_display(reason="AirPlay stream started")
        try:
            open("/tmp/airplay_streaming", "w").close()
        except Exception:
            pass
        subprocess.run("DISPLAY=:0 xdotool search --class WifiKiosk windowunmap 2>/dev/null", shell=True)
        subprocess.run('DISPLAY=:0 xsetroot -cursor_name blank 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xsetroot -solid "#000000" 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset dpms force on 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset -dpms s off 2>/dev/null', shell=True)
        print("[Kiosk] AirPlay stream started: Woke up monitor, kept screen awake & hid mouse.")

def on_stream_ended():
    global CURRENT_LOCKED
    with STATE_LOCK:
        if not CURRENT_LOCKED:
            return
        CURRENT_LOCKED = False
        try:
            if os.path.exists("/tmp/airplay_streaming"):
                os.remove("/tmp/airplay_streaming")
        except OSError:
            pass
        subprocess.run("DISPLAY=:0 xdotool search --class WifiKiosk windowmap 2>/dev/null", shell=True)
        subprocess.run('DISPLAY=:0 xsetroot -cursor_name left_ptr 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset -dpms s off s noblank 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset dpms force on 2>/dev/null', shell=True)
        wake_display(reason="AirPlay stream ended, standby restored")
        print("[Kiosk] AirPlay stream ended: Restored standby wallpaper (30s sleep timer started).")

def monitor_uxplay_output(proc):
    """
    Reads UxPlay stdout line-by-line in real time.
    Detects stream start, PIN prompts, and end events with 0ms delay.
    """
    try:
        with open("/tmp/uxplay.log", "a") as ux_log:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                ux_log.write(line)
                ux_log.flush()

                # 1. Wake display instantly upon any incoming client connection request
                if (
                    "Accepted IPv" in line
                    or "connection request from" in line
                    or "PAIR-PIN-START" in line
                ):
                    wake_display(reason="Incoming AirPlay connection")

                # 2. Track AirPlay PIN authentication requests and display OTP modal
                m = re.search(r'CLIENT MUST NOW ENTER PIN = "(\d{4})"', line)
                if m:
                    pin_code = m.group(1)
                    wake_display(reason=f"PIN OTP required: {pin_code}")
                    try:
                        with open("/tmp/airplay_pin.txt", "w") as pf:
                            pf.write(pin_code + "\n")
                        print(f"[Kiosk] PIN Passcode generated: {pin_code}. Displaying OTP modal on screen.")
                    except Exception:
                        pass
                elif "registered new client" in line:
                    try:
                        if os.path.exists("/tmp/airplay_pin.txt"):
                            os.remove("/tmp/airplay_pin.txt")
                    except Exception:
                        pass

                # 3. Stream lifecycle
                if "Initialized GStreamer video renderer" in line or "identified as Connection type RAOP" in line:
                    try:
                        if os.path.exists("/tmp/airplay_pin.txt"):
                            os.remove("/tmp/airplay_pin.txt")
                    except Exception:
                        pass
                    on_stream_started()
                elif (
                    "Destroying connection" in line
                    or "exiting TCP thread" in line
                    or "running is no longer true" in line
                    or "video has finished" in line
                    or "video_reset" in line
                ):
                    try:
                        if os.path.exists("/tmp/airplay_pin.txt"):
                            os.remove("/tmp/airplay_pin.txt")
                    except Exception:
                        pass
                    if CURRENT_LOCKED:
                        on_stream_ended()
                    # Terminate UxPlay cleanly so it restarts fresh for the next session
                    stop_uxplay(reason="Client disconnected / stream finished")
    except Exception as e:
        print("[Kiosk] UxPlay monitor error:", e)

def manage_wifi_gui():
    global WIFI_GUI_PROC
    with STATE_LOCK:
        if WIFI_GUI_PROC is None or WIFI_GUI_PROC.poll() is not None:
            print("[Kiosk] Launching/ensuring unified Standby & Wi-Fi Kiosk UI...")
            env = dict(os.environ, DISPLAY=":0")
            WIFI_GUI_PROC = subprocess.Popen(["python3", "-u", "/opt/airplay/wifi_gui.py"], env=env)

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
    Lightweight fallback watcher (runs every 2s, single xdotool check).
    Ensures state stays synchronized even if stdout stream drops.
    """
    def _watch():
        while True:
            time.sleep(2.0)
            if CURRENT_PROC and CURRENT_PROC.poll() is None:
                try:
                    out = subprocess.check_output(
                        "DISPLAY=:0 xdotool search --onlyvisible --class 'uxplay|gst' 2>/dev/null || true",
                        shell=True
                    ).decode().strip()
                    has_win = bool(out)
                    if has_win and not CURRENT_LOCKED:
                        on_stream_started()
                    elif not has_win and CURRENT_LOCKED:
                        on_stream_ended()
                except Exception:
                    pass

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

        disconnect_strikes = 0
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

            # 2. Check Display changes with robust 3s debounce (prevents HDMI HPD micro-glitches from killing UxPlay)
            try:
                if not is_physical_display_connected():
                    disconnect_strikes += 1
                    if disconnect_strikes >= 3:
                        stop_uxplay(reason="Physical display disconnected (confirmed 3s)")
                else:
                    disconnect_strikes = 0
                    if event_triggered:
                        time.sleep(1.0)
                        subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
                        time.sleep(0.5)

                        res, rate, name = make_wallpaper.get_display_info()
                        has_audio, _ = check_hdmi_audio_support()
                        new_info = (name, res, rate, has_audio)

                        if CURRENT_DISPLAY is not None and new_info != CURRENT_DISPLAY:
                            time.sleep(1.0)
                            subprocess.run('DISPLAY=:0 xrandr --auto', shell=True)
                            time.sleep(0.5)
                            res2, rate2, name2 = make_wallpaper.get_display_info()
                            has_audio2, _ = check_hdmi_audio_support()
                            stable_info = (name2, res2, rate2, has_audio2)

                            if stable_info != CURRENT_DISPLAY and stable_info[0] not in ("None", "Unknown"):
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

def is_allwinner_h313_h616(profile=None):
    """Checks if running specifically on Allwinner H313/H616 (Cortex-A53 / low-power XR819 Wi-Fi)."""
    if profile:
        soc = str(profile.get("soc_platform", "")).lower()
        model = str(profile.get("cpu", {}).get("model", "")).lower()
        if "allwinner" in soc or "sunxi" in soc or "h313" in soc or "h616" in soc:
            return True
        if "cortex-a53" in model and profile.get("cpu", {}).get("cores", 0) <= 4:
            return True
    try:
        if os.path.exists("/proc/device-tree/compatible"):
            with open("/proc/device-tree/compatible", "r") as f:
                compat = f.read().lower()
                if "allwinner" in compat or "sun50i" in compat or "x96q" in compat:
                    return True
    except Exception:
        pass
    try:
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r") as f:
                info = f.read().lower()
                if "sunxi" in info or "allwinner" in info:
                    return True
    except Exception:
        pass
    return False

def check_display_audio_support() -> tuple[bool, str]:
    """
    Universal audio capability check for any display connected via HDMI, DisplayPort (DP/eDP), or DVI.
    Compatible across ALL CPU architectures (x86_64, ARM64, ARMv7, MIPS, RISC-V) and GPU drivers
    (Intel i915, AMDGPU, Nouveau/Nvidia, VC4/RaspberryPi, Allwinner Cedrus/DE, Rockchip, Panfrost).
    Returns (has_audio: bool, reason: str).
    """
    # 1. Primary check: Universal DRM Connector & EDID scan
    has_connected_display = False
    for status_file in sorted(glob.glob("/sys/class/drm/card*-*/status")):
        try:
            with open(status_file, "r") as f:
                if f.read().strip() != "connected":
                    continue
            conn_dir = os.path.dirname(status_file)
            conn_name = os.path.basename(conn_dir)
            if "writeback" in conn_name.lower():
                continue
            has_connected_display = True

            edid_file = os.path.join(conn_dir, "edid")
            if os.path.isfile(edid_file):
                with open(edid_file, "rb") as f:
                    edid = f.read()
                # Check valid EDID header (00 FF FF FF FF FF FF 00)
                if len(edid) >= 256 and edid[:8] == b"\x00\xff\xff\xff\xff\xff\xff\x00":
                    ext_blocks = edid[126]
                    for i in range(1, ext_blocks + 1):
                        block = edid[i * 128 : (i + 1) * 128]
                        if len(block) == 128 and block[0] == 0x02:  # CTA/CEA-861 Extension
                            # Byte 3 Bit 6 = Basic Audio Support flag
                            basic_audio = bool(block[3] & 0x40)
                            if basic_audio:
                                return True, f"DRM {conn_name} CEA-861 Basic Audio bit bật"
                            dtd_start = block[2]
                            offset = 4
                            while offset < dtd_start and offset < 128:
                                header = block[offset]
                                tag = (header >> 5) & 0x07
                                length = header & 0x1F
                                if tag == 1 and length > 0:  # Audio Data Block with SADs
                                    return True, f"DRM {conn_name} CEA-861 Audio Data Block ({length // 3} SADs)"
                                offset += 1 + length
                    return False, f"DRM {conn_name} có CEA-861 nhưng không có bộ giải mã âm thanh"
        except Exception:
            pass

    # 2. Secondary check: Universal ALSA ELD (EDID-Like Data) scan for HDMI / DisplayPort codecs
    for eld_path in sorted(glob.glob("/proc/asound/**/eld*", recursive=True)):
        try:
            with open(eld_path, "r", errors="ignore") as f:
                content = f.read()
            if any(k in content for k in ("HDMI", "DisplayPort", "DP")):
                if "eld_valid" in content and re.search(r"eld_valid\s+0", content):
                    continue
                m = re.search(r"sad_count\s+(\d+)", content)
                if m:
                    sad = int(m.group(1))
                    if sad > 0:
                        return True, f"ALSA ELD ({os.path.basename(eld_path)}) sad_count={sad}"
                    else:
                        return False, f"ALSA ELD ({os.path.basename(eld_path)}) sad_count=0 (không có loa)"
        except Exception:
            pass

    if not has_connected_display:
        return False, "Không phát hiện màn hình kết nối qua cổng đồ họa số (HDMI/DP)"

    return False, "Màn hình kết nối không hỗ trợ âm thanh số"

# Backward compatibility alias
check_hdmi_audio_support = check_display_audio_support

def main():
    global CURRENT_PROC, CURRENT_DISPLAY, CURRENT_NET_TYPE, CURRENT_WIFI_GUI_ACTIVE
    os.environ['DISPLAY'] = ':0'
    try:
        if os.path.exists("/tmp/airplay_streaming"):
            os.remove("/tmp/airplay_streaming")
    except OSError:
        pass

    # Clear root screen and initialize DPMS (enabled, display active at boot)
    subprocess.run('DISPLAY=:0 xsetroot -solid "#000000"', shell=True)
    subprocess.run('DISPLAY=:0 xset +dpms 2>/dev/null', shell=True)
    subprocess.run('DISPLAY=:0 xset s off s noblank 2>/dev/null', shell=True)
    subprocess.run('DISPLAY=:0 xset dpms force on 2>/dev/null', shell=True)
    
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
    has_audio_init, _ = check_hdmi_audio_support()
    CURRENT_DISPLAY = (monitor_name, res, rate, has_audio_init)
    subprocess.run('DISPLAY=:0 feh --no-fehbg --bg-fill /opt/airplay/standby.png 2>/dev/null', shell=True)

    # Start background watcher threads
    window_watcher()
    hotplug_and_network_watcher()
    threading.Thread(target=display_power_manager, daemon=True, name="DisplayPowerManager").start()

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
        has_audio, audio_reason = check_hdmi_audio_support()
        CURRENT_DISPLAY = (monitor_name, res, rate, has_audio)

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
            # Use avdec_h264 (NEON ARM assembly, 203.9 FPS @ 16% CPU) to prevent NV12_4L4 software de-tiling
            decoder = profile.get("decoder", "avdec_h264")
            if decoder == "v4l2slh264dec":
                decoder = "avdec_h264"
            raw_sink = profile.get("video_sink", "autovideosink")
            video_sink = "autovideosink" if raw_sink in ("ximagesink", "", None) else raw_sink
            print(f"[Kiosk] Benchmark Profile active: {sp.get('tier', 'Custom')} -> Stream: {target_res}@{target_fps}fps (H.265: {target_h265}, Decoder: {decoder}, Sink: {video_sink})")
        else:
            print(f"[Kiosk] No benchmark profile found, using default: {target_res}@{target_fps}fps")

        # Determine if running specifically on Allwinner H313/H616 platform
        is_h313_h616 = is_allwinner_h313_h616(profile)
        if is_h313_h616:
            # Match native physical monitor resolution (e.g. 1920x1080 Full HD) for sharp 1:1 display
            target_res = res if (res and res not in ("None", "Unknown")) else sp.get("resolution", "1920x1080")
            stream_fps = int(target_fps) if target_fps else 60
            # Note: v4l2slh264dec at 1080p causes kernel CMA memory pool exhaustion and drops 60% frames.
            # avdec_h264 (ARM NEON multi-threaded assembly) achieves 203.9 FPS with zero drops in native I420.
            decoder = "avdec_h264"
            print(f"[Kiosk] Profile Allwinner H313/H616: Native {target_res}@{stream_fps}fps với bộ giải mã tối ưu NEON {decoder} (Direct I420 xvimagesink, zero-copy, vsync no)")
        else:
            # Generic / higher-end hardware: keep benchmarked framerate and configurations
            target_res = res if (res and res not in ("None", "Unknown")) else sp.get("resolution", "1920x1080")
            stream_fps = int(target_fps) if target_fps else 60

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

        if decoder == 'v4l2slh264dec':
            extra_flags.extend(['-vd', 'v4l2slh264dec', '-vc', 'none'])
        elif decoder == 'avdec_h264':
            extra_flags.extend(['-vd', 'avdec_h264', '-vc', 'none'])
        elif decoder and decoder not in ('avdec_h264', 'avdec_h265'):
            extra_flags.extend(['-vd', decoder])

        # Ensure xvimagesink has qos=false and max-lateness=-1 to eliminate latency drops
        if "xvimagesink" in video_sink:
            if "qos=false" not in video_sink:
                video_sink = video_sink.replace("xvimagesink", "xvimagesink qos=false")
            if "max-lateness" not in video_sink:
                video_sink = video_sink.replace("xvimagesink", "xvimagesink max-lateness=-1")

        # Zero-latency live mirroring mode, persistent client whitelist & PIN prompt
        extra_flags.extend([
            '-pin',
            '-reg', '/opt/airplay/registered_clients.txt'
        ])

        # Check if connected digital display (HDMI/DisplayPort) has audio capability
        if not has_audio:
            print(f"[Kiosk] Display Audio Check: Thiết bị '{monitor_name}' KHÔNG có loa/âm thanh ({audio_reason}). Tự động tắt quảng bá Audio (-a) để thiết bị phát giữ nguyên âm thanh loa máy tính!")
            extra_flags.append('-a')
        else:
            print(f"[Kiosk] Display Audio Check: Thiết bị '{monitor_name}' CÓ hỗ trợ âm thanh số HDMI/DP ({audio_reason}). Bật tính năng Audio AirPlay.")

        cmd = [
            'stdbuf', '-oL', '-eL',
            'uxplay',
            '-nh',
            '-n', monitor_name,
            '-fs',
            '-p',
            '-s', f'{target_res}@{stream_fps}',
            '-fps', str(stream_fps),
            '-reset', '3',
            '-nofreeze',
            '-vsync', 'no',
            '-FPSdata',
            '-vs', video_sink
        ] + extra_flags

        print(f"[Kiosk] Starting UxPlay as '{monitor_name}' with {target_res}@{target_fps}Hz (Monitor: {res}@{rate}Hz, standard ports -p, smooth clock-synced)...")
        with open("/tmp/uxplay.log", "a") as ux_log:
            ux_log.write(f"\n--- [Kiosk] UxPlay Starting at {time.strftime('%Y-%m-%d %H:%M:%S')} (cmd: {' '.join(cmd)}) ---\n")
            ux_log.flush()

        with STATE_LOCK:
            CURRENT_PROC = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

        mon_t = threading.Thread(target=monitor_uxplay_output, args=(CURRENT_PROC,), daemon=True)
        mon_t.start()

        start_time = time.time()
        # Block until UxPlay exits (either closed, crashed, or terminated by hotplug watcher)
        ret = CURRENT_PROC.wait()
        print(f"[Kiosk] UxPlay exited with code {ret} after {time.time() - start_time:.1f}s")
        
        # When UxPlay exits, ensure inputs and UI are restored
        on_stream_ended()

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
