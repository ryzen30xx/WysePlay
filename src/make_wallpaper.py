import os, sys, glob, json, subprocess, time, socket, struct
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
from PIL import Image, ImageDraw, ImageFont

def get_display_info():
    res = "1280x800"
    rate = 60
    monitor_name = "AirPlay Display"
    disp = os.environ.get("DISPLAY", ":0")

    # 1. Parse xrandr for active resolution and refresh rate
    try:
        out = subprocess.check_output(f"DISPLAY={disp} xrandr", shell=True).decode()
        for line in out.splitlines():
            if ' connected' in line:
                m = [p for p in line.split() if 'x' in p and '+' in p]
                if m:
                    res = m[0].split('+')[0]
                continue
            if '*' in line:
                for token in line.split():
                    if '*' in token:
                        clean = token.replace('*', '').replace('+', '').strip()
                        try:
                            rate = min(int(round(float(clean))), 60)
                        except Exception:
                            pass
                break
    except Exception:
        pass

    # 2. Get monitor name from sysfs drm edid
    try:
        connectors = glob.glob("/sys/class/drm/card*-*")
        for c in connectors:
            status_file = os.path.join(c, "status")
            edid_file = os.path.join(c, "edid")
            if os.path.exists(status_file):
                with open(status_file) as f:
                    if f.read().strip() == "connected" and os.path.exists(edid_file):
                        with open(edid_file, "rb") as ef:
                            edid = ef.read()
                        if len(edid) >= 128:
                            for offset in (54, 72, 90, 108):
                                desc = edid[offset:offset+18]
                                if desc[0:3] == b"\x00\x00\x00" and desc[3] == 0xFC:
                                    n = desc[5:].decode("ascii", errors="ignore").strip("\x00\n\r\t ")
                                    if n:
                                        monitor_name = n
                                        break
            if monitor_name != "AirPlay Display":
                break
    except Exception:
        pass

    # 3. Fallback: check xrandr --verbose for EDID
    if monitor_name == "AirPlay Display":
        try:
            out = subprocess.check_output(f"DISPLAY={disp} xrandr --verbose", shell=True).decode()
            lines = out.splitlines()
            for i, line in enumerate(lines):
                if 'EDID:' in line:
                    hex_str = ''
                    for j in range(i+1, min(i+18, len(lines))):
                        if lines[j].startswith('\t\t'):
                            hex_str += lines[j].strip()
                        else:
                            break
                    if hex_str:
                        edid_bytes = bytes.fromhex(hex_str)
                        for offset in (54, 72, 90, 108):
                            desc = edid_bytes[offset:offset+18]
                            if desc[0:3] == b'\x00\x00\x00' and desc[3] == 0xFC:
                                name = desc[5:].decode('ascii', errors='ignore').strip('\x00\n\r\t ')
                                if name:
                                    monitor_name = name
                                    break
                    if monitor_name != "AirPlay Display":
                        break
        except Exception:
            pass

    # 4. Fallback: use connected port name
    if monitor_name == "AirPlay Display":
        try:
            out = subprocess.check_output(f"DISPLAY={disp} xrandr", shell=True).decode()
            for line in out.splitlines():
                if ' connected' in line:
                    port = line.split()[0]
                    monitor_name = f"{port} Display"
                    break
        except Exception:
            pass

    return res, rate, monitor_name

def get_kernel_interface_ip(iface):
    """Reads IPv4 address directly from kernel socket via SIOCGIFADDR ioctl (<0.01ms)."""
    if not HAS_FCNTL:
        return None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        addr = fcntl.ioctl(
            s.fileno(),
            0x8915,  # SIOCGIFADDR
            struct.pack('256s', iface[:15].encode('utf-8'))
        )[20:24]
        s.close()
        ip = socket.inet_ntoa(addr)
        if ip and ip != "127.0.0.1" and not ip.startswith("169.254."):
            return ip
    except Exception:
        pass
    return None

def get_kernel_default_route_iface():
    """Parses Linux kernel routing table (/proc/net/route) to locate default gateway interface."""
    try:
        with open("/proc/net/route", "r") as f:
            for line in f.readlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 4 and parts[1] == "00000000":
                    flags = int(parts[3], 16)
                    if flags & 0x2:  # RTF_GATEWAY
                        return parts[0]
    except Exception:
        pass
    return None

