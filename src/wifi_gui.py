import os, sys, subprocess, re, time, threading
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

FONT_FAMILY_DISP = "SF Pro Display"
FONT_FAMILY_TEXT = "SF Pro Text"

def get_font_file(filename):
    candidates = [
        f"/usr/local/share/fonts/apple-sf-pro/{filename}",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", filename),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", filename),
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
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img)

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

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img)

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
    
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img)

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
    
    sec_label = "Mạng mở" if (not net.get("security") or net["security"] == "--") else f"Bảo mật {net['security']}"
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
                 
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img)

class WifiSetupApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WifiKiosk")
        self.root.configure(bg="#070709")

        # Ensure all hardware inputs are enabled
        try:
            subprocess.run(
                'DISPLAY=:0 xinput list | grep slave | grep id= | grep -o "id=[0-9]*" | cut -d= -f2 | xargs -I{} DISPLAY=:0 xinput enable {} 2>/dev/null',
                shell=True
            )
        except Exception:
            pass

        # Apple TV dark aesthetic palette
        self.COLOR_BG          = "#070709"
        self.COLOR_MODAL       = "#161618" # Main modal card
        self.COLOR_CARD_NORM   = "#1c1c1e" # Row normal
        self.COLOR_BORDER      = "#2c2c2e" # Hairline border
        self.COLOR_SELECTED    = "#0071e3" # Apple System Blue
        self.COLOR_TEXT        = "#ffffff"
        self.COLOR_MUTED       = "#86868b"
        self.COLOR_MUTED_SEL   = "#d0e4ff"
        self.COLOR_ERROR       = "#ff453a"
        self.COLOR_SUCCESS     = "#30d158"

        # Screen sizing
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        if sw >= 1920:
            self.win_w = 480
            self.win_h = 630
            self.win_x = int(sw * 0.08)
            self.win_y = (sh - self.win_h) // 2
            self.row_w = 424
            self.row_h = 56
            self.radius_card = 24
            self.radius_row = 14
            self.sheet_w = 424
            self.sheet_h = 146
        else:
            self.win_w = 420
            self.win_h = 540
            self.win_x = int(sw * 0.06)
            self.win_y = (sh - self.win_h) // 2
            self.row_w = 368
            self.row_h = 50
            self.radius_card = 20
            self.radius_row = 12
            self.sheet_w = 368
            self.sheet_h = 144

        # Native Apple San Francisco typography for Tkinter widgets
        self.f_title = (FONT_FAMILY_DISP, 17, "bold")
        self.f_sub   = (FONT_FAMILY_TEXT, 11)
        self.f_ssid  = (FONT_FAMILY_DISP, 12, "bold")
        self.f_hint  = (FONT_FAMILY_TEXT, 10)
        self.f_err   = (FONT_FAMILY_TEXT, 9)

        self.root.geometry(f"{self.win_w}x{self.win_h}+{self.win_x}+{self.win_y}")
        self.root.resizable(False, False)

        # Pre-render rounded shapes & buttons
        self._cache_static_images()

        # State management
        self.networks = []
        self.selected_index = 0
        self.focused_ssid = None
        self.password_ssid = None
        self.is_connecting = False
        self.is_scanning = False
        self.has_wifi_device = True
        self.row_widgets = []
        self.empty_widget = None

        self._build_ui()
        self._bind_keys()

        # Start initial real scan in background (NO DUMMY DATA)
        self.refresh_networks(force_rescan=True)

        # Start 10-second auto-scan timer
        self.root.after(10000, self._auto_scan_loop)

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

    def _build_ui(self):
        # Base canvas covering entire window to draw rounded modal
        self.canvas_main = tk.Canvas(self.root, width=self.win_w, height=self.win_h, bg=self.COLOR_BG, highlightthickness=0)
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

        # 3. Password Sheet (Positioned cleanly at bottom)
        sheet_y = self.win_h - (self.sheet_h + 34)
        self.cv_sheet = tk.Canvas(self.canvas_main, width=self.sheet_w, height=self.sheet_h, bg=self.COLOR_MODAL, highlightthickness=0)
        self.cv_sheet.create_image(0, 0, anchor="nw", image=self.img_sheet)

        # Title Frame: Clean prefix + BOLD Wi-Fi SSID (No quotes)
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

        # Inline error/status message inside sheet
        self.lbl_sheet_msg = tk.Label(self.cv_sheet, text="", font=self.f_err, bg=self.COLOR_CARD_NORM, fg=self.COLOR_ERROR)
        self.cv_sheet.create_window((16, 76), window=self.lbl_sheet_msg, anchor="nw")

        # Pill Action Buttons
        self.btn_cancel = tk.Label(self.cv_sheet, image=self.img_btn_cancel, bg=self.COLOR_CARD_NORM, bd=0, cursor="hand2")
        self.cv_sheet.create_window((16, 98), window=self.btn_cancel, anchor="nw")
        self.btn_cancel.bind("<Button-1>", lambda e: self._dismiss_password_sheet())

        self.btn_connect = tk.Label(self.cv_sheet, image=self.img_btn_connect, bg=self.COLOR_CARD_NORM, bd=0, cursor="hand2")
        self.cv_sheet.create_window((self.sheet_w - 152, 98), window=self.btn_connect, anchor="nw")
        self.btn_connect.bind("<Button-1>", lambda e: self._do_connect())

        # Sheet window ID on canvas_main (hidden initially)
        self.sheet_window_id = self.canvas_main.create_window((22, sheet_y), window=self.cv_sheet, anchor="nw", state="hidden")


    def _bind_keys(self):
        self.root.bind("<Up>", self._on_arrow_up)
        self.root.bind("<Down>", self._on_arrow_down)
        self.root.bind("<Return>", self._on_enter_key)
        self.root.bind("<Escape>", self._on_escape_key)
        self.root.bind("<q>", lambda e: self.root.destroy() if self.password_ssid is None else None)
        self.root.bind("<Q>", lambda e: self.root.destroy() if self.password_ssid is None else None)
        self.root.bind("<F5>", lambda e: self.refresh_networks(force_rescan=True))
        self.root.bind("<r>", lambda e: self.refresh_networks(force_rescan=True) if self.password_ssid is None else None)
        self.root.bind("<R>", lambda e: self.refresh_networks(force_rescan=True) if self.password_ssid is None else None)

        self.root.focus_force()

    def _on_arrow_up(self, event):
        if self.password_ssid is not None:
            return
        if self.networks and self.selected_index > 0:
            self._select_row(self.selected_index - 1)

    def _on_arrow_down(self, event):
        if self.password_ssid is not None:
            return
        if self.networks and self.selected_index < len(self.networks) - 1:
            self._select_row(self.selected_index + 1)

    def _on_enter_key(self, event):
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
        else:
            self.root.destroy()

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
        total = len(self.networks)
        if total <= 1:
            return
        target_frac = index / total
        self.canvas_list.yview_moveto(max(0.0, target_frac - 0.15))

    def _show_password_sheet(self, net):
        self.password_ssid = net["ssid"]
        self.lbl_pwd_ssid.config(text=net["ssid"])
        self.entry_pwd.delete(0, tk.END)
        self.lbl_sheet_msg.config(text="")
        self.canvas_main.itemconfigure(self.sheet_window_id, state="normal")
        self.canvas_main.tag_raise(self.sheet_window_id)
        self.entry_pwd.focus_set()

    def _dismiss_password_sheet(self):
        self.password_ssid = None
        self.canvas_main.itemconfigure(self.sheet_window_id, state="hidden")
        self.lbl_sheet_msg.config(text="")
        self.root.focus_force()

    def _auto_scan_loop(self):
        """Runs silently every 10 seconds without interrupting user input or jumping selection."""
        if not self.is_connecting:
            self.refresh_networks(force_rescan=True, silent=True)
        self.root.after(10000, self._auto_scan_loop)

    def refresh_networks(self, force_rescan=False, silent=False):
        if self.is_scanning:
            return
        self.is_scanning = True
        if not silent:
            self.lbl_scanning.config(text="Đang tìm kiếm mạng Wi-Fi...")

        def _worker():
            # 1. Check if hardware Wi-Fi card exists
            has_wifi_dev = False
            try:
                dev_out = subprocess.check_output("nmcli -t -f TYPE dev status 2>/dev/null", shell=True).decode()
                for line in dev_out.splitlines():
                    if line.strip() == "wifi":
                        has_wifi_dev = True
                        break
            except Exception:
                pass

            fresh_list = []
            if has_wifi_dev:
                try:
                    subprocess.run("sudo rfkill unblock wifi 2>/dev/null", shell=True)
                    subprocess.run("sudo nmcli radio wifi on 2>/dev/null", shell=True)
                    if force_rescan:
                        subprocess.run("sudo nmcli dev wifi rescan 2>/dev/null", shell=True)
                except Exception:
                    pass

                try:
                    out = subprocess.check_output(
                        "sudo nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list 2>/dev/null", shell=True
                    ).decode()
                    seen = set()
                    for line in out.splitlines():
                        if not line.strip():
                            continue
                        safe_line = line.replace(r"\:", "__COLON__")
                        parts = safe_line.split(":")
                        if len(parts) >= 4:
                            in_use = (parts[0].strip() == "*")
                            ssid = parts[1].replace("__COLON__", ":").strip()
                            sig = parts[2].strip()
                            sec = parts[3].replace("__COLON__", ":").strip()
                        elif len(parts) >= 3:
                            in_use = False
                            ssid = parts[0].replace("__COLON__", ":").strip()
                            sig = parts[1].strip()
                            sec = parts[2].replace("__COLON__", ":").strip()
                        else:
                            continue

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
                    print("[WiFi Scan Error]:", e)

            # Strictly REAL data: absolutely NO dummy fallback!
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

        # Build floating rounded pill rows with pre-rendered Retina-sharp images
        for i, net in enumerate(self.networks):
            cv_row = tk.Canvas(self.scrollable_frame, width=self.row_w, height=self.row_h,
                               bg=self.COLOR_MODAL, highlightthickness=0, cursor="hand2")
            cv_row.pack(pady=4)

            # Pre-render both states with Pillow using Apple SF Pro fonts & SF Symbols
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

        # CRITICAL: Keep typing cursor inside password entry if user is currently entering password!
        if self.password_ssid is not None:
            self.entry_pwd.focus_set()
        else:
            self.root.focus_force()

    def _on_row_click(self, index):
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
                cmd = f'sudo nmcli dev wifi connect "{ssid}" password "{pwd}"'
            else:
                cmd = f'sudo nmcli dev wifi connect "{ssid}"'

            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            self.root.after(0, lambda: self._handle_connect_result(res.returncode, res.stdout, res.stderr, ssid))

        threading.Thread(target=_connect_thread, daemon=True).start()

    def _handle_connect_result(self, code, stdout, stderr, ssid):
        self.is_connecting = False
        self.btn_connect.config(image=self.img_btn_connect)

        if code == 0:
            self.lbl_sheet_msg.config(text=f"✓ Đã kết nối thành công tới {ssid}!", fg=self.COLOR_SUCCESS)
            self.root.after(1200, self.root.destroy)
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
    app = WifiSetupApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
