import os, sys, time, subprocess, re, signal, threading, glob, json, socket, struct, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if not os.environ.get("DISPLAY") and (os.path.exists("/tmp/.X11-unix/X0") or os.path.exists("/dev/dri/card0")):
    os.environ["DISPLAY"] = ":0"
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

import ipaddress

LAST_CLIENT_IP = None
CLIENT_NAME_CACHE = {}
IP_TO_MAC_CACHE = {}
MAC_TO_IPS_CACHE = {}
CACHE_LOCK = threading.Lock()

def load_env_config():
    """
    Loads configuration from /opt/wyseplay/.env or /opt/airplay/.env.
    Supports comments (#), quotes, and case-insensitive boolean values.
    """
    env_paths = ["/opt/wyseplay/.env", "/opt/airplay/.env"]
    config = {
        "ENABLE_LOGS": False,
        "DEBUG_VERBOSE": False,
    }
    for p in env_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k == "ENABLE_LOGS":
                                config["ENABLE_LOGS"] = v.lower() in ("true", "1", "yes", "on")
                            elif k == "DEBUG_VERBOSE":
                                config["DEBUG_VERBOSE"] = v.lower() in ("true", "1", "yes", "on")
                            else:
                                config[k] = v
                break
            except Exception as e:
                print(f"[Kiosk] Warning: Failed to read {p}: {e}")
    return config

def purge_old_logs():
    """
    Purges all old runtime log files when logging is disabled.
    Protects RAM and ensures clean state.
    """
    targets = [
        "/tmp/uxplay.log",
        "/tmp/kiosk.log",
        "/tmp/wyseplay.log",
        "/tmp/wyseplay_err.log"
    ]
    for target in targets:
        try:
            if os.path.exists(target):
                os.remove(target)
        except OSError:
            pass

def normalize_ip(ip_str):
    if not ip_str:
        return None
    raw = str(ip_str).split("%")[0].strip()
    try:
        return str(ipaddress.ip_address(raw))
    except Exception:
        return raw.lower()

def decode_avahi_name(srv_name):
    raw = bytearray()
    i = 0
    while i < len(srv_name):
        if srv_name[i] == "\\" and i + 3 < len(srv_name) and srv_name[i+1:i+4].isdigit():
            raw.append(int(srv_name[i+1:i+4], 10))
            i += 4
        else:
            raw.extend(srv_name[i].encode("utf-8"))
            i += 1
    return raw.decode("utf-8", errors="replace").strip()

def update_client_cache(key, name):
    if not key or not name:
        return
    clean_k = normalize_ip(key) if (":" in str(key) and len(str(key)) > 17 or "." in str(key)) else str(key).strip().lower()
    with CACHE_LOCK:
        CLIENT_NAME_CACHE[clean_k] = name

def get_cached_name(key):
    if not key:
        return None
    clean_k = normalize_ip(key) if (":" in str(key) and len(str(key)) > 17 or "." in str(key)) else str(key).strip().lower()
    with CACHE_LOCK:
        return CLIENT_NAME_CACHE.get(clean_k)