def probe_kernel_network_devices():
    """
    Directly queries Linux sysfs (/sys/class/net/*) for kernel-level link states:
    - carrier (1=physical link detected by PHY, 0=unplugged/disconnected)
    - operstate ('up', 'dormant', 'down', 'lowerlayerdown', 'unknown')
    - flags (IFF_UP=0x1, IFF_RUNNING=0x40 indicates active operational hardware link)
    - ARPHRD type & wireless extensions
    """
    devices = []
    default_iface = get_kernel_default_route_iface()

    for ifpath in sorted(glob.glob("/sys/class/net/*")):
        iface = os.path.basename(ifpath)
        if iface == "lo" or iface.startswith(("docker", "veth", "br-", "virbr", "tun", "tap")):
            continue

        carrier = 0
        carrier_file = os.path.join(ifpath, "carrier")
        if os.path.isfile(carrier_file):
            try:
                with open(carrier_file, "r") as f:
                    carrier = int(f.read().strip())
            except Exception:
                carrier = 0

        operstate = "unknown"
        oper_file = os.path.join(ifpath, "operstate")
        if os.path.isfile(oper_file):
            try:
                with open(oper_file, "r") as f:
                    operstate = f.read().strip().lower()
            except Exception:
                pass

        flags = 0
        flags_file = os.path.join(ifpath, "flags")
        if os.path.isfile(flags_file):
            try:
                with open(flags_file, "r") as f:
                    flags = int(f.read().strip(), 16)
            except Exception:
                pass

        is_running = bool(flags & 0x40) or (carrier == 1)

        is_wireless = (
            os.path.isdir(os.path.join(ifpath, "wireless")) or
            os.path.isdir(os.path.join(ifpath, "phy80211")) or
            iface.startswith(("wlan", "wl"))
        )
        iface_type = "WIFI" if is_wireless else "LAN"
        ip = get_kernel_interface_ip(iface)

        devices.append({
            "iface": iface,
            "type": iface_type,
            "carrier": carrier,
            "operstate": operstate,
            "flags": flags,
            "is_running": is_running,
            "is_default": (iface == default_iface),
            "ip": ip
        })

    return devices

def get_active_wifi_ssid(iface=None):
    """Retrieves active Wi-Fi SSID with timeout protection."""
    if iface:
        try:
            out = subprocess.check_output(f"iw dev {iface} link 2>/dev/null", shell=True, timeout=1.0).decode()
            for line in out.splitlines():
                if "SSID:" in line:
                    ssid = line.split("SSID:", 1)[1].strip()
                    if ssid:
                        return ssid
        except Exception:
            pass

    try:
        out = subprocess.check_output("nmcli -t -f active,ssid dev wifi 2>/dev/null | grep ^yes", shell=True, timeout=1.0).decode()
        parts = out.strip().split(":")
        if len(parts) > 1 and parts[1]:
            return parts[1]
    except Exception:
        pass

    return ""

