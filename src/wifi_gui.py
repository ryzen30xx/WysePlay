import os, sys, subprocess, re, time, threading, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/opt/airplay")
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk
import make_wallpaper

class AppleSpring:
    """
    Apple SwiftUI / CoreAnimation standard damped harmonic spring physics solver.
    Implements exact differential equation: d^2x/dt^2 + 2*zeta*omega_n*dx/dt + omega_n^2*x = 0
    Direct counterpart of SwiftUI .spring(response, dampingRatio).
    """
    def __init__(self, response=0.44, damping_ratio=0.88, initial_velocity=0.0):
        self.response = max(0.01, response)
        self.zeta = damping_ratio
        self.omega_n = (2 * math.pi) / self.response
        self.omega_d = self.omega_n * math.sqrt(max(0.0001, 1.0 - self.zeta * self.zeta))
        self.v0 = initial_velocity
        self.duration = self.response * (1.6 if self.zeta < 0.9 else 1.3)

    def solve(self, t):
        if t <= 0:
            return 0.0, self.v0
        if t >= self.duration:
            return 1.0, 0.0
        decay = math.exp(-self.zeta * self.omega_n * t)
        c = math.cos(self.omega_d * t)
        s = math.sin(self.omega_d * t)
        k = (self.zeta * self.omega_n - self.v0) / self.omega_d
        val = 1.0 - decay * (c + k * s)
        vel = decay * (self.v0 * c + ((self.omega_n**2 - self.zeta * self.omega_n * self.v0) / self.omega_d) * s)
        return val, vel


FONT_FAMILY_DISP = "SF Pro Display"
FONT_FAMILY_TEXT = "SF Pro Text"

def get_font_file(filename):
    candidates = [
        f"/usr/local/share/fonts/apple-sf-pro/{filename}",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", filename),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", filename),
        os.path.join("/opt/airplay/fonts", filename),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return filename

def get_asset_file(filename):
    candidates = [
        f"/opt/airplay/assets/{filename}",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", filename),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", filename),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]

FONT_DISPLAY_BOLD = get_font_file("SFProDisplay-Bold.ttf")
FONT_DISPLAY_SEMI = get_font_file("SFProDisplay-Semibold.ttf")
FONT_DISPLAY_MED  = get_font_file("SFProDisplay-Medium.ttf")
FONT_TEXT_BOLD    = get_font_file("SFProText-Bold.ttf")
FONT_TEXT_SEMI    = get_font_file("SFProText-Semibold.ttf")
FONT_TEXT_MED     = get_font_file("SFProText-Medium.ttf")
FONT_TEXT_REG     = get_font_file("SFProText-Regular.ttf")

def make_rounded_img(w, h, r, fill, outline=None, outline_width=1):
    """Generates an ultra-crisp anti-aliased rounded rectangle image using 2x supersampling."""
    scale = 2
    sw, sh = w * scale, h * scale
    img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [1, 1, sw - 2, sh - 2],
        radius=r * scale,
        fill=fill,
        outline=outline,
        width=outline_width * scale
    )
    return ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))

def make_apple_wifi_badge(size=38, bg_col="#0071e3"):
    """Renders the authentic circular Apple Wi-Fi badge using the official SF Symbol."""
    scale = 2
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, s - 1, s - 1], fill=bg_col)
    
    try:
        sym = Image.open(get_asset_file("wifi_badge.png")).convert("RGBA")
        sw = int(22 * scale)
        sh = int(sym.height * (sw / sym.width))
        sym = sym.resize((sw, sh), Image.Resampling.LANCZOS)
        img.paste(sym, ((s - sw) // 2, (s - sh) // 2), sym)
    except Exception:
        pass

    return ImageTk.PhotoImage(img.resize((size, size), Image.Resampling.LANCZOS))

def make_pill_button(w, h, r, bg_color, text, text_color="#ffffff", is_bold=True):
    """Renders an Apple TV-style pill button with supersampled crisp SF Pro typography."""
    scale = 2
    sw, sh = w * scale, h * scale
    img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, sw - 1, sh - 1], radius=r * scale, fill=bg_color)
    
    font_path = FONT_DISPLAY_BOLD if is_bold else FONT_DISPLAY_SEMI
    try:
        font = ImageFont.truetype(font_path, int(11.5 * scale))
    except Exception:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (sw - tw) // 2 - bbox[0]
    ty = (sh - th) // 2 - bbox[1] - int(1 * scale)
    draw.text((tx, ty), text, fill=text_color, font=font)
    
    return ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))