def discover_network_airplay_clients():
    """
    Scans mDNS _companion-link._tcp and _airplay._tcp plus ARP/NDP cache
    to map Apple client device names to their IPs and MAC addresses.
    """
    try:
        out = subprocess.check_output(["ip", "neigh"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            p = line.split()
            if len(p) >= 5:
                nip = normalize_ip(p[0])
                nmac = p[4].lower()
                if nip and nmac and ":" in nmac:
                    with CACHE_LOCK:
                        IP_TO_MAC_CACHE[nip] = nmac
                        MAC_TO_IPS_CACHE.setdefault(nmac, set()).add(nip)
                        cached_mac_name = CLIENT_NAME_CACHE.get(nmac)
                        if cached_mac_name:
                            CLIENT_NAME_CACHE[nip] = cached_mac_name
    except Exception:
        pass

    for srv in ["_companion-link._tcp", "_airplay._tcp"]:
        try:
            cmd = ["avahi-browse", "-r", "-t", "-p", srv]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=2.5)
            for line in out.splitlines():
                fields = line.split(";")
                if len(fields) >= 8 and fields[0] == "=":
                    srv_name = decode_avahi_name(fields[3])
                    srv_ip = normalize_ip(fields[7])
                    if srv_ip and srv_name:
                        with CACHE_LOCK:
                            CLIENT_NAME_CACHE[srv_ip] = srv_name
                            mac = IP_TO_MAC_CACHE.get(srv_ip)
                            if mac:
                                CLIENT_NAME_CACHE[mac] = srv_name
                                for sib in MAC_TO_IPS_CACHE.get(mac, set()):
                                    CLIENT_NAME_CACHE[sib] = srv_name
                    if len(fields) >= 10:
                        txt = fields[9]
                        for item in txt.split():
                            if "deviceid=" in item.lower():
                                devid = item.split("=")[1].replace('"', '').strip().lower()
                                with CACHE_LOCK:
                                    CLIENT_NAME_CACHE[devid] = srv_name
        except Exception:
            pass

def resolve_device_name(target_ip_str=None):
    """
    Resolves client IP (IPv4 or IPv6 link-local) to human-readable Apple device name.
    Checks memory cache, ARP/NDP mappings, on-demand mDNS scan, and avahi-resolve.
    """
    global LAST_CLIENT_IP
    if not target_ip_str:
        target_ip_str = LAST_CLIENT_IP
    if not target_ip_str:
        return None

    norm_ip = normalize_ip(target_ip_str)

    # 1. Direct cache lookup by normalized IP
    name = get_cached_name(norm_ip)
    if name:
        return name

    # 2. Cache lookup via MAC address
    with CACHE_LOCK:
        mac = IP_TO_MAC_CACHE.get(norm_ip)
        if mac:
            name = CLIENT_NAME_CACHE.get(mac)
            if name:
                return name

    # 3. On-demand network discovery
    discover_network_airplay_clients()

    # Check cache again post-discovery
    name = get_cached_name(norm_ip)
    if name:
        return name

    with CACHE_LOCK:
        mac = IP_TO_MAC_CACHE.get(norm_ip)
        if mac:
            name = CLIENT_NAME_CACHE.get(mac)
            if name:
                return name

    # 4. Fallback: avahi-resolve reverse lookup
    try:
        res = subprocess.check_output(["avahi-resolve", "-a", norm_ip], text=True, stderr=subprocess.DEVNULL, timeout=1.0).strip()
        if res:
            host = res.split()[-1].replace(".local", "").replace("-", " ").strip()
            if host:
                update_client_cache(norm_ip, host)
                return host
    except Exception:
        pass

    return None

def periodic_client_discovery():
    """Continuously refreshes Apple device name cache every 10 seconds."""
    while True:
        try:
            discover_network_airplay_clients()
        except Exception:
            pass
        time.sleep(10.0)

threading.Thread(target=periodic_client_discovery, daemon=True).start()

def get_active_network_info():
    """Detects active IPv4 address, broadcast address, MAC address, and hostname."""
    ip = "192.168.2.97"
    bcast = "192.168.2.255"
    mac = "12:00:d5:21:8e:c0"
    hostname = "x96q.local."
    try:
        r = subprocess.check_output("ip -o -4 addr show", shell=True, text=True)
        for line in r.strip().splitlines():
            parts = line.split()
            if "scope global" in line:
                iface = parts[1]
                ip_cidr = parts[3]
                cur_ip = ip_cidr.split("/")[0]
                cur_bcast = None
                if "brd" in parts:
                    idx = parts.index("brd")
                    cur_bcast = parts[idx + 1]
                if cur_ip:
                    ip = cur_ip
                if cur_bcast:
                    bcast = cur_bcast
                try:
                    with open(f"/sys/class/net/{iface}/address") as f:
                        cur_mac = f.read().strip()
                        if cur_mac:
                            mac = cur_mac
                except Exception:
                    pass
                break
    except Exception:
        pass
    try:
        h = socket.gethostname()
        if h:
            hostname = f"{h.strip()}.local."
    except Exception:
        pass
    return ip, bcast, mac, hostname

def get_server_public_key():
    """Extracts Ed25519 public key hex from server.pem or fallback."""
    pem_path = "/opt/airplay/server.pem"
    if os.path.exists(pem_path):
        try:
            cmd = f"openssl pkey -in {pem_path} -pubout -outform DER 2>/dev/null"
            out = subprocess.check_output(cmd, shell=True)
            if len(out) >= 32:
                return out[-32:].hex()
        except Exception:
            pass
    return "a130efa531a109bccb8d1483f26227bacc6b2df48eaaa7c05804f5a89c6c1d17"

def encode_dns_name(name):
    parts = name.strip('.').split('.')
    encoded = b''
    for p in parts:
        b = p.encode('utf-8')
        encoded += bytes([len(b)]) + b
    return encoded + b'\x00'

def encode_dns_txt(txt_list):
    res = b''
    for item in txt_list:
        b = item.encode('utf-8')
        res += bytes([len(b)]) + b
    return res

def build_airplay_mdns_packet(ip, bcast, mac, hostname, monitor_name="P27FBA-RAGL"):
    mac_clean = mac.replace(":", "").upper()
    mac_colon = mac.lower()
    raop_name = f"{mac_clean}@{monitor_name}"
    pk = get_server_public_key()
    
    airplay_service = "_airplay._tcp.local."
    raop_service = "_raop._tcp.local."
    airplay_instance = f"{monitor_name}._airplay._tcp.local."
    raop_instance = f"{raop_name}._raop._tcp.local."

    airplay_txt = [
        f"deviceid={mac_colon}",
        "features=0x527FFEE6,0x0",
        "flags=0x204",
        "model=AppleTV3,2",
        f"pk={pk}",
        "pw=false",
        "srcvers=220.68",
        "vv=2",
        "pi=2e388006-13ba-4041-9a67-25dd4a43d536"
    ]

    raop_txt = [
        "ch=2", "cn=0,1,2,3", "da=true", "et=0,3,5", "vv=2",
        "ft=0x527FFEE6,0x0", "am=AppleTV3,2", "md=0,1,2", "rhd=5.6.0.0",
        "pw=false", "sr=44100", "ss=16", "sv=false", "tp=UDP", "txtvers=1",
        "sf=0x204", "vs=220.68", "vn=65537",
        f"pk={pk}",
        "pi=2e388006-13ba-4041-9a67-25dd4a43d536"
    ]

    # DNS Header: ID=0, Flags=0x8400 (Response, Authoritative), Questions=0, Answers=2, Authority=0, Additional=5
    header = struct.pack("!HHHHHH", 0, 0x8400, 0, 2, 0, 5)
    ttl = 120 # 120 seconds

    # 1. PTR _airplay._tcp.local -> airplay_instance
    ans1_name = encode_dns_name(airplay_service)
    ans1_rdata = encode_dns_name(airplay_instance)
    ans1 = ans1_name + struct.pack("!HHIH", 12, 1, ttl, len(ans1_rdata)) + ans1_rdata

    # 2. PTR _raop._tcp.local -> raop_instance
    ans2_name = encode_dns_name(raop_service)
    ans2_rdata = encode_dns_name(raop_instance)
    ans2 = ans2_name + struct.pack("!HHIH", 12, 1, ttl, len(ans2_rdata)) + ans2_rdata

    # Additional 1: SRV airplay_instance -> port 7000, target hostname
    add1_name = encode_dns_name(airplay_instance)
    target_encoded = encode_dns_name(hostname)
    add1_rdata = struct.pack("!HHH", 0, 0, 7000) + target_encoded
    add1 = add1_name + struct.pack("!HHIH", 33, 0x8001, ttl, len(add1_rdata)) + add1_rdata

    # Additional 2: TXT airplay_instance
    add2_name = encode_dns_name(airplay_instance)
    add2_rdata = encode_dns_txt(airplay_txt)
    add2 = add2_name + struct.pack("!HHIH", 16, 0x8001, ttl, len(add2_rdata)) + add2_rdata

    # Additional 3: SRV raop_instance -> port 7000, target hostname
    add3_name = encode_dns_name(raop_instance)
    add3_rdata = struct.pack("!HHH", 0, 0, 7000) + target_encoded
    add3 = add3_name + struct.pack("!HHIH", 33, 0x8001, ttl, len(add3_rdata)) + add3_rdata

    # Additional 4: TXT raop_instance
    add4_name = encode_dns_name(raop_instance)
    add4_rdata = encode_dns_txt(raop_txt)
    add4 = add4_name + struct.pack("!HHIH", 16, 0x8001, ttl, len(add4_rdata)) + add4_rdata

    # Additional 5: A hostname -> IP
    add5_name = encode_dns_name(hostname)
    add5_rdata = socket.inet_aton(ip)
    add5 = add5_name + struct.pack("!HHIH", 1, 0x8001, ttl, len(add5_rdata)) + add5_rdata

    return header + ans1 + ans2 + add1 + add2 + add3 + add4 + add5

def autonomous_airplay_announcer():
    """
    Autonomous Bonjour/mDNS Announcer running 100% on the TV Box.
    Broadcasts unsolicited mDNS responses to both 224.0.0.251:5353 and subnet broadcast.
    Also listens for active client queries on port 5353 for instant 0ms response.
    Guarantees permanent visibility in macOS Screen Mirroring menu without any software on Mac.
    """
    sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def _query_listener():
        try:
            s_listen = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass
            s_listen.bind(('', 5353))
            mreq = struct.pack('4sl', socket.inet_aton('224.0.0.251'), socket.INADDR_ANY)
            s_listen.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            while True:
                data, addr = s_listen.recvfrom(2048)
                if b'_airplay' in data or b'_raop' in data:
                    cur_name = CURRENT_DISPLAY[0] if CURRENT_DISPLAY else "P27FBA-RAGL"
                    ip, bcast, mac, hostname = get_active_network_info()
                    pkt = build_airplay_mdns_packet(ip, bcast, mac, hostname, cur_name)
                    sock_send.sendto(pkt, ("224.0.0.251", 5353))
                    if bcast:
                        sock_send.sendto(pkt, (bcast, 5353))
                    if addr[0] != "127.0.0.1" and addr[0] != ip:
                        try:
                            sock_send.sendto(pkt, addr)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[Kiosk] mDNS query listener stopped: {e}", flush=True)

    threading.Thread(target=_query_listener, daemon=True, name="mDNSQueryListener").start()
    print("[Kiosk] Autonomous AirPlay mDNS Announcer & Query Responder started on TV Box.")

    while True:
        try:
            cur_name = CURRENT_DISPLAY[0] if CURRENT_DISPLAY else "P27FBA-RAGL"
            ip, bcast, mac, hostname = get_active_network_info()
            pkt = build_airplay_mdns_packet(ip, bcast, mac, hostname, cur_name)
            sock_send.sendto(pkt, ("224.0.0.251", 5353))
            if bcast:
                sock_send.sendto(pkt, (bcast, 5353))
        except Exception:
            pass
        time.sleep(2.5)

def is_monitor_asleep():
    global MONITOR_ASLEEP
    disp = os.environ.get("DISPLAY", ":0")
    if os.path.exists("/tmp/.X11-unix/X0") or os.environ.get("DISPLAY"):
        try:
            out = subprocess.check_output(f"DISPLAY={disp} xset q 2>/dev/null", shell=True).decode()
            if "Monitor is Off" in out:
                MONITOR_ASLEEP = True
                return True
            elif "Monitor is On" in out:
                MONITOR_ASLEEP = False
                return False
        except Exception:
            pass
    return MONITOR_ASLEEP

def wake_display(reason="Activity"):
    global LAST_ACTIVITY, MONITOR_ASLEEP
    LAST_ACTIVITY = time.time()
    disp = os.environ.get("DISPLAY", ":0")
    if MONITOR_ASLEEP or is_monitor_asleep():
        MONITOR_ASLEEP = False
        subprocess.run('echo 0 | sudo tee /sys/class/graphics/fb0/blank >/dev/null 2>&1 || true', shell=True)
        subprocess.run(f'DISPLAY={disp} xset +dpms s off s noblank 2>/dev/null', shell=True)
        subprocess.run(f'DISPLAY={disp} xset dpms force on 2>/dev/null', shell=True)
        if not CURRENT_LOCKED:
            apply_standby_wallpaper()
        print(f"[Kiosk] Display WOKEN UP ({reason}): Monitor panel & backlight ON.")

def sleep_display():
    global MONITOR_ASLEEP
    with STATE_LOCK:
        if is_monitor_asleep():
            MONITOR_ASLEEP = True
            return
        if CURRENT_LOCKED:
            return
        if os.path.exists("/tmp/airplay_pin.txt"):
            return
        MONITOR_ASLEEP = True
        subprocess.run('echo 1 | sudo tee /sys/class/graphics/fb0/blank >/dev/null 2>&1 || true', shell=True)
        disp = os.environ.get("DISPLAY", ":0")
        subprocess.run(f'DISPLAY={disp} xset +dpms 2>/dev/null', shell=True)
        subprocess.run(f'DISPLAY={disp} xset dpms force off 2>/dev/null', shell=True)
        print("[Kiosk] Idle 30s: Display entered DPMS SLEEP (monitor panel & backlight OFF).")

def apply_standby_wallpaper():
    base_p = "/opt/airplay/standby.png"
    if not os.path.exists(base_p) or os.path.getsize(base_p) == 0:
        try:
            make_wallpaper.generate_wallpaper(wait_sync=False)
        except Exception as e:
            print(f"[Kiosk] Error generating missing standby wallpaper: {e}", flush=True)

    try:
        if os.path.exists("/dev/fb0"):
            from PIL import Image
            if os.path.exists(base_p):
                img = Image.open(base_p).convert("RGB")
                fb_w, fb_h = 1920, 1080
                try:
                    with open("/sys/class/graphics/fb0/virtual_size", "r") as vsf:
                        vp = vsf.read().strip().split(",")
                        fb_w, fb_h = int(vp[0]), int(vp[1])
                except Exception:
                    pass
                if img.size != (fb_w, fb_h):
                    img = img.resize((fb_w, fb_h), Image.Resampling.BILINEAR)
                raw = img.tobytes("raw", "BGRX")
                with open("/dev/fb0", "wb") as fb:
                    fb.write(raw)
    except Exception as e:
        print(f"[Kiosk] Error applying fb0 wallpaper: {e}", flush=True)

    disp = os.environ.get("DISPLAY", ":0")
    if os.path.exists("/tmp/.X11-unix/X0") or os.environ.get("DISPLAY"):
        subprocess.run(f'DISPLAY={disp} feh --no-fehbg --bg-fill {base_p} 2>/dev/null', shell=True)

def render_pin_modal_fb0(pin, client_name=None):
    if not os.path.exists("/dev/fb0"):
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
        base_path = "/opt/airplay/standby.png"
        if os.path.exists(base_path):
            img = Image.open(base_path).convert("RGBA")
        else:
            img = Image.new("RGBA", (1920, 1080), (10, 10, 12, 255))
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 190))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        w, h = img.size
        card_w, card_h = int(w * 0.45), int(h * 0.42)
        cx, cy = w // 2, h // 2
        card_box = [cx - card_w // 2, cy - card_h // 2, cx + card_w // 2, cy + card_h // 2]
        draw.rounded_rectangle(card_box, radius=24, fill=(28, 28, 30, 245), outline=(68, 68, 70), width=2)

        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path):
            font_path = "/opt/airplay/fonts/SF-Pro-Display-Bold.otf"
        if not os.path.exists(font_path):
            font_path = None
        try:
            f_title = ImageFont.truetype(font_path, int(h * 0.035)) if font_path else ImageFont.load_default()
            f_pin = ImageFont.truetype(font_path, int(h * 0.11)) if font_path else ImageFont.load_default()
            f_sub = ImageFont.truetype(font_path, int(h * 0.024)) if font_path else ImageFont.load_default()
        except Exception:
            f_title = f_pin = f_sub = ImageFont.load_default()

        draw.text((cx, cy - card_h // 2 + int(card_h * 0.20)), "Mã xác thực AirPlay (PIN)", fill="#FFFFFF", font=f_title, anchor="mm")
        draw.text((cx, cy + int(card_h * 0.02)), "  ".join(str(pin)), fill="#34C759", font=f_pin, anchor="mm")
        sub_text = f"Thiết bị: {client_name}" if client_name else "Nhập mã số này trên thiết bị Apple của bạn"
        draw.text((cx, cy + card_h // 2 - int(card_h * 0.20)), sub_text, fill="#8E8E93", font=f_sub, anchor="mm")

        raw = img.convert("RGB").tobytes("raw", "BGRX")
        with open("/dev/fb0", "wb") as fb:
            fb.write(raw)
    except Exception as e:
        print(f"[Kiosk] Error rendering PIN modal to fb0: {e}", flush=True)

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
        if not os.environ.get("DISPLAY"):
            try:
                import select
                if os.path.exists("/dev/input/mice"):
                    with open("/dev/input/mice", "rb") as f_m:
                        r, _, _ = select.select([f_m], [], [], 0.0)
                        if r:
                            f_m.read(3)
                            wake_display(reason="Mouse movement")
            except Exception:
                pass
        else:
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
            if MONITOR_ASLEEP or is_monitor_asleep():
                wake_display(reason="AirPlay streaming or PIN modal active")
            continue

        # 3. Check 30s idle timeout
        if not is_monitor_asleep():
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
        subprocess.run('DISPLAY=:0 xset +dpms s off s noblank 2>/dev/null', shell=True)
        print("[Kiosk] AirPlay stream started: Woke up monitor, kept screen awake & hid mouse.")

def on_stream_ended():
    global CURRENT_LOCKED
    with STATE_LOCK:
        if not CURRENT_LOCKED:
            apply_standby_wallpaper()
            return
        CURRENT_LOCKED = False
        try:
            if os.path.exists("/tmp/airplay_streaming"):
                os.remove("/tmp/airplay_streaming")
        except OSError:
            pass
        disp = os.environ.get("DISPLAY", ":0")
        subprocess.run(f"DISPLAY={disp} xdotool search --class WifiKiosk windowmap 2>/dev/null", shell=True)
        subprocess.run(f'DISPLAY={disp} xsetroot -cursor_name left_ptr 2>/dev/null', shell=True)
        subprocess.run(f'DISPLAY={disp} xset +dpms s off s noblank 2>/dev/null', shell=True)
        subprocess.run(f'DISPLAY={disp} xset dpms force on 2>/dev/null', shell=True)
        apply_standby_wallpaper()
        wake_display(reason="AirPlay stream ended, standby restored")
        print("[Kiosk] AirPlay stream ended: Restored standby wallpaper (30s sleep timer started).")

def monitor_uxplay_output(proc):
    """
    Reads UxPlay stdout line-by-line in real time.
    Detects stream start, PIN prompts, and end events with 0ms delay.
    If ENABLE_LOGS is True in /opt/wyseplay/.env, writes to /tmp/uxplay.log (capped at ~2MB).
    If ENABLE_LOGS is False, no log is written and any existing logs are purged.
    """
    global LAST_CLIENT_IP
    log_file = "/tmp/uxplay.log"
    env_cfg = load_env_config()
    enable_logs = env_cfg.get("ENABLE_LOGS", False)

    ux_log = None
    if enable_logs:
        try:
            if os.path.exists(log_file) and os.path.getsize(log_file) > 2097152:
                with open(log_file, "r", errors="ignore") as f:
                    tail_lines = f.readlines()[-1000:]
                with open(log_file, "w") as f:
                    f.writelines(tail_lines)
            ux_log = open(log_file, "a")
        except Exception:
            ux_log = None
    else:
        purge_old_logs()

    line_count = 0
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break

            # Dynamic check every 500 lines
            line_count += 1
            if line_count >= 500:
                line_count = 0
                env_cfg = load_env_config()
                new_enable_logs = env_cfg.get("ENABLE_LOGS", False)
                if new_enable_logs != enable_logs:
                    enable_logs = new_enable_logs
                    if not enable_logs:
                        if ux_log:
                            try:
                                ux_log.close()
                            except Exception:
                                pass
                            ux_log = None
                        purge_old_logs()
                    else:
                        try:
                            ux_log = open(log_file, "a")
                        except Exception:
                            ux_log = None
                elif enable_logs and ux_log:
                    try:
                        if os.path.getsize(log_file) > 2097152:
                            ux_log.close()
                            with open(log_file, "r", errors="ignore") as f:
                                tail_lines = f.readlines()[-1000:]
                            with open(log_file, "w") as f:
                                f.writelines(tail_lines)
                            ux_log = open(log_file, "a")
                    except Exception:
                        pass

            if ux_log and enable_logs:
                ux_log.write(line)
                ux_log.flush()

                # 1. Wake display instantly upon any incoming client connection request
                if (
                    "Accepted IPv" in line
                    or "connection request from" in line
                    or "PAIR-PIN-START" in line
                ):
                    wake_display(reason="Incoming AirPlay connection")

                # Track client remote IP
                m_remote = re.search(r'Remote:\s+([^\s]+)', line)
                if m_remote:
                    LAST_CLIENT_IP = m_remote.group(1).strip()

                # Track client name from connection requests & registrations
                m_req = re.search(r'connection request from (.+) \((.+)\) with deviceID = (.+)', line)
                if m_req:
                    c_name = m_req.group(1).strip()
                    c_devid = m_req.group(3).strip()
                    update_client_cache(c_devid, c_name)
                    if LAST_CLIENT_IP:
                        update_client_cache(LAST_CLIENT_IP, c_name)

                m_reg = re.search(r'registered new client: (.+) DeviceID = (.+) PK =', line)
                if m_reg:
                    c_name = m_reg.group(1).strip()
                    c_devid = m_reg.group(2).strip()
                    update_client_cache(c_devid, c_name)
                    if LAST_CLIENT_IP:
                        update_client_cache(LAST_CLIENT_IP, c_name)
                    try:
                        if os.path.exists("/tmp/airplay_pin.txt"):
                            os.remove("/tmp/airplay_pin.txt")
                    except Exception:
                        pass

                # 2. Track AirPlay PIN authentication requests and display OTP modal
                m = re.search(r'(?:\*\*\* CLIENT (?:\[(.*?)\] )?MUST NOW ENTER PIN = "(\d{4})")', line)
                if m:
                    client_ip_in_line = m.group(1)
                    pin_code = m.group(2)
                    ip_to_resolve = client_ip_in_line or LAST_CLIENT_IP
                    wake_display(reason=f"PIN OTP required: {pin_code}")

                    def _write_pin_file(pin, cname=None):
                        try:
                            with open("/tmp/airplay_pin.txt", "w") as pf:
                                if cname:
                                    pf.write(f"{pin}\n{cname}\n")
                                else:
                                    pf.write(f"{pin}\n")
                        except Exception:
                            pass
                        render_pin_modal_fb0(pin, cname)

                    dev_name = resolve_device_name(ip_to_resolve)
                    _write_pin_file(pin_code, dev_name)
                    print(f"[Kiosk] PIN Passcode generated: {pin_code} (Device: {dev_name}). Displaying OTP modal on screen.")

                    if not dev_name:
                        def _bg_resolve_pin(p_code, p_ip):
                            for _ in range(6):
                                time.sleep(0.5)
                                if not os.path.exists("/tmp/airplay_pin.txt"):
                                    break
                                resolved = resolve_device_name(p_ip)
                                if resolved:
                                    _write_pin_file(p_code, resolved)
                                    print(f"[Kiosk] Resolved client name asynchronously: '{resolved}'. Updated OTP modal.")
                                    break
                        threading.Thread(target=_bg_resolve_pin, args=(pin_code, ip_to_resolve), daemon=True).start()
                elif "registered new client" in line:
                    try:
                        if os.path.exists("/tmp/airplay_pin.txt"):
                            os.remove("/tmp/airplay_pin.txt")
                            apply_standby_wallpaper()
                    except Exception:
                        pass

                # 3. Stream lifecycle
                if (
                    "raop_rtp_mirror starting mirroring" in line
                    or "Begin streaming to GStreamer video pipeline" in line
                ):
                    try:
                        if os.path.exists("/tmp/airplay_pin.txt"):
                            os.remove("/tmp/airplay_pin.txt")
                    except Exception:
                        pass
                    on_stream_started()
                elif (
                    "Destroying connection" in line
                    or "running is no longer true" in line
                    or "video has finished" in line
                    or "raop_rtp_mirror stopping mirroring" in line
                    or "Stopping mirror audio" in line
                ):
                    try:
                        if os.path.exists("/tmp/airplay_pin.txt"):
                            os.remove("/tmp/airplay_pin.txt")
                    except Exception:
                        pass
                    on_stream_ended()
                    apply_standby_wallpaper()
                    # Keep UxPlay running as a permanent daemon across sessions:
                    # Do not kill UxPlay on disconnect, preventing mDNS flapping and device disappearance on client devices.
    except Exception as e:
        print("[Kiosk] UxPlay monitor error:", e)
    finally:
        if ux_log:
            try:
                ux_log.close()
            except Exception:
                pass

def manage_wifi_gui():
    global WIFI_GUI_PROC, CURRENT_NET_TYPE
    if not os.environ.get("DISPLAY"):
        return
    with STATE_LOCK:
        if CURRENT_NET_TYPE == "NONE":
            if WIFI_GUI_PROC is None or WIFI_GUI_PROC.poll() is not None:
                print("[Kiosk] No network: Launching Wi-Fi Onboarding UI...")
                env = dict(os.environ, DISPLAY=":0")
                WIFI_GUI_PROC = subprocess.Popen(["python3", "-u", "/opt/airplay/wifi_gui.py"], env=env)
        else:
            if WIFI_GUI_PROC is not None and WIFI_GUI_PROC.poll() is None:
                print("[Kiosk] Network active: Terminating Wi-Fi Onboarding UI...")
                try:
                    WIFI_GUI_PROC.terminate()
                    WIFI_GUI_PROC.wait(timeout=1.0)
                except Exception:
                    WIFI_GUI_PROC.kill()
                WIFI_GUI_PROC = None

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
        last_active_iface = None
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
                        # Do not wake up or reconfigure display while in DPMS sleep
                        if is_monitor_asleep():
                            continue
                        time.sleep(1.0)
                        disp = os.environ.get("DISPLAY", ":0")
                        subprocess.run(f'DISPLAY={disp} xrandr --auto', shell=True)
                        time.sleep(0.5)

                        res, rate, name = make_wallpaper.get_display_info()
                        has_audio, _ = check_hdmi_audio_support()
                        new_info = (name, res, rate, has_audio)

                        if CURRENT_DISPLAY is not None and new_info != CURRENT_DISPLAY:
                            time.sleep(1.0)
                            subprocess.run(f'DISPLAY={disp} xrandr --auto', shell=True)
                            time.sleep(0.5)
                            res2, rate2, name2 = make_wallpaper.get_display_info()
                            has_audio2, _ = check_hdmi_audio_support()
                            stable_info = (name2, res2, rate2, has_audio2)

                            if stable_info != CURRENT_DISPLAY and stable_info[0] not in ("None", "Unknown"):
                                restart_uxplay_for_display(stable_info)
                        else:
                            if not CURRENT_LOCKED:
                                apply_standby_wallpaper()
            except Exception as e:
                print("[Hotplug] Check error:", e)

            # 3. Check active network interface changes (e.g. Ethernet cable plugged in or unplugged)
            try:
                r_route = subprocess.check_output("ip route get 1.1.1.1 2>/dev/null", shell=True, text=True)
                m_iface = re.search(r"dev\s+(\S+)", r_route)
                current_iface = m_iface.group(1) if m_iface else None
                if current_iface:
                    if last_active_iface is not None and current_iface != last_active_iface:
                        print(f"[Network] Active interface changed from {last_active_iface} -> {current_iface}!")
                        last_active_iface = current_iface
                        with STATE_LOCK:
                            is_streaming = CURRENT_LOCKED or os.path.exists("/tmp/airplay_streaming")
                        if not is_streaming:
                            stop_uxplay(reason=f"Network interface changed to {current_iface}")
                    elif last_active_iface is None:
                        last_active_iface = current_iface
            except Exception:
                pass

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

    env_cfg = load_env_config()
    if not env_cfg.get("ENABLE_LOGS", False):
        purge_old_logs()
    else:
        print("[Kiosk] Debug logging ENABLED via /opt/wyseplay/.env (ENABLE_LOGS=true)")

    is_x11 = bool(os.environ.get("DISPLAY")) and subprocess.run("pgrep -x Xorg >/dev/null", shell=True).returncode == 0
    if not is_x11 and 'DISPLAY' in os.environ:
        del os.environ['DISPLAY']

    try:
        if os.path.exists("/tmp/airplay_streaming"):
            os.remove("/tmp/airplay_streaming")
    except OSError:
        pass

    if is_x11:
        # Clear root screen and initialize DPMS for X11
        subprocess.run('DISPLAY=:0 xsetroot -solid "#000000" 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset +dpms 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset s off s noblank 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xset dpms force on 2>/dev/null', shell=True)
        subprocess.run('DISPLAY=:0 xrandr --auto 2>/dev/null', shell=True)
    else:
        # Native DRM/KMS Framebuffer initialization (like Android HWComposer)
        subprocess.run('echo 0 | sudo tee /sys/class/graphics/fb0/blank >/dev/null 2>&1 || true', shell=True)
        subprocess.run('modetest -M sun4i-drm -w 49:DPMS:0 >/dev/null 2>&1 || true', shell=True)

    # Ensure inputs are unlocked in standby
    set_inputs(False)
    time.sleep(0.5)

    # Maximize CPU responsiveness for zero-latency decode/render
    subprocess.run('echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor >/dev/null 2>&1 || true', shell=True)

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
    apply_standby_wallpaper()

    # Start background watcher threads
    window_watcher()
    hotplug_and_network_watcher()
    threading.Thread(target=display_power_manager, daemon=True, name="DisplayPowerManager").start()
    threading.Thread(target=discover_network_airplay_clients, daemon=True, name="InitialClientDiscovery").start()
    threading.Thread(target=autonomous_airplay_announcer, daemon=True, name="AutonomousAirPlayAnnouncer").start()

    # Launch or close Wi-Fi GUI based on verified initial network state
    manage_wifi_gui()

    os.environ["LIBGL_DRI3_DISABLE"] = "1"
    hw_fallback_active = False
    sink_fallback_active = False
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
        apply_standby_wallpaper()

        # 2. UxPlay streaming parameters are STRICTLY determined by hardware benchmark profile
        # (Independent of the connected display, preventing downgraded performance from inferior setup monitors)
        profile = load_hardware_profile()
        target_res = "1920x1080"
        target_fps = 60
        target_h265 = False
        decoder = "avdec_h264"
        video_sink = "autovideosink"

        # Check if running in Linux DRM/KMS mode without X11
        is_drm_mode = (not os.environ.get("DISPLAY")) or (os.path.exists("/dev/dri/card0") and subprocess.run("pgrep -x Xorg >/dev/null", shell=True).returncode != 0)

        # Multi-Tier Video Sink Detection:
        # Tier 1: xvimagesink (XVideo Hardware Acceleration - Fast, Native, Zero GL overhead)
        # Tier 2: ximagesink (XShm Shared Memory Software Fallback)
        # Tier 3: autovideosink (GStreamer Automatic Selection)
        has_xv = bool(shutil.which("xvinfo"))

        if is_drm_mode:
            video_sink = "kmssink" if shutil.which("kmssink") else "autovideosink"
            decoder = "v4l2slh264dec"
            print(f"[Kiosk] Direct DRM/KMS mode active: VideoSink={video_sink}, Decoder={decoder}")
        elif profile and "selected_profile" in profile:
            sp = profile["selected_profile"]
            target_res = sp.get("resolution", "1920x1080")
            target_fps = sp.get("max_fps", 60)
            target_h265 = sp.get("h265", False)
            decoder = profile.get("decoder", "avdec_h264")
            video_sink = "xvimagesink" if has_xv else "ximagesink"
            print(f"[Kiosk] Benchmark Profile active: {sp.get('tier', 'Custom')} -> Stream: {target_res}@{target_fps}fps (H.265: {target_h265}, Decoder: {decoder}, Sink: {video_sink})")
        else:
            video_sink = "xvimagesink" if has_xv else "ximagesink"
            print(f"[Kiosk] No benchmark profile found, using default: {target_res}@{target_fps}fps (Sink: {video_sink})")

        # 3. Check user display mode preference (/opt/airplay/display_mode.json or legacy /opt/airplay/x96q_config.json)
        disp_mode_file = "/opt/airplay/display_mode.json"
        legacy_mode_file = "/opt/airplay/x96q_config.json"
        user_disp_cfg = {}
        for cfg_path in (disp_mode_file, legacy_mode_file):
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r") as xf:
                        user_disp_cfg = json.load(xf)
                        break
                except Exception:
                    pass

        disp_mode = user_disp_cfg.get("mode", "")
        disp_res = user_disp_cfg.get("resolution", "")

        if disp_mode == "smooth_720p" or disp_res == "1280x720":
            target_res = "1280x720"
            stream_fps = 60
            print(f"[Kiosk] Chế độ 720p Mượt mà (Smooth): Stream 1280x720@60fps (Hardware upscaled to {res}, tối ưu băng thông chuột 40-60 FPS)")
        elif disp_mode == "sharp_1080p" or disp_res == "1920x1080":
            target_res = "1920x1080"
            stream_fps = 60
            print(f"[Kiosk] Chế độ 1080p Sắc nét (Sharp 1:1): Stream 1920x1080@60fps")
        elif disp_mode == "ultra_4k" or disp_res == "3840x2160":
            target_res = "3840x2160"
            stream_fps = 60
            target_h265 = True
            print(f"[Kiosk] Chế độ 4K Ultra HD: Stream 3840x2160@60fps (H.265)")
        else:
            # Always request full 60 FPS from AirPlay source, never cap in software
            stream_fps = 60
            print(f"[Kiosk] Cấu hình tự động: Stream {target_res}@{stream_fps}fps (Mở tối đa 60 FPS, không khóa FPS bằng code)")

        # 4. Select the optimal decoder for target architecture & resolution
        soc_platform = (profile.get("soc_platform") if profile else "") or ""
        if not soc_platform and is_allwinner_h313_h616(profile):
            soc_platform = "allwinner"

        user_pref_decoder = user_disp_cfg.get("decoder")
        if user_pref_decoder:
            decoder = user_pref_decoder
            print(f"[Kiosk] Ưu tiên cấu hình người dùng: Decoder={decoder}")
        elif soc_platform in ("intel", "amd", "x86_generic"):
            # Intel/AMD x86 (Dell Wyse 3040, Zotac Zbox N3150, Intel NUC, PC Thin Client):
            # Native Hardware Acceleration via Intel Quick Sync Video (VA-API).
            # Decodes 1080p@60 / 4K@30 with 0% CPU memcpy, 0% CPU de-tiling, and < 8% CPU utilization.
            has_vaapi = (subprocess.run("gst-inspect-1.0 vaapih264dec >/dev/null 2>&1", shell=True).returncode == 0)
            if has_vaapi:
                decoder = "vaapih264dec"
                print(f"[Kiosk] Nền tảng {soc_platform.upper()} (x86/x64): Tự động kích hoạt bộ giải mã phần cứng Intel VA-API ({decoder})")
            else:
                decoder = "avdec_h264"
                print(f"[Kiosk] Nền tảng {soc_platform.upper()}: Không tìm thấy plugin VA-API, sử dụng CPU đa luồng ({decoder})")
        elif soc_platform == "allwinner":
            # On Allwinner H313/H616:
            # v4l2slh264dec (Cedrus VPU) provides real-time <30ms decode without TCP buffer bloat.
            if os.path.exists("/dev/video0") and not hw_fallback_active:
                decoder = "v4l2slh264dec"
            else:
                decoder = "avdec_h264"
        elif soc_platform == "raspberrypi":
            if os.path.exists("/dev/video10") or os.path.exists("/dev/video11"):
                decoder = "v4l2h264dec"
            else:
                decoder = "avdec_h264"
        elif disp_mode in ("sharp_1080p",) or target_res == "1920x1080":
            decoder = "avdec_h264"

        # Automatic Fail-Safe: If hardware decoder previously crashed, force CPU decoder
        if hw_fallback_active:
            decoder = "avdec_h264"
            print("[Kiosk] Chế độ Fail-Safe đang bật: Sử dụng bộ giải mã CPU tiêu chuẩn (avdec_h264)")

        if sink_fallback_active:
            video_sink = "ximagesink"
            print("[Kiosk] Chế độ Fail-Safe đang bật: Sử dụng XShm video sink (ximagesink)")

        # Check for 4K / H.265
        extra_flags = []
        try:
            w = int(target_res.split('x')[0])
            if target_h265 or w >= 3840:
                extra_flags.append('-h265')
        except Exception:
            pass

        if decoder == 'v4l2slh264dec':
            extra_flags.extend(['-vd', 'v4l2slh264dec', '-vc', 'capsfilter caps=video/x-raw,format=NV12'])
        elif decoder == 'avdec_h264':
            extra_flags.extend(['-vd', 'avdec_h264 max-threads=4', '-vc', 'none'])
        elif decoder == 'avdec_h265':
            extra_flags.extend(['-vd', 'avdec_h265 max-threads=4', '-vc', 'none'])
        elif decoder and decoder not in ('avdec_h264', 'avdec_h265'):
            extra_flags.extend(['-vd', decoder])

        # Ensure sink options are tuned for zero-latency streaming
        if "glimagesink" in video_sink:
            if "qos=false" not in video_sink:
                video_sink = video_sink.replace("glimagesink", "glimagesink qos=false")
            if "max-lateness" not in video_sink:
                video_sink = video_sink.replace("glimagesink", "glimagesink max-lateness=-1")
            if "enable-last-sample" not in video_sink:
                video_sink += " enable-last-sample=false"
        elif "xvimagesink" in video_sink:
            if "qos=false" not in video_sink:
                video_sink = video_sink.replace("xvimagesink", "xvimagesink qos=false")
            if "max-lateness" not in video_sink:
                video_sink = video_sink.replace("xvimagesink", "xvimagesink max-lateness=-1")
            if "force-aspect-ratio" not in video_sink:
                video_sink += " force-aspect-ratio=false draw-borders=false"
            if "enable-last-sample" not in video_sink:
                video_sink += " enable-last-sample=false"
        elif "ximagesink" in video_sink:
            if "qos=false" not in video_sink:
                video_sink = video_sink.replace("ximagesink", "ximagesink qos=false")
            if "max-lateness" not in video_sink:
                video_sink = video_sink.replace("ximagesink", "ximagesink max-lateness=-1")

        # Zero-latency live mirroring mode, persistent client whitelist & PIN prompt
        extra_flags.extend([
            '-pin',
            '-reg', '/opt/airplay/registered_clients.txt',
            '-key', '/opt/airplay/server.pem'
        ])

        # Ensure MAC address / deviceid matches active interface
        try:
            r_route = subprocess.check_output("ip route get 1.1.1.1 2>/dev/null", shell=True, text=True)
            m_iface = re.search(r"dev\s+(\S+)", r_route)
            if m_iface:
                iface_name = m_iface.group(1)
                with open(f"/sys/class/net/{iface_name}/address") as f_mac:
                    act_mac = f_mac.read().strip()
                    if act_mac:
                        print(f"[Kiosk] Binding UxPlay to active interface '{iface_name}' MAC: {act_mac}")
                        extra_flags.extend(['-m', act_mac])
        except Exception as e:
            print(f"[Kiosk] Warning: Failed to detect active MAC: {e}")


        # AirPlay Screen Mirroring specification requires both _airplay._tcp and _raop._tcp
        # Do not disable audio (-a), as doing so prevents Apple clients from recognizing the display in Screen Mirroring.
        print(f"[Kiosk] AirPlay Screen Mirroring: Advertising both Video (_airplay) and Audio (_raop) as Apple TV target '{monitor_name}'.")

        cmd = [
            'stdbuf', '-oL', '-eL',
            'uxplay',
            '-nh',
            '-n', monitor_name,
            '-nohold',
            '-p',
            '-s', f'{target_res}@{stream_fps}',
            '-fps', str(stream_fps),
            '-reset', '0',
            '-nofreeze',
            '-vsync', 'no',
            '-vs', video_sink
        ]
        if not is_drm_mode and video_sink not in ("kmssink",):
            cmd.append('-fs')
        cmd.extend(extra_flags)

        # Check environment configuration for debug logging
        env_cfg = load_env_config()
        enable_logs = env_cfg.get("ENABLE_LOGS", False)
        debug_verbose = env_cfg.get("DEBUG_VERBOSE", False)

        if enable_logs and debug_verbose:
            cmd.extend(['-FPSdata', '-d'])

        print(f"[Kiosk] Starting UxPlay as '{monitor_name}' with {target_res}@{target_fps}Hz (Monitor: {res}@{rate}Hz, standard ports -p, smooth clock-synced)...")
        if enable_logs:
            try:
                if os.path.exists("/tmp/uxplay.log") and os.path.getsize("/tmp/uxplay.log") > 2097152:
                    with open("/tmp/uxplay.log", "r", errors="ignore") as f:
                        tail_lines = f.readlines()[-1000:]
                    with open("/tmp/uxplay.log", "w") as f:
                        f.writelines(tail_lines)
            except Exception:
                pass

            try:
                with open("/tmp/uxplay.log", "a") as ux_log:
                    ux_log.write(f"\n--- [Kiosk] UxPlay Starting at {time.strftime('%Y-%m-%d %H:%M:%S')} (cmd: {' '.join(cmd)}) ---\n")
                    ux_log.flush()
            except Exception:
                pass
        else:
            purge_old_logs()

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
        apply_standby_wallpaper()

        # Defensive backoff & Fail-Safe Auto-Recovery
        elapsed = time.time() - start_time
        if elapsed < 3.0 and ret != 0:
            consecutive_crashes += 1
            if not is_physical_display_connected():
                continue
            
            # If xvimagesink caused 2 consecutive crashes, automatically fall back to ximagesink
            if consecutive_crashes >= 2 and "xvimagesink" in video_sink and not sink_fallback_active:
                print(f"[Kiosk] CẢNH BÁO: Video sink '{video_sink}' gặp lỗi. Tự động chuyển sang XShm (ximagesink) an toàn!")
                sink_fallback_active = True
                consecutive_crashes = 0
            # If a custom hardware decoder caused 2 consecutive crashes, automatically drop to CPU decoder
            elif consecutive_crashes >= 2 and decoder not in ('avdec_h264', 'avdec_h265') and not hw_fallback_active:
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