def check_network_status(wait_sync=False, max_wait=2.5):
    """
    Evaluates network connection at the Linux kernel level:
    - Queries /sys/class/net/* for hardware carrier & operstate.
    - Resolves IP via kernel SIOCGIFADDR ioctl (and ip -j addr fallback).
    - If wait_sync=True and kernel detects an active physical link (e.g. Ethernet cable
      plugged in or Wi-Fi associated) but DHCP has not yet finished assigning IP,
      it waits up to max_wait (checking every 50ms) so the standby screen boots up
      with the verified connected state immediately without flickering or wrong status.
    Returns: (net_type, ip, extra_info)
    """
    if os.path.exists("/tmp/simulate_offline"):
        return "NONE", "127.0.0.1", ""

    devices = probe_kernel_network_devices()

    lan_devs = [d for d in devices if d["type"] == "LAN" and (d["carrier"] == 1 or d["is_running"])]
    wifi_devs = [d for d in devices if d["type"] == "WIFI" and (d["carrier"] == 1 or d["operstate"] == "up" or d["is_running"])]

    # 1. Physical Ethernet (LAN) has absolute priority
    if lan_devs:
        lan_devs.sort(key=lambda d: 0 if d["is_default"] else 1)
        target = lan_devs[0]
        ip = target["ip"]

        if (not ip) and wait_sync:
            start_t = time.time()
            while time.time() - start_t < max_wait:
                time.sleep(0.05)
                ip = get_kernel_interface_ip(target["iface"])
                if ip:
                    break

        if not ip:
            try:
                out = subprocess.check_output("ip -j addr show " + target["iface"], shell=True, timeout=1.0).decode()
                addrs = json.loads(out)
                for item in addrs:
                    for a in item.get("addr_info", []):
                        if a.get("family") == "inet" and a.get("local") != "127.0.0.1":
                            ip = a.get("local")
                            break
            except Exception:
                pass

        if ip:
            return "LAN", ip, ""
        else:
            # Physical carrier exists: cable is connected, waiting for DHCP lease
            return "LAN", "127.0.0.1", "Đang nhận IP..."

    # 2. Wi-Fi connection
    if wifi_devs:
        wifi_devs.sort(key=lambda d: 0 if d["is_default"] else 1)
        target = wifi_devs[0]
        ip = target["ip"]

        if (not ip) and wait_sync:
            start_t = time.time()
            while time.time() - start_t < max_wait:
                time.sleep(0.05)
                ip = get_kernel_interface_ip(target["iface"])
                if ip:
                    break

        if not ip:
            try:
                out = subprocess.check_output("ip -j addr show " + target["iface"], shell=True, timeout=1.0).decode()
                addrs = json.loads(out)
                for item in addrs:
                    for a in item.get("addr_info", []):
                        if a.get("family") == "inet" and a.get("local") != "127.0.0.1":
                            ip = a.get("local")
                            break
            except Exception:
                pass

        ssid = get_active_wifi_ssid(target["iface"])
        if ip:
            return "WIFI", ip, ssid
        else:
            return "WIFI", "127.0.0.1", ssid or "Đang nhận IP..."

    # 3. Fallback: general 'ip -j addr' in case of non-standard devices
    try:
        out = subprocess.check_output("ip -j addr", shell=True, timeout=1.0).decode()
        addrs = json.loads(out)
        for item in addrs:
            name = item.get("ifname", "")
            if name == "lo":
                continue
            for a in item.get("addr_info", []):
                if a.get("family") == "inet" and a.get("local") != "127.0.0.1":
                    cand_ip = a.get("local")
                    if name.startswith(("eth", "en", "lan")):
                        return "LAN", cand_ip, ""
                    elif name.startswith(("wlan", "wl")):
                        return "WIFI", cand_ip, get_active_wifi_ssid(name)
    except Exception:
        pass

    return "NONE", "127.0.0.1", ""

def is_wifi_gui_active():
    """Checks if Wi-Fi setup GUI process is currently running."""
    try:
        out = subprocess.check_output('pgrep -f wifi_gui.py', shell=True).decode().strip()
        return bool(out)
    except Exception:
        return False