def render_row_image(w, h, r, net, is_sel):
    """Renders a vector-crisp Wi-Fi list row item with official Apple SF Symbols and SF Pro fonts."""
    scale = 2
    sw, sh = w * scale, h * scale
    img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    bg_col = "#0071e3" if is_sel else "#1c1c1e"
    border_col = None if is_sel else "#2c2c2e"
    draw.rounded_rectangle([1, 1, sw - 2, sh - 2], radius=r * scale, fill=bg_col, outline=border_col, width=1 * scale)
    
    # 1. SSID Text (Apple SF Pro Display Bold when selected, SemiBold when normal)
    try:
        font_ssid = ImageFont.truetype(FONT_DISPLAY_BOLD if is_sel else FONT_DISPLAY_SEMI, int(13.5 * scale))
        font_sec  = ImageFont.truetype(FONT_TEXT_REG, int(10.5 * scale))
    except Exception:
        font_ssid = font_sec = ImageFont.load_default()
        
    draw.text((18 * scale, 9 * scale), net["ssid"], fill="#ffffff", font=font_ssid)
    
    sec_label = "Mạng mở" if (not net.get("security") or net["security"] == "--") else f"Bảo mật {net["security"]}"
    sub_col = "#d0e4ff" if is_sel else "#86868b"
    draw.text((18 * scale, 31 * scale), sec_label, fill=sub_col, font=font_sec)
    
    # 2. Official Apple SF Symbol Wi-Fi Fan Arcs
    try:
        sym_wifi_path = get_asset_file("wifi_white.png" if is_sel else "wifi_muted.png")
        sym_wifi = Image.open(sym_wifi_path).convert("RGBA")
        target_wifi_w = int(22 * scale)
        ratio = target_wifi_w / sym_wifi.width
        target_wifi_h = int(sym_wifi.height * ratio)
        sym_wifi = sym_wifi.resize((target_wifi_w, target_wifi_h), Image.Resampling.LANCZOS)
        
        wx = sw - target_wifi_w - int(18 * scale)
        wy = (sh - target_wifi_h) // 2
        img.paste(sym_wifi, (wx, wy), sym_wifi)
    except Exception:
        wx = sw - int(40 * scale)

    # 3. Official Apple SF Symbol Lock Icon (if secured)
    if net.get("security") and net["security"] != "--":
        try:
            sym_lock_path = get_asset_file("lock_white.png" if is_sel else "lock_muted.png")
            sym_lock = Image.open(sym_lock_path).convert("RGBA")
            target_lock_h = int(17 * scale)
            l_ratio = target_lock_h / sym_lock.height
            target_lock_w = int(sym_lock.width * l_ratio)
            sym_lock = sym_lock.resize((target_lock_w, target_lock_h), Image.Resampling.LANCZOS)
            
            lx = wx - target_lock_w - int(14 * scale)
            ly = (sh - target_lock_h) // 2
            img.paste(sym_lock, (lx, ly), sym_lock)
        except Exception:
            pass
                 
    return ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))

class WifiKioskApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WifiKiosk")
        self.root.configure(bg="#070709")
        self.root.attributes("-fullscreen", True)

        # Unhide cursor & ensure hardware inputs are enabled
        try:
            subprocess.run(
                'DISPLAY=:0 xinput list | grep slave | grep id= | grep -o "id=[0-9]*" | cut -d= -f2 | xargs -I{} DISPLAY=:0 xinput enable {} 2>/dev/null',
                shell=True
            )
        except Exception:
            pass

        # Screen dimensions
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if not sw or sw <= 0:
            sw = 1280
        if not sh or sh <= 0:
            sh = 800
        self.sw = sw
        self.sh = sh

        # Apple TV dark palette
        self.COLOR_BG          = "#070709"
        self.COLOR_MODAL       = "#161618"
        self.COLOR_CARD_NORM   = "#1c1c1e"
        self.COLOR_BORDER      = "#2c2c2e"
        self.COLOR_SELECTED    = "#0071e3"
        self.COLOR_TEXT        = "#ffffff"
        self.COLOR_MUTED       = "#86868b"
        self.COLOR_MUTED_SEL   = "#d0e4ff"
        self.COLOR_ERROR       = "#ff453a"
        self.COLOR_SUCCESS     = "#30d158"

        # Adaptive layout sizing
        if self.sw >= 1920:
            self.win_w = 480
            self.win_h = 630
            self.target_wx = int(self.sw * 0.08)
            self.row_w = 424
            self.row_h = 56
            self.radius_card = 24
            self.radius_row = 14
            self.sheet_w = 424
            self.sheet_h = 146
        else:
            self.win_w = 420
            self.win_h = 540
            self.target_wx = int(self.sw * 0.06)
            self.row_w = 368
            self.row_h = 50
            self.radius_card = 20
            self.radius_row = 12
            self.sheet_w = 368
            self.sheet_h = 144

        self.hidden_wx = -(self.win_w + 60)
        self.wifi_y = (self.sh - self.win_h) // 2
        self.center_ax = self.sw // 2
        self.shift_ax = self.target_wx + self.win_w + (self.sw - (self.target_wx + self.win_w)) // 2
        self.panel_w = int(self.sw * 0.58)

        # Typography
        self.f_title = (FONT_FAMILY_DISP, 17, "bold")
        self.f_sub   = (FONT_FAMILY_TEXT, 11)
        self.f_ssid  = (FONT_FAMILY_DISP, 12, "bold")
        self.f_hint  = (FONT_FAMILY_TEXT, 10)
        self.f_err   = (FONT_FAMILY_TEXT, 9)

        # Base Fullscreen Canvas
        self.canvas_root = tk.Canvas(self.root, width=self.sw, height=self.sh, bg=self.COLOR_BG, highlightthickness=0)
        self.canvas_root.pack(fill=tk.BOTH, expand=True)

        # Query initial network & display information
        self.net_type, self.ip, self.ssid = make_wallpaper.check_network_status()
        _, _, self.monitor_name = make_wallpaper.get_display_info()
        has_net = (self.net_type != "NONE")

        self.current_state = "CONNECTED" if has_net else "DISCONNECTED"
        self.cur_ax = self.center_ax if has_net else self.shift_ax
        self.cur_wx = self.hidden_wx if has_net else self.target_wx
        self.is_animating = False
        self.manual_wifi_open = False

        # State management for Wi-Fi
        self.networks = []
        self.selected_index = 0
        self.focused_ssid = None
        self.password_ssid = None
        self.is_connecting = False
        self.is_scanning = False
        self.has_wifi_device = True
        self.row_widgets = []
        self.empty_widget = None

        # Pre-render shapes & images
        self._cache_static_images()

        # 1. Place AirPlay notification panel on root canvas
        self.photo_airplay = self.render_airplay_panel(has_net)
        self.airplay_item = self.canvas_root.create_image(self.cur_ax, self.sh // 2, image=self.photo_airplay, anchor="center")

        # 2. Place Wi-Fi modal frame on root canvas via window
        self.wifi_frame = tk.Frame(self.canvas_root, width=self.win_w, height=self.win_h, bg=self.COLOR_BG)
        self.wifi_window = self.canvas_root.create_window(self.cur_wx, self.wifi_y, window=self.wifi_frame, anchor="nw")
        self._build_wifi_ui()

        # Key bindings
        self._bind_keys()

        # If disconnected on boot, immediately trigger background scan
        if not has_net:
            self.refresh_networks(force_rescan=True)

        # Start continuous network state watcher loop (every 1.5s)
        self.root.after(1500, self._network_poll_loop)

        # Start silent periodic Wi-Fi scan loop (every 12s)
        self.root.after(12000, self._auto_scan_loop)

    def _render_panel_image(self, has_network):
        """Renders raw PIL Image for AirPlay Standby Notification Panel with 2x supersampling."""
        SS = 2
        W = self.panel_w * SS
        H = self.sh * SS
        scale = min(self.sw / 1280, self.sh / 800) * SS

        img = Image.new("RGB", (W, H), color=self.COLOR_BG)
        draw = ImageDraw.Draw(img)


        try:
            font_title = ImageFont.truetype(FONT_DISPLAY_BOLD, int(42 * scale))
            font_label = ImageFont.truetype(FONT_TEXT_MED, int(17 * scale))
            font_name  = ImageFont.truetype(FONT_DISPLAY_BOLD, int(20 * scale))
            font_status= ImageFont.truetype(FONT_TEXT_MED, int(15 * scale))
            font_inst1 = ImageFont.truetype(FONT_TEXT_REG, int(15 * scale))
            font_inst2 = ImageFont.truetype(FONT_TEXT_REG, int(14 * scale))
            font_hint  = ImageFont.truetype(FONT_TEXT_REG, int(11 * scale))
        except Exception:
            font_title = font_label = font_name = font_status = font_inst1 = font_inst2 = font_hint = ImageFont.load_default()

        # AirPlay Icon
        try:
            icon_orig = Image.open(get_asset_file("airplay_large.png")).convert("RGBA")
            target_icon_w = int(112 * scale)
            ratio = target_icon_w / icon_orig.width
            target_icon_h = int(icon_orig.height * ratio)
            icon_img = icon_orig.resize((target_icon_w, target_icon_h), Image.Resampling.LANCZOS)
        except Exception:
            icon_img = Image.new("RGBA", (int(112 * scale), int(80 * scale)), (0, 113, 227, 255))
            target_icon_w, target_icon_h = icon_img.size

        center_x = W // 2

        # Ambient Blue Radial Glow
        glow_scale = 0.46 if not has_network else 0.52
        max_r = int(min(W, H) * glow_scale)
        rad_img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        rad_draw = ImageDraw.Draw(rad_img)
        glow_alpha = 24 if not has_network else 28
        for r in range(256, 0, -2):
            alpha = int(glow_alpha * (1.0 - r / 256.0))
            rad_draw.ellipse([256 - r, 256 - r, 256 + r, 256 + r], fill=(24, 42, 78, alpha))
        rad_scaled = rad_img.resize((max_r * 2, max_r * 2), Image.Resampling.BILINEAR)
        glow_y = int(H * (0.48 if not has_network else 0.45))
        img.paste(rad_scaled, (center_x - max_r, glow_y - max_r), rad_scaled)

        # Title
        t_title = "AirPlay"
        b_title = draw.textbbox((0, 0), t_title, font=font_title)
        title_h = b_title[3] - b_title[1]

        # Device Name Pill
        lbl_txt = "Tên thiết bị: "
        val_txt = self.monitor_name if self.monitor_name else "AirPlay Display"
        b_lbl = draw.textbbox((0, 0), lbl_txt, font=font_label)
        b_val = draw.textbbox((0, 0), val_txt, font=font_name)
        pad_x, pad_y = int(24 * scale), int(12 * scale)
        pill_w = (b_lbl[2] - b_lbl[0]) + (b_val[2] - b_val[0]) + pad_x * 2
        pill_h = max(b_lbl[3] - b_lbl[1], b_val[3] - b_val[1]) + pad_y * 2

        if has_network:
            stat_color = "#30d158"
            if self.net_type == "LAN":
                stat_text = f"● Đang kết nối mạng LAN ({self.ip})" if (self.ip and self.ip != "127.0.0.1") else "● Đang kết nối mạng LAN"
                net_text = ""
            else:
                net_label = f"Wi-Fi: {self.ssid}" if self.ssid else "Wi-Fi"
                stat_text = f"● Đang kết nối {net_label} ({self.ip})" if (self.ip and self.ip != "127.0.0.1") else f"● Đang kết nối {net_label}"
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

            inst1 = "Mở Trung tâm điều khiển trên iPhone, iPad hoặc Mac"
            inst2 = f"Chọn \"{val_txt}\" để kết nối"
            b_i1 = draw.textbbox((0, 0), inst1, font=font_inst1)
            b_i2 = draw.textbbox((0, 0), inst2, font=font_inst2)
            inst_h = (b_i1[3] - b_i1[1]) + int(8 * scale) + (b_i2[3] - b_i2[1])

            if getattr(self, "manual_wifi_open", False):
                hint_txt = "Nhấn phím [Esc] trên bàn phím để đóng cài đặt Wi-Fi"
            else:
                hint_txt = ""

            has_hint = bool(hint_txt)
            if has_hint:
                b_h = draw.textbbox((0, 0), hint_txt, font=font_hint)
                hint_h = b_h[3] - b_h[1]
                gap_hint = int(26 * scale)
            else:
                hint_h = 0
                gap_hint = 0

            total_h = (target_icon_h + int(20 * scale) + title_h + int(24 * scale) + pill_h +
                       int(24 * scale) + stat_h + (gap_stat_net + net_h if has_net_line else 0) +
                       int(22 * scale) + inst_h + (gap_hint + hint_h if has_hint else 0))
        else:
            stat_text = "● Chưa có kết nối mạng"
            stat_color = "#ff9f0a"
            b_stat = draw.textbbox((0, 0), stat_text, font=font_status)
            stat_h = b_stat[3] - b_stat[1]

            inst1 = "Vui lòng chọn mạng Wi-Fi ở khung bên trái."
            inst2 = "Dùng phím ↑ ↓ và Enter trên bàn phím để kết nối"
            b_i1 = draw.textbbox((0, 0), inst1, font=font_inst1)
            b_i2 = draw.textbbox((0, 0), inst2, font=font_inst2)
            inst_h = (b_i1[3] - b_i1[1]) + int(8 * scale) + (b_i2[3] - b_i2[1])

            total_h = (target_icon_h + int(20 * scale) + title_h + int(24 * scale) + pill_h +
                       int(24 * scale) + stat_h + int(22 * scale) + inst_h)

        current_y = (H - total_h) // 2

        # Draw Icon
        img.paste(icon_img, (center_x - target_icon_w // 2, current_y), icon_img)
        current_y += target_icon_h + int(20 * scale)

        # Draw Title
        draw.text((center_x - (b_title[2] - b_title[0]) // 2, current_y), t_title, fill="#f5f5f7", font=font_title)
        current_y += title_h + int(24 * scale)

        # Draw Device Name Pill
        pill_x = center_x - pill_w // 2
        draw.rounded_rectangle([pill_x, current_y, pill_x + pill_w, current_y + pill_h],
                               radius=int(14 * scale), fill="#1c1c1e", outline="#323236", width=int(1.2 * scale))
        draw.text((pill_x + pad_x, current_y + pad_y), lbl_txt, fill="#86868b", font=font_label)
        draw.text((pill_x + pad_x + (b_lbl[2] - b_lbl[0]), current_y + pad_y), val_txt, fill="#ffffff", font=font_name)
        current_y += pill_h + int(24 * scale)

        # Draw Status
        draw.text((center_x - (b_stat[2] - b_stat[0]) // 2, current_y), stat_text, fill=stat_color, font=font_status)
        current_y += stat_h

        # Draw Network Info or Spacing
        if has_network and has_net_line:
            current_y += gap_stat_net
            draw.text((center_x - (b_net[2] - b_net[0]) // 2, current_y), net_text, fill="#5e5e62", font=font_status)
            current_y += net_h + int(22 * scale)
        else:
            current_y += int(22 * scale)

        # Draw Instructions
        draw.text((center_x - (b_i1[2] - b_i1[0]) // 2, current_y), inst1, fill="#86868b", font=font_inst1)
        current_y += (b_i1[3] - b_i1[1]) + int(8 * scale)
        draw.text((center_x - (b_i2[2] - b_i2[0]) // 2, current_y), inst2, fill="#5e5e62", font=font_inst2)
        current_y += (b_i2[3] - b_i2[1])

        # Draw Subtle Key Hint if present
        if has_network and has_hint:
            current_y += gap_hint
            draw.text((center_x - (b_h[2] - b_h[0]) // 2, current_y), hint_txt, fill="#3a3a3c", font=font_hint)

        return img

    def render_airplay_panel(self, has_network):
        """Returns PhotoImage for AirPlay Standby Notification Panel."""
        img = self._render_panel_image(has_network)
        final_img = img.resize((self.panel_w, self.sh), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(final_img)

    def update_airplay_panel_image(self):
        """Renders and updates the AirPlay standby panel based on actual network state."""
        has_net = (self.net_type != "NONE")
        self.photo_airplay = self.render_airplay_panel(has_net)
        self.canvas_root.itemconfig(self.airplay_item, image=self.photo_airplay)


    def _cache_static_images(self):
        """Pre-renders reusable shapes and buttons with subpixel antialiasing."""
        # 1. Main outer modal card
        self.img_modal = make_rounded_img(self.win_w, self.win_h, self.radius_card, self.COLOR_MODAL, self.COLOR_BORDER, 1)

        # 2. Header Wi-Fi Badge with official SF Symbol
        self.img_badge = make_apple_wifi_badge(38, self.COLOR_SELECTED)

        # 3. Password sheet background & input pill
        self.img_sheet = make_rounded_img(self.sheet_w, self.sheet_h, 18, self.COLOR_CARD_NORM, self.COLOR_BORDER, 1)
        self.img_input = make_rounded_img(self.sheet_w - 32, 36, 10, "#252528", "#3a3a3c", 1)

        # 4. Action buttons
        self.img_btn_cancel     = make_pill_button(104, 34, 12, "#2c2c2e", "Hủy (Esc)", "#ffffff", is_bold=False)
        self.img_btn_connect    = make_pill_button(136, 34, 12, self.COLOR_SELECTED, "Kết nối (Enter)", "#ffffff", is_bold=True)
        self.img_btn_connecting = make_pill_button(136, 34, 12, self.COLOR_SELECTED, "Đang kết nối...", "#ffffff", is_bold=True)

    def _build_wifi_ui(self):
        """Builds the full Apple TV styled Wi-Fi Settings UI inside self.wifi_frame."""
        self.canvas_main = tk.Canvas(self.wifi_frame, width=self.win_w, height=self.win_h, bg=self.COLOR_BG, highlightthickness=0)
        self.canvas_main.pack(fill=tk.BOTH, expand=True)

        # Draw rounded modal background
        self.canvas_main.create_image(0, 0, anchor="nw", image=self.img_modal)

        # 1. Header Frame
        hdr = tk.Frame(self.canvas_main, bg=self.COLOR_MODAL)
        self.canvas_main.create_window((22, 20), window=hdr, anchor="nw", width=self.win_w - 44)

        lbl_badge = tk.Label(hdr, image=self.img_badge, bg=self.COLOR_MODAL, bd=0)
        lbl_badge.pack(side=tk.LEFT, padx=(0, 12))

        hdr_text_frame = tk.Frame(hdr, bg=self.COLOR_MODAL)
        hdr_text_frame.pack(side=tk.LEFT, fill=tk.Y)

        lbl_title = tk.Label(hdr_text_frame, text="Wi-Fi", font=self.f_title, bg=self.COLOR_MODAL, fg=self.COLOR_TEXT)
        lbl_title.pack(anchor="w")

        lbl_sub = tk.Label(hdr_text_frame, text="Chọn mạng để kết nối", font=self.f_sub, bg=self.COLOR_MODAL, fg=self.COLOR_MUTED)
        lbl_sub.pack(anchor="w")

        self.lbl_scanning = tk.Label(hdr, text="", font=self.f_sub, bg=self.COLOR_MODAL, fg=self.COLOR_MUTED)
        self.lbl_scanning.pack(side=tk.RIGHT, padx=(0, 8))

        # 2. Scrollable Network List Area
        list_y = 76
        list_h = self.win_h - 180
        self.canvas_list = tk.Canvas(self.canvas_main, bg=self.COLOR_MODAL, highlightthickness=0)
        self.scroll_window = self.canvas_main.create_window((22, list_y), window=self.canvas_list, anchor="nw",
                                                            width=self.win_w - 44, height=list_h)

        self.scrollable_frame = tk.Frame(self.canvas_list, bg=self.COLOR_MODAL)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas_list.configure(scrollregion=self.canvas_list.bbox("all"))
        )
        self.canvas_list.create_window((0, 0), window=self.scrollable_frame, anchor="nw", width=self.win_w - 44)

        # 3. Password Sheet
        self.sheet_target_y = self.win_h - (self.sheet_h + 34)
        self.sheet_animating = False
        self.cv_sheet = tk.Canvas(self.canvas_main, width=self.sheet_w, height=self.sheet_h, bg=self.COLOR_MODAL, highlightthickness=0)
        self.cv_sheet.create_image(0, 0, anchor="nw", image=self.img_sheet)

        # Title Frame: Clean prefix + BOLD Wi-Fi SSID
        self.pwd_title_frame = tk.Frame(self.cv_sheet, bg=self.COLOR_CARD_NORM)
        self.cv_sheet.create_window((16, 12), window=self.pwd_title_frame, anchor="nw")

        self.lbl_pwd_prefix = tk.Label(self.pwd_title_frame, text="Mật khẩu cho: ", font=self.f_sub,
                                       bg=self.COLOR_CARD_NORM, fg=self.COLOR_MUTED)
        self.lbl_pwd_prefix.pack(side=tk.LEFT)

        self.lbl_pwd_ssid = tk.Label(self.pwd_title_frame, text="", font=self.f_ssid,
                                     bg=self.COLOR_CARD_NORM, fg=self.COLOR_TEXT)
        self.lbl_pwd_ssid.pack(side=tk.LEFT)

        # Rounded input field
        self.cv_input = tk.Canvas(self.cv_sheet, width=self.sheet_w - 32, height=36, bg=self.COLOR_CARD_NORM, highlightthickness=0)
        self.cv_input.create_image(0, 0, anchor="nw", image=self.img_input)
        self.cv_sheet.create_window((16, 36), window=self.cv_input, anchor="nw")

        self.entry_pwd = tk.Entry(
            self.cv_input, font=(FONT_FAMILY_TEXT, 12), bg="#252528", fg=self.COLOR_TEXT,
            insertbackground=self.COLOR_TEXT, highlightthickness=0, relief=tk.FLAT, show="•", bd=0
        )
        self.cv_input.create_window((12, 9), window=self.entry_pwd, anchor="nw", width=self.sheet_w - 56)

        # Inline error/status message
        self.lbl_sheet_msg = tk.Label(self.cv_sheet, text="", font=self.f_err, bg=self.COLOR_CARD_NORM, fg=self.COLOR_ERROR)
        self.cv_sheet.create_window((16, 76), window=self.lbl_sheet_msg, anchor="nw")

        # Pill Action Buttons
        self.btn_cancel = tk.Label(self.cv_sheet, image=self.img_btn_cancel, bg=self.COLOR_CARD_NORM, bd=0, cursor="hand2")
        self.cv_sheet.create_window((16, 98), window=self.btn_cancel, anchor="nw")
        self.btn_cancel.bind("<Button-1>", lambda e: self._dismiss_password_sheet())

        self.btn_connect = tk.Label(self.cv_sheet, image=self.img_btn_connect, bg=self.COLOR_CARD_NORM, bd=0, cursor="hand2")
        self.cv_sheet.create_window((self.sheet_w - 152, 98), window=self.btn_connect, anchor="nw")
        self.btn_connect.bind("<Button-1>", lambda e: self._do_connect())

        # Sheet window ID on canvas_main (hidden initially, offset by 45px below for spring entrance)
        self.sheet_window_id = self.canvas_main.create_window((22, self.sheet_target_y + 45), window=self.cv_sheet, anchor="nw", state="hidden")


    def _bind_keys(self):
        self.root.bind("<Up>", self._on_arrow_up)
        self.root.bind("<Down>", self._on_arrow_down)
        self.root.bind("<Return>", self._on_enter_key)
        self.root.bind("<Escape>", self._on_escape_key)
        self.root.bind("<w>", lambda e: self._on_key_w())
        self.root.bind("<W>", lambda e: self._on_key_w())
        self.root.bind("<F5>", lambda e: self.refresh_networks(force_rescan=True))
        self.root.bind("<r>", lambda e: self.refresh_networks(force_rescan=True) if self.password_ssid is None else None)
        self.root.bind("<R>", lambda e: self.refresh_networks(force_rescan=True) if self.password_ssid is None else None)
        self.root.bind("<q>", lambda e: self.root.destroy() if self.password_ssid is None else None)
        self.root.bind("<Q>", lambda e: self.root.destroy() if self.password_ssid is None else None)
        self.root.focus_force()

    def _on_key_w(self):
        if self.password_ssid is not None:
            return
        self._toggle_wifi_manual()

    def animate_to_state(self, target_state, force=False):
        """Executes genuine Apple Spring physics slide with velocity inheritance."""
        if self.current_state == target_state and not force:
            return

        self.anim_gen = getattr(self, "anim_gen", 0) + 1
        my_gen = self.anim_gen

        self.current_state = target_state
        show_wifi = (target_state == "DISCONNECTED")

        # Update AirPlay standby panel based on actual network connection & manual state
        self.update_airplay_panel_image()

        start_ax = self.cur_ax
        start_wx = self.cur_wx
        tgt_ax = self.shift_ax if show_wifi else self.center_ax
        tgt_wx = self.target_wx if show_wifi else self.hidden_wx

        # Calculate normalized initial velocity if interrupted mid-spring
        v0_norm = 0.0
        dist = tgt_ax - start_ax
        if self.is_animating and hasattr(self, "cur_vel_ax") and abs(dist) > 2.0:
            v0_norm = self.cur_vel_ax / dist

        # Apple Spring calibrated to Apple TV modal presentation
        spring = AppleSpring(response=0.42, damping_ratio=0.86, initial_velocity=v0_norm)
        start_time = time.time()
        self.is_animating = True

        def step():
            if self.anim_gen != my_gen:
                return
            now = time.time()
            t = now - start_time
            val, vel = spring.solve(t)

            ax = start_ax + (tgt_ax - start_ax) * val
            wx = start_wx + (tgt_wx - start_wx) * val
            self.cur_vel_ax = (tgt_ax - start_ax) * vel

            self.canvas_root.coords(self.airplay_item, ax, self.sh // 2)
            self.canvas_root.coords(self.wifi_window, wx, self.wifi_y)
            self.cur_ax = ax
            self.cur_wx = wx

            if t < spring.duration:
                self.root.after(16, step)
            else:
                self.is_animating = False
                self.cur_ax = tgt_ax
                self.cur_wx = tgt_wx
                self.cur_vel_ax = 0.0
                self.canvas_root.coords(self.airplay_item, tgt_ax, self.sh // 2)
                self.canvas_root.coords(self.wifi_window, tgt_wx, self.wifi_y)

                if target_state == "DISCONNECTED":
                    if self.password_ssid is not None:
                        self.entry_pwd.focus_set()
                    else:
                        self.root.focus_force()
                    if not self.networks and not self.is_scanning:
                        self.refresh_networks(force_rescan=True)
                else:
                    self._dismiss_password_sheet()
                    self.root.focus_force()

        step()


    def _toggle_wifi_manual(self):
        """Allows the user to manually open/close Wi-Fi selector card via [W] key."""
        if self.password_ssid is not None:
            return
        if self.current_state == "CONNECTED":
            print("[WifiKiosk] Manual [W] toggle: Opening Wi-Fi card...")
            self.manual_wifi_open = True
            self.animate_to_state("DISCONNECTED")
        else:
            print("[WifiKiosk] Manual [W] toggle: Closing Wi-Fi card...")
            self.manual_wifi_open = False
            if self.net_type != "NONE":
                self.animate_to_state("CONNECTED")

    def _network_poll_loop(self):
        """Monitors network connection changes and triggers smooth slide transitions."""
        try:
            net_type, ip, ssid = make_wallpaper.check_network_status()
            _, _, monitor_name = make_wallpaper.get_display_info()

            monitor_changed = (monitor_name != self.monitor_name)
            self.monitor_name = monitor_name

            prev_net_type = self.net_type
            net_changed = (net_type != self.net_type)
            info_changed = (ip != self.ip or ssid != self.ssid)
            self.net_type = net_type
            self.ip = ip
            self.ssid = ssid

            if net_type == "NONE":
                if self.current_state != "DISCONNECTED":
                    print("[WifiKiosk] Network connection lost! Sliding to DISCONNECTED state...")
                    self.manual_wifi_open = False
                    self.animate_to_state("DISCONNECTED")
                elif net_changed or info_changed or monitor_changed:
                    self.update_airplay_panel_image()
            else:
                # Network is active (LAN or Wi-Fi)
                if prev_net_type == "NONE" and net_type != "NONE":
                    # Network was previously down and is now restored
                    if self.password_ssid is None and not self.is_connecting:
                        print(f"[WifiKiosk] Network restored ({net_type})! Sliding to CONNECTED state...")
                        self.manual_wifi_open = False
                        self.animate_to_state("CONNECTED")
                    else:
                        self.update_airplay_panel_image()
                elif (net_changed or info_changed or monitor_changed) and not self.is_animating:
                    # Update active connection display (e.g. DHCP IP assigned)
                    self.update_airplay_panel_image()
        except Exception as e:
            print("[WifiKiosk] Poller error:", e)

        self.root.after(1500, self._network_poll_loop)


    def _auto_scan_loop(self):
        """Silently refreshes Wi-Fi scan every 12 seconds when in DISCONNECTED state."""
        if self.current_state == "DISCONNECTED" and not self.is_connecting and not self.is_scanning:
            self.refresh_networks(force_rescan=True, silent=True)
        self.root.after(12000, self._auto_scan_loop)

    def _on_arrow_up(self, event):
        if self.current_state != "DISCONNECTED" or self.password_ssid is not None:
            return
        if self.networks and self.selected_index > 0:
            self._select_row(self.selected_index - 1)

    def _on_arrow_down(self, event):
        if self.current_state != "DISCONNECTED" or self.password_ssid is not None:
            return
        if self.networks and self.selected_index < len(self.networks) - 1:
            self._select_row(self.selected_index + 1)

    def _on_enter_key(self, event):
        if self.current_state != "DISCONNECTED":
            return
        if self.password_ssid is not None:
            self._do_connect()
        else:
            if not self.networks:
                self.refresh_networks(force_rescan=True)
                return
            if 0 <= self.selected_index < len(self.networks):
                net = self.networks[self.selected_index]
                sec = net.get("security", "")
                is_secure = bool(sec and sec != "--")
                if is_secure:
                    self._show_password_sheet(net)
                else:
                    self._do_connect()

    def _on_escape_key(self, event):
        if self.password_ssid is not None:
            self._dismiss_password_sheet()
        elif self.current_state == "DISCONNECTED" and self.net_type != "NONE":
            self.manual_wifi_open = False
            self.animate_to_state("CONNECTED")


    def _select_row(self, index):
        if not self.networks or index < 0 or index >= len(self.networks):
            return
        self.selected_index = index
        self.focused_ssid = self.networks[index]["ssid"]

        for i, row in enumerate(self.row_widgets):
            is_sel = (i == index)
            photo = row["photo_sel"] if is_sel else row["photo_norm"]
            row["canvas"].itemconfig(row["img_item"], image=photo)

        self._ensure_visible(index)

    def _ensure_visible(self, index):
        """Apple TV style smooth focus scrolling for network list."""
        total = len(self.networks)
        if total <= 1:
            return
        target_frac = max(0.0, min(1.0, (index / total) - 0.15))
        try:
            current_frac = self.canvas_list.yview()[0]
        except Exception:
            current_frac = 0.0

        if abs(target_frac - current_frac) < 0.01:
            return

        spring = AppleSpring(response=0.24, damping_ratio=0.86)
        start_time = time.time()

        def _step():
            t = time.time() - start_time
            val, _ = spring.solve(t)
            frac = current_frac + (target_frac - current_frac) * val
            self.canvas_list.yview_moveto(frac)
            if t < spring.duration:
                self.root.after(16, _step)
            else:
                self.canvas_list.yview_moveto(target_frac)

        _step()

    def _show_password_sheet(self, net):
        """Apple TV modal bottom sheet entrance animation with spring physics."""
        if getattr(self, "sheet_animating", False):
            return
        self.password_ssid = net["ssid"]
        self.lbl_pwd_ssid.config(text=net["ssid"])
        self.entry_pwd.delete(0, tk.END)
        self.lbl_sheet_msg.config(text="")

        start_y = self.sheet_target_y + 45
        self.canvas_main.coords(self.sheet_window_id, 22, start_y)
        self.canvas_main.itemconfigure(self.sheet_window_id, state="normal")
        self.canvas_main.tag_raise(self.sheet_window_id)

        spring = AppleSpring(response=0.34, damping_ratio=0.84)
        start_time = time.time()
        self.sheet_animating = True

        def _step():
            t = time.time() - start_time
            val, _ = spring.solve(t)
            cur_y = start_y + (self.sheet_target_y - start_y) * val
            self.canvas_main.coords(self.sheet_window_id, 22, cur_y)
            if t < spring.duration:
                self.root.after(16, _step)
            else:
                self.canvas_main.coords(self.sheet_window_id, 22, self.sheet_target_y)
                self.sheet_animating = False
                self.entry_pwd.focus_set()

        _step()

    def _dismiss_password_sheet(self):
        """Apple TV modal bottom sheet dismissal animation with spring physics."""
        if getattr(self, "sheet_animating", False) or self.sheet_window_id is None or self.password_ssid is None:
            return
        self.password_ssid = None
        start_y = self.sheet_target_y
        target_y = self.sheet_target_y + 45
        spring = AppleSpring(response=0.28, damping_ratio=0.90)
        start_time = time.time()
        self.sheet_animating = True

        def _step():
            t = time.time() - start_time
            val, _ = spring.solve(t)
            cur_y = start_y + (target_y - start_y) * val
            self.canvas_main.coords(self.sheet_window_id, 22, cur_y)
            if t < spring.duration:
                self.root.after(16, _step)
            else:
                self.canvas_main.coords(self.sheet_window_id, 22, target_y)
                self.canvas_main.itemconfigure(self.sheet_window_id, state="hidden")
                self.lbl_sheet_msg.config(text="")
                self.sheet_animating = False
                self.root.focus_force()

        _step()


    def refresh_networks(self, force_rescan=False, silent=False):
        if self.is_scanning:
            return
        self.is_scanning = True
        if not silent:
            self.lbl_scanning.config(text="Đang tìm...")

        def _worker():
            fresh_list = []
            has_wifi_dev = False
            try:
                dev_out = subprocess.check_output("nmcli -t -f DEVICE,TYPE,STATE dev 2>/dev/null", shell=True).decode()
                for line in dev_out.splitlines():
                    parts = line.split(":")
                    if len(parts) >= 2 and parts[1] == "wifi":
                        has_wifi_dev = True
                        break
            except Exception:
                pass

            if has_wifi_dev:
                try:
                    if force_rescan:
                        subprocess.run("sudo nmcli dev wifi rescan 2>/dev/null", shell=True, timeout=5)
                except Exception:
                    pass

                try:
                    out = subprocess.check_output("sudo nmcli -t -f IN-USE,BSSID,SSID,SIGNAL,SECURITY dev wifi list 2>/dev/null", shell=True).decode()
                    seen = set()
                    for line in out.splitlines():
                        parts = line.split(":")
                        if len(parts) < 5:
                            continue
                        in_use = (parts[0] == "*")
                        sec = parts[-1].strip()
                        sig = parts[-2].strip()
                        ssid = ":".join(parts[2:-2]).strip()

                        if not ssid or ssid == "--" or ssid in seen:
                            continue
                        seen.add(ssid)
                        try:
                            s_val = int(sig)
                        except Exception:
                            s_val = 50
                        fresh_list.append({
                            "ssid": ssid,
                            "signal": s_val,
                            "security": sec if sec else "--",
                            "in_use": in_use
                        })
                    fresh_list.sort(key=lambda x: (x.get("in_use", False), x.get("signal", 0)), reverse=True)
                except Exception as e:
                    print("[WifiKiosk Scan Error]:", e)

            # Strictly REAL data - NO dummy fallback!
            self.root.after(0, lambda: self._apply_network_data(fresh_list, has_wifi_dev))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_network_data(self, new_list, has_wifi_dev=True):
        self.is_scanning = False
        self.has_wifi_device = has_wifi_dev
        self.lbl_scanning.config(text="")

        target_ssid = self.password_ssid if self.password_ssid else self.focused_ssid
        self.networks = new_list

        for r in self.row_widgets:
            r["canvas"].destroy()
        self.row_widgets = []

        if hasattr(self, "empty_widget") and self.empty_widget:
            self.empty_widget.destroy()
            self.empty_widget = None

        if not self.networks:
            self.empty_widget = tk.Frame(self.scrollable_frame, bg=self.COLOR_MODAL)
            self.empty_widget.pack(pady=40, fill="x")

            if not has_wifi_dev:
                title = "Không tìm thấy card Wi-Fi"
                sub = "Vui lòng cắm dây cáp mạng LAN hoặc USB Wi-Fi\nNhấn [F5] để quét lại sau khi cắm"
            else:
                title = "Không tìm thấy mạng Wi-Fi nào khả dụng"
                sub = "Đang kiểm tra sóng Wi-Fi xung quanh...\nVui lòng kiểm tra router hoặc nhấn [F5] để quét lại"

            lbl_t = tk.Label(self.empty_widget, text=title, font=(FONT_FAMILY_DISP, 13, "bold"),
                             fg="#ffffff", bg=self.COLOR_MODAL)
            lbl_t.pack(pady=(0, 6))

            lbl_s = tk.Label(self.empty_widget, text=sub, font=(FONT_FAMILY_TEXT, 10),
                             fg=self.COLOR_MUTED, bg=self.COLOR_MODAL, justify="center")
            lbl_s.pack()
            return

        new_index = 0
        if target_ssid:
            for idx, item in enumerate(self.networks):
                if item["ssid"] == target_ssid:
                    new_index = idx
                    break
            else:
                new_index = min(self.selected_index, len(self.networks) - 1)

        # Build floating rounded pill rows
        for i, net in enumerate(self.networks):
            cv_row = tk.Canvas(self.scrollable_frame, width=self.row_w, height=self.row_h,
                               bg=self.COLOR_MODAL, highlightthickness=0, cursor="hand2")
            cv_row.pack(pady=4)

            p_norm = render_row_image(self.row_w, self.row_h, self.radius_row, net, False)
            p_sel  = render_row_image(self.row_w, self.row_h, self.radius_row, net, True)

            img_item = cv_row.create_image(0, 0, anchor="nw", image=p_norm)

            idx_capture = i
            cv_row.bind("<Button-1>", lambda e, idx=idx_capture: self._on_row_click(idx))

            row_data = {
                "canvas": cv_row,
                "img_item": img_item,
                "photo_norm": p_norm,
                "photo_sel": p_sel,
                "net": net
            }
            self.row_widgets.append(row_data)

        self._select_row(new_index)

        if self.password_ssid is not None:
            self.entry_pwd.focus_set()
        else:
            self.root.focus_force()

    def _on_row_click(self, index):
        if self.current_state != "DISCONNECTED":
            return
        self._select_row(index)
        net = self.networks[index]
        sec = net.get("security", "")
        if sec and sec != "--":
            self._show_password_sheet(net)
        else:
            self._do_connect()

    def _do_connect(self):
        if not self.networks or self.is_connecting:
            return

        net = self.networks[self.selected_index]
        ssid = net["ssid"]
        sec = net.get("security", "")
        is_secure = bool(sec and sec != "--")
        pwd = self.entry_pwd.get().strip()

        if is_secure and not pwd:
            self.lbl_sheet_msg.config(text="Vui lòng nhập mật khẩu", fg=self.COLOR_ERROR)
            self.entry_pwd.focus_set()
            return

        self.is_connecting = True
        self.btn_connect.config(image=self.img_btn_connecting)
        self.lbl_sheet_msg.config(text=f"Đang kết nối tới {ssid}...", fg=self.COLOR_SELECTED)

        def _connect_thread():
            if is_secure:
                cmd = f"sudo nmcli dev wifi connect \"{ssid}\" password \"{pwd}\""
            else:
                cmd = f"sudo nmcli dev wifi connect \"{ssid}\""

            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            self.root.after(0, lambda: self._handle_connect_result(res.returncode, res.stdout, res.stderr, ssid))

        threading.Thread(target=_connect_thread, daemon=True).start()

    def _handle_connect_result(self, code, stdout, stderr, ssid):
        self.is_connecting = False
        self.btn_connect.config(image=self.img_btn_connect)

        if code == 0:
            self.lbl_sheet_msg.config(text=f"✓ Đã kết nối thành công tới {ssid}!", fg=self.COLOR_SUCCESS)
            # Smoothly transition to CONNECTED after 1200ms
            def _finish():
                self.net_type, self.ip, self.ssid = make_wallpaper.check_network_status()
                self._dismiss_password_sheet()
                self.manual_wifi_open = False
                self.animate_to_state("CONNECTED")
            self.root.after(1200, _finish)

        else:
            err = stderr.strip() or stdout.strip() or "Không thể kết nối"
            if "Secret" in err or "password" in err.lower():
                err_msg = "✗ Mật khẩu không đúng. Thử lại."
            else:
                err_msg = f"✗ Lỗi kết nối ({err[:28]})"
            self.lbl_sheet_msg.config(text=err_msg, fg=self.COLOR_ERROR)
            self.entry_pwd.focus_set()

def main():
    root = tk.Tk(className="WifiKiosk")
    app = WifiKioskApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
