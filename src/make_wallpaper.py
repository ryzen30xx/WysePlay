import os, sys, glob, json, subprocess
from PIL import Image, ImageDraw, ImageFont

def get_display_info():
    res = "1280x800"
    rate = 60
    monitor_name = "AirPlay Display"

    # 1. Parse xrandr for active resolution and refresh rate
    try:
        out = subprocess.check_output("DISPLAY=:0 xrandr", shell=True).decode()
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
            out = subprocess.check_output("DISPLAY=:0 xrandr --verbose", shell=True).decode()
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
            out = subprocess.check_output("DISPLAY=:0 xrandr", shell=True).decode()
            for line in out.splitlines():
                if ' connected' in line:
                    port = line.split()[0]
                    monitor_name = f"{port} Display"
                    break
        except Exception:
            pass

    return res, rate, monitor_name

def check_network_status():
    """Returns (net_type, ip, extra_info) where net_type is LAN, WIFI, or NONE"""
    if os.path.exists("/tmp/simulate_offline"):
        return "NONE", "127.0.0.1", ""
    net_type = "NONE"
    ip = "127.0.0.1"
    ssid = ""

    try:
        out = subprocess.check_output("ip -j addr", shell=True).decode()
        addrs = json.loads(out)
        for iface in addrs:
            name = iface.get("ifname", "")
            for a in iface.get("addr_info", []):
                if a.get("family") == "inet" and a.get("local") != "127.0.0.1":
                    if name.startswith(("eth", "en")):
                        return "LAN", a.get("local"), ""
                    elif name.startswith(("wlan", "wl")):
                        net_type = "WIFI"
                        ip = a.get("local")
        if net_type == "WIFI":
            try:
                s_out = subprocess.check_output("nmcli -t -f active,ssid dev wifi 2>/dev/null | grep ^yes", shell=True).decode()
                parts = s_out.strip().split(":")
                if len(parts) > 1:
                    ssid = parts[1]
            except Exception:
                pass
            return "WIFI", ip, ssid
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

def generate_wallpaper(wifi_gui_showing=None):
    res, rate, monitor_name = get_display_info()
    net_type, ip, ssid = check_network_status()
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

    font_title  = get_font("SFProDisplay-Bold.ttf", int(42 * scale))
    font_label  = get_font("SFProText-Medium.ttf", int(17 * scale))
    font_name   = get_font("SFProDisplay-Bold.ttf", int(20 * scale))
    font_status = get_font("SFProText-Medium.ttf", int(15 * scale))
    font_inst1  = get_font("SFProText-Regular.ttf", int(15 * scale))
    font_inst2  = get_font("SFProText-Regular.ttf", int(14 * scale))

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
    glow_alpha = 24 if wifi_gui_showing else 28
    for r in range(256, 0, -2):
        alpha = int(glow_alpha * (1.0 - r / 256.0))
        rad_draw.ellipse([256 - r, 256 - r, 256 + r, 256 + r], fill=(24, 42, 78, alpha))
    rad_scaled = rad_img.resize((max_r * 2, max_r * 2), Image.Resampling.BILINEAR)
    glow_y = int(H * (0.48 if wifi_gui_showing else 0.45))
    img.paste(rad_scaled, (center_x - max_r, glow_y - max_r), rad_scaled)

    # 2. Dimensions calculation
    target_icon_w = int((108 if wifi_gui_showing else 120) * scale)
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
    pad_x, pad_y = int(24 * scale), int(12 * scale)
    pill_w = (b_lbl[2] - b_lbl[0]) + (b_val[2] - b_val[0]) + pad_x * 2
    pill_h = max(b_lbl[3] - b_lbl[1], b_val[3] - b_val[1]) + pad_y * 2

    gap_pill_stat = int(24 * scale)

    if has_network:
        stat_text = "Đang chờ kết nối..."
        stat_color = '#86868b'
        b_stat = draw.textbbox((0, 0), stat_text, font=font_status)
        stat_h = b_stat[3] - b_stat[1]

        gap_stat_net = int(14 * scale)
        if net_type == "LAN":
            net_text = "● Mạng dây (LAN)"
        else:
            net_label = f"Wi-Fi: {ssid}" if ssid else "Wi-Fi"
            net_text = f"● {net_label} ({ip})"
        b_net = draw.textbbox((0, 0), net_text, font=font_status)
        net_h = b_net[3] - b_net[1]

        gap_net_inst = int((22 if wifi_gui_showing else 26) * scale)
        inst1 = "Mở Trung tâm điều khiển trên iPhone, iPad hoặc Mac"
        inst2 = f'Chọn "{monitor_name}" để kết nối'
        b_i1 = draw.textbbox((0, 0), inst1, font=font_inst1)
        b_i2 = draw.textbbox((0, 0), inst2, font=font_inst2)
        inst_h = (b_i1[3] - b_i1[1]) + int(8 * scale) + (b_i2[3] - b_i2[1])

        total_h = (target_icon_h + gap_icon_title + title_h + gap_title_pill +
                   pill_h + gap_pill_stat + stat_h + gap_stat_net + net_h +
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
        inst_h = (b_i1[3] - b_i1[1]) + int(8 * scale) + (b_i2[3] - b_i2[1])

        total_h = (target_icon_h + gap_icon_title + title_h + gap_title_pill +
                   pill_h + gap_pill_stat + stat_h + gap_stat_inst + inst_h)

    current_y = (H - total_h) // 2

    # Draw AirPlay icon
    icon_x = center_x - target_icon_w // 2
    img.paste(icon_img, (icon_x, current_y), icon_img)
    current_y += target_icon_h + gap_icon_title

    # Draw Title
    draw.text((center_x - (b_title[2] - b_title[0]) // 2, current_y), t_title, fill='#f5f5f7', font=font_title)
    current_y += title_h + gap_title_pill

    # Draw Device Pill Badge
    pill_x = center_x - pill_w // 2
    draw.rounded_rectangle([pill_x, current_y, pill_x + pill_w, current_y + pill_h],
                           radius=int(14 * scale), fill='#1c1c1e', outline='#323236', width=int(1.2 * scale))
    draw.text((pill_x + pad_x, current_y + pad_y), lbl_txt, fill='#86868b', font=font_label)
    draw.text((pill_x + pad_x + (b_lbl[2] - b_lbl[0]), current_y + pad_y), val_txt, fill='#ffffff', font=font_name)
    current_y += pill_h + gap_pill_stat

    # Draw Status
    draw.text((center_x - (b_stat[2] - b_stat[0]) // 2, current_y), stat_text, fill=stat_color, font=font_status)
    current_y += stat_h

    # Draw Network Status if available
    if has_network:
        current_y += gap_stat_net
        draw.text((center_x - (b_net[2] - b_net[0]) // 2, current_y), net_text, fill='#5e5e62', font=font_status)
        current_y += net_h + gap_net_inst
    else:
        current_y += gap_stat_inst

    # Draw Step Instructions
    draw.text((center_x - (b_i1[2] - b_i1[0]) // 2, current_y), inst1, fill='#86868b', font=font_inst1)
    draw.text((center_x - (b_i2[2] - b_i2[0]) // 2, current_y + (b_i1[3] - b_i1[1]) + int(8 * scale)), inst2, fill='#5e5e62', font=font_inst2)

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