def generate_wallpaper(wifi_gui_showing=None, wait_sync=False):
    res, rate, monitor_name = get_display_info()
    net_type, ip, ssid = check_network_status(wait_sync=wait_sync)
    has_network = (net_type != "NONE")

    if wifi_gui_showing is None:
        # Layout shifts right ONLY when there is no network connection (to make room for Wi-Fi setup modal)
        wifi_gui_showing = (not has_network)

    parts = res.split('x')
    target_w, target_h = int(parts[0]), int(parts[1])

    # 2x Supersampling for ultra-crisp Retina anti-aliasing
    SS = 2
    W, H = target_w * SS, target_h * SS
    scale = min(target_w / 1280, target_h / 800) * SS

    # Apple True Dark background
    img = Image.new('RGB', (W, H), color='#070709')
    draw = ImageDraw.Draw(img)

    # Official Apple San Francisco Font Paths
    def get_font(filename, sz):
        candidates = [
            f"/usr/local/share/fonts/apple-sf-pro/{filename}",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", filename),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", filename),
        ]
        for c in candidates:
            if os.path.exists(c):
                try:
                    return ImageFont.truetype(c, sz)
                except Exception:
                    pass
        return ImageFont.load_default()

    font_title  = get_font("SFProDisplay-Heavy.ttf", int(50 * scale))
    font_label  = get_font("SFProText-Semibold.ttf", int(17 * scale))
    font_name   = get_font("SFProDisplay-Bold.ttf", int(21 * scale))
    font_status = get_font("SFProText-Semibold.ttf", int(17 * scale))
    font_inst1  = get_font("SFProText-Medium.ttf", int(17 * scale))
    font_inst2  = get_font("SFProText-Medium.ttf", int(16 * scale))

    # Apple AirPlay SF Symbol Icon
    def get_asset(filename):
        candidates = [
            f"/opt/airplay/assets/{filename}",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", filename),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", filename),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return candidates[0]

    airplay_icon_path = get_asset("airplay_large.png")
    icon_orig = Image.open(airplay_icon_path).convert('RGBA')

    # Calculate horizontal layout center
    if wifi_gui_showing:
        # Shifted right to perfectly balance with the Wi-Fi settings board on the left
        if target_w >= 1920:
            wifi_right = int(target_w * 0.08) + 480
        else:
            wifi_right = int(target_w * 0.06) + 420
        remaining_center = wifi_right + (target_w - wifi_right) // 2
        center_x = remaining_center * SS
    else:
        # Centered horizontally on the full screen
        center_x = W // 2

    # 1. Subtle Apple Ambient Glow behind center_x
    glow_scale = 0.48 if wifi_gui_showing else 0.55
    max_r = int(min(W, H) * glow_scale)
    rad_img = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    rad_draw = ImageDraw.Draw(rad_img)
    glow_alpha = 24 if wifi_gui_showing else 30
    for r in range(256, 0, -2):
        alpha = int(glow_alpha * (1.0 - r / 256.0))
        rad_draw.ellipse([256 - r, 256 - r, 256 + r, 256 + r], fill=(24, 42, 78, alpha))
    rad_scaled = rad_img.resize((max_r * 2, max_r * 2), Image.Resampling.BILINEAR)
    glow_y = int(H * (0.48 if wifi_gui_showing else 0.45))
    img.paste(rad_scaled, (center_x - max_r, glow_y - max_r), rad_scaled)

    # 2. Dimensions calculation
    target_icon_w = int((116 if wifi_gui_showing else 128) * scale)
    ratio = target_icon_w / icon_orig.width
    target_icon_h = int(icon_orig.height * ratio)
    icon_img = icon_orig.resize((target_icon_w, target_icon_h), Image.Resampling.LANCZOS)

    gap_icon_title = int((20 if wifi_gui_showing else 22) * scale)
    t_title = "AirPlay"
    b_title = draw.textbbox((0, 0), t_title, font=font_title)
    title_h = b_title[3] - b_title[1]

    gap_title_pill = int((24 if wifi_gui_showing else 26) * scale)
    lbl_txt = "Tên thiết bị: "
    val_txt = monitor_name
    b_lbl = draw.textbbox((0, 0), lbl_txt, font=font_label)
    b_val = draw.textbbox((0, 0), val_txt, font=font_name)
    pad_x, pad_y = int(26 * scale), int(13 * scale)
    pill_w = (b_lbl[2] - b_lbl[0]) + (b_val[2] - b_val[0]) + pad_x * 2
    pill_h = max(b_lbl[3] - b_lbl[1], b_val[3] - b_val[1]) + pad_y * 2

    gap_pill_stat = int((24 if wifi_gui_showing else 26) * scale)

    if has_network:
        stat_color = '#30d158'
        if net_type == "LAN":
            if ip and ip != "127.0.0.1":
                stat_text = "● Đang kết nối mạng LAN"
            else:
                stat_text = "● Đã cắm cáp LAN (Đang nhận IP...)"
            net_text = ""
        else:
            net_label = f"Wi-Fi: {ssid}" if ssid else "Wi-Fi"
            if ip and ip != "127.0.0.1":
                stat_text = f"● Đang kết nối {net_label}"
            else:
                stat_text = f"● Đã kết nối {net_label} (Đang nhận IP...)"
            net_text = ""
        b_stat = draw.textbbox((0, 0), stat_text, font=font_status)
        stat_h = b_stat[3] - b_stat[1]

        has_net_line = bool(net_text)
        if has_net_line:
            b_net = draw.textbbox((0, 0), net_text, font=font_status)
            net_h = b_net[3] - b_net[1]
            gap_stat_net = int(14 * scale)
        else:
            net_h = 0
            gap_stat_net = 0

        gap_net_inst = int((22 if wifi_gui_showing else 26) * scale)
        inst1 = "Mở Trung tâm điều khiển trên iPhone, iPad hoặc Mac"
        inst2 = f'Chọn "{monitor_name}" để kết nối'
        b_i1 = draw.textbbox((0, 0), inst1, font=font_inst1)
        b_i2 = draw.textbbox((0, 0), inst2, font=font_inst2)
        inst_h = (b_i1[3] - b_i1[1]) + int(10 * scale) + (b_i2[3] - b_i2[1])

        total_h = (target_icon_h + gap_icon_title + title_h + gap_title_pill +
                   pill_h + gap_pill_stat + stat_h + (gap_stat_net + net_h if has_net_line else 0) +
                   gap_net_inst + inst_h)
    else:
        stat_text = "● Chưa có kết nối mạng"
        stat_color = '#ff9f0a'
        b_stat = draw.textbbox((0, 0), stat_text, font=font_status)
        stat_h = b_stat[3] - b_stat[1]

        gap_stat_inst = int(22 * scale)
        inst1 = "Vui lòng chọn mạng Wi-Fi để kết nối."
        inst2 = "Dùng phím ↑ ↓ và Enter trên bàn phím"
        b_i1 = draw.textbbox((0, 0), inst1, font=font_inst1)
        b_i2 = draw.textbbox((0, 0), inst2, font=font_inst2)
        inst_h = (b_i1[3] - b_i1[1]) + int(10 * scale) + (b_i2[3] - b_i2[1])

        total_h = (target_icon_h + gap_icon_title + title_h + gap_title_pill +
                   pill_h + gap_pill_stat + stat_h + gap_stat_inst + inst_h)

    current_y = (H - total_h) // 2

    # Draw AirPlay icon
    icon_x = center_x - target_icon_w // 2
    img.paste(icon_img, (icon_x, current_y), icon_img)
    current_y += target_icon_h + gap_icon_title

    # Draw Title
    draw.text((center_x - (b_title[2] - b_title[0]) // 2, current_y), t_title, fill='#ffffff', font=font_title)
    current_y += title_h + gap_title_pill

    # Draw Device Pill Badge
    pill_x = center_x - pill_w // 2
    draw.rounded_rectangle([pill_x, current_y, pill_x + pill_w, current_y + pill_h],
                           radius=int(16 * scale), fill='#1c1c1e', outline='#3a3a3c', width=int(1.5 * scale))
    draw.text((pill_x + pad_x, current_y + pad_y), lbl_txt, fill='#aeaeb2', font=font_label)
    draw.text((pill_x + pad_x + (b_lbl[2] - b_lbl[0]), current_y + pad_y), val_txt, fill='#ffffff', font=font_name)
    current_y += pill_h + gap_pill_stat

    # Draw Status
    draw.text((center_x - (b_stat[2] - b_stat[0]) // 2, current_y), stat_text, fill=stat_color, font=font_status)
    current_y += stat_h

    # Draw Network Status if available
    if has_network and has_net_line:
        current_y += gap_stat_net
        draw.text((center_x - (b_net[2] - b_net[0]) // 2, current_y), net_text, fill='#aeaeb2', font=font_status)
        current_y += net_h + gap_net_inst
    elif has_network:
        current_y += gap_net_inst
    else:
        current_y += gap_stat_inst

    # Draw Step Instructions
    draw.text((center_x - (b_i1[2] - b_i1[0]) // 2, current_y), inst1, fill='#f5f5f7', font=font_inst1)
    draw.text((center_x - (b_i2[2] - b_i2[0]) // 2, current_y + (b_i1[3] - b_i1[1]) + int(10 * scale)), inst2, fill='#aeaeb2', font=font_inst2)

    # Downsample from 2x using Lanczos filter for razor-sharp Retina output
    final_img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    out_dir = '/opt/airplay'
    if not os.path.exists(out_dir):
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    out_file = os.path.join(out_dir, 'standby.png')
    final_img.save(out_file)
    layout_mode = "Shifted-Right (Wi-Fi Modal Active)" if wifi_gui_showing else "Centered"
    print(f"Wallpaper saved: {out_file} (Monitor: {monitor_name}, Net: {net_type}, Layout: {layout_mode}, Res: {res})")
    return monitor_name, res, rate

if __name__ == '__main__':
    shift = None
    if '--shift-right' in sys.argv:
        shift = True
    elif '--center' in sys.argv:
        shift = False
    generate_wallpaper(wifi_gui_showing=shift)
