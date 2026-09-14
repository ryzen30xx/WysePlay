#!/usr/bin/env python3
"""
WysePlay — Unified System Orchestrator
Merges all system fragments (TV Box remote engine supervisor, macOS Bonjour proxy, 
health monitoring, self-healing, and launchd background daemon) into a single, cohesive engine.
"""

import sys, os, time, subprocess, signal, socket, struct, threading, shutil, argparse

# Ensure standard user & Homebrew paths are present in environment
os.environ["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"

# --- Canonical Invariants (Single Source of Truth) ---
AIRPLAY_NAME = "P27FBA-RAGL"
MAC_COLON = "12:00:d5:21:8e:c0"
MAC_CLEAN = "1200D5218EC0"
MODEL = "AppleTV3,2"
DEFAULT_TVBOX_IP = "192.168.2.97"
KNOWN_TVBOX_IPS = ["192.168.2.97", "192.168.2.133", "192.168.2.20"]
TVBOX_HOSTNAME = "x96q.local."
TVBOX_PORT = 7000
TVBOX_USER = "ryzen30xx"
TVBOX_PASS = "1"

AIRPLAY_TXT = [
    f"deviceid={MAC_COLON}",
    "features=0x527FFEE6,0x0",
    "flags=0x204",
    f"model={MODEL}",
    "pk=a130efa531a109bccb8d1483f26227bacc6b2df48eaaa7c05804f5a89c6c1d17",
    "pw=false",
    "srcvers=220.68",
    "vv=2",
    "pi=2e388006-13ba-4041-9a67-25dd4a43d536"
]

RAOP_NAME = f"{MAC_CLEAN}@{AIRPLAY_NAME}"
RAOP_TXT = [
    "ch=2", "cn=0,1,2,3", "da=true", "et=0,3,5", "vv=2",
    "ft=0x527FFEE6,0x0", f"am={MODEL}", "md=0,1,2", "rhd=5.6.0.0",
    "pw=false", "sr=44100", "ss=16", "sv=false", "tp=UDP", "txtvers=1",
    "sf=0x204", "vs=220.68", "vn=65537",
    "pk=a130efa531a109bccb8d1483f26227bacc6b2df48eaaa7c05804f5a89c6c1d17",
    "pi=2e388006-13ba-4041-9a67-25dd4a43d536"
]

LAUNCHD_PLIST_NAME = "com.wyseplay.orchestrator.plist"
LAUNCHD_PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_PLIST_NAME}")


def is_mac():
    return sys.platform == "darwin"


def is_linux():
    return sys.platform.startswith("linux")


def find_active_tvbox_ip():
    """Detects active TV Box IP by testing ping and AirPlay port."""
    for ip in KNOWN_TVBOX_IPS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            if s.connect_ex((ip, TVBOX_PORT)) == 0:
                s.close()
                return ip
            s.close()
        except Exception:
            pass

    for ip in KNOWN_TVBOX_IPS:
        ret = subprocess.run(["ping", "-c", "1", "-W", "300", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ret.returncode == 0:
            return ip

    return DEFAULT_TVBOX_IP


def check_tvbox_service_status(tvbox_ip):
    """Checks whether the TV Box airplay-kiosk service is running and responsive."""
    cmd = (
        f"sshpass -p '{TVBOX_PASS}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=2 "
        f"{TVBOX_USER}@{tvbox_ip} 'systemctl is-active airplay-kiosk' 2>/dev/null"
    )
    try:
        out = subprocess.check_output(cmd, shell=True, timeout=3).decode().strip()
        return out == "active"
    except Exception:
        return False


def ensure_tvbox_service_running(tvbox_ip):
    """Ensures airplay-kiosk is running on the TV box."""
    if not check_tvbox_service_status(tvbox_ip):
        print(f"[Orchestrator] TV Box ({tvbox_ip}) airplay-kiosk not active, starting it via SSH...")
        cmd = (
            f"sshpass -p '{TVBOX_PASS}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 "
            f"{TVBOX_USER}@{tvbox_ip} 'sudo systemctl start airplay-kiosk' 2>/dev/null"
        )
        try:
            subprocess.run(cmd, shell=True, timeout=5)
        except Exception as e:
            print(f"[Orchestrator] Warning: Failed to restart TV Box service: {e}")


class MacBonjourProxy:
    """Manages local macOS mDNSResponder registrations with zero-flakiness auto-healing."""

    def __init__(self, tvbox_ip):
        self.tvbox_ip = tvbox_ip
        self.p_airplay = None
        self.p_raop = None
        self.lock = threading.Lock()
        self.running = False

    def build_commands(self):
        cmd_airplay = [
            "dns-sd", "-P", AIRPLAY_NAME, "_airplay._tcp", "local.", str(TVBOX_PORT),
            TVBOX_HOSTNAME, self.tvbox_ip
        ] + AIRPLAY_TXT
        cmd_raop = [
            "dns-sd", "-P", RAOP_NAME, "_raop._tcp", "local.", str(TVBOX_PORT),
            TVBOX_HOSTNAME, self.tvbox_ip
        ] + RAOP_TXT
        return cmd_airplay, cmd_raop

    def start(self):
        with self.lock:
            self._kill()
            subprocess.run("pkill -9 -f 'dns-sd.*P27FBA-RAGL' 2>/dev/null || true", shell=True)
            cmd_air, cmd_raop = self.build_commands()
            self.p_airplay = subprocess.Popen(cmd_air, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.p_raop = subprocess.Popen(cmd_raop, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.running = True

    def _kill(self):
        for p in (self.p_airplay, self.p_raop):
            if p:
                try:
                    p.kill()
                    p.wait(timeout=0.3)
                except Exception:
                    pass
        self.p_airplay = None
        self.p_raop = None

    def stop(self):
        with self.lock:
            self.running = False
            self._kill()
            subprocess.run("pkill -9 -f 'dns-sd.*P27FBA-RAGL' 2>/dev/null || true", shell=True)

    def check_and_heal(self, current_tvbox_ip):
        with self.lock:
            if not self.running:
                return
            if current_tvbox_ip != self.tvbox_ip:
                print(f"[Orchestrator] TV Box IP changed from {self.tvbox_ip} to {current_tvbox_ip}. Rebinding Bonjour proxy...")
                self.tvbox_ip = current_tvbox_ip
                cmd_air, cmd_raop = self.build_commands()
                self._kill()
                self.p_airplay = subprocess.Popen(cmd_air, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.p_raop = subprocess.Popen(cmd_raop, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return

            air_dead = self.p_airplay is None or self.p_airplay.poll() is not None
            raop_dead = self.p_raop is None or self.p_raop.poll() is not None
            if air_dead or raop_dead:
                print("[Orchestrator] mDNS proxy process died, auto-healing immediately...")
                cmd_air, cmd_raop = self.build_commands()
                self._kill()
                self.p_airplay = subprocess.Popen(cmd_air, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.p_raop = subprocess.Popen(cmd_raop, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install_launchd_service():
    """Installs persistent macOS LaunchAgent service so WysePlay runs 24/7 in background."""
    python_bin = sys.executable
    script_path = os.path.abspath(__file__)
    repo_dir = os.path.dirname(os.path.dirname(script_path))

    os.makedirs(os.path.expanduser("~/Library/LaunchAgents"), exist_ok=True)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wyseplay.orchestrator</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{script_path}</string>
        <string>--run</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/wyseplay.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/wyseplay_err.log</string>
</dict>
</plist>
"""
    with open(LAUNCHD_PLIST_PATH, "w") as f:
        f.write(plist_content)

    subprocess.run(f"launchctl unload '{LAUNCHD_PLIST_PATH}' 2>/dev/null || true", shell=True)
    subprocess.run(f"launchctl load -w '{LAUNCHD_PLIST_PATH}'", shell=True)
    print(f"✅ Đã cài đặt dịch vụ tự khởi động WysePlay thành công: {LAUNCHD_PLIST_PATH}")
    print("Thiết bị 'P27FBA-RAGL' sẽ luôn luôn hiển thị 100% trên Control Center ngay cả khi tắt terminal hoặc khởi động lại máy Mac!")


def uninstall_launchd_service():
    """Uninstalls the macOS LaunchAgent service."""
    if os.path.exists(LAUNCHD_PLIST_PATH):
        subprocess.run(f"launchctl unload -w '{LAUNCHD_PLIST_PATH}' 2>/dev/null || true", shell=True)
        try:
            os.remove(LAUNCHD_PLIST_PATH)
        except OSError:
            pass
        subprocess.run("pkill -9 -f 'dns-sd.*P27FBA-RAGL' 2>/dev/null || true", shell=True)
        print("✅ Đã gỡ bỏ dịch vụ tự khởi động WysePlay thành công.")
    else:
        print("Dịch vụ chưa được cài đặt.")


def print_status():
    """Prints live status of WysePlay system."""
    tvbox_ip = find_active_tvbox_ip()
    port_open = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        port_open = (s.connect_ex((tvbox_ip, TVBOX_PORT)) == 0)
        s.close()
    except Exception:
        pass

    service_active = check_tvbox_service_status(tvbox_ip)
    launchd_installed = os.path.exists(LAUNCHD_PLIST_PATH)

    # Check dns-sd proxy
    dns_active = False
    try:
        out = subprocess.check_output("ps aux | grep -v grep | grep 'dns-sd.*P27FBA-RAGL' || true", shell=True).decode()
        dns_active = bool(out.strip())
    except Exception:
        pass

    print("\n" + "═" * 60)
    print("       🍏 WysePlay — Trạng Thái Hệ Thống Hợp Nhất")
    print("═" * 60)
    print(f" 📺 TV Box IP            : {tvbox_ip}")
    print(f" 🔌 AirPlay Port (7000)  : {'🟢 MỞ (Sẵn sàng)' if port_open else '🔴 ĐÓNG (Chưa phản hồi)'}")
    print(f" ⚙️  Dịch vụ Kiosk TV Box : {'🟢 ĐANG CHẠY (Native DRM 60 FPS)' if service_active else '🟡 DỪNG/KHÔNG KẾT NỐI'}")
    print(f" 📡 Bonjour Proxy (Mac)  : {'🟢 ĐANG PHÁT (Đang hiện trong Control Center)' if dns_active else '🔴 DỪNG'}")
    print(f" 🔄 Dịch vụ ngầm 24/7    : {'🟢 ĐÃ BẬT (LaunchAgent)' if launchd_installed else '⚪ CHƯA CÀI ĐẶT'}")
    print(f" 🎯 Tên thiết bị AirPlay : {AIRPLAY_NAME} (Địa chỉ MAC: {MAC_COLON})")
    print("═" * 60 + "\n")


def run_orchestrator(tvbox_ip=None, loop_forever=True):
    """Runs the unified supervisor loop."""
    if not tvbox_ip:
        tvbox_ip = find_active_tvbox_ip()

    print("\n" + "═" * 64)
    print("       🍏 Khởi động WysePlay Unified Orchestrator")
    print("═" * 64)
    print(f"[*] TV Box mục tiêu: {tvbox_ip} ({TVBOX_HOSTNAME})")

    # 1. Ensure TV Box service is active
    ensure_tvbox_service_running(tvbox_ip)

    # 2. Start macOS Bonjour Proxy
    proxy = MacBonjourProxy(tvbox_ip)
    proxy.start()
    print(f"[+] Bonjour Proxy đã kích hoạt! Thiết bị '{AIRPLAY_NAME}' đã xuất hiện trên menu Screen Mirroring.")
    print("[*] Đang chạy vòng lặp giám sát hợp nhất (tự động khôi phục nếu mất kết nối)...")
    print("═" * 64)
    sys.stdout.flush()

    def handle_exit(sig, frame):
        print("\n[!] Đang dừng WysePlay Orchestrator...")
        proxy.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    check_interval = 2.0
    tvbox_check_counter = 0

    try:
        while loop_forever:
            time.sleep(check_interval)
            # Check and heal Mac Bonjour proxy
            proxy.check_and_heal(tvbox_ip)

            # Every 10 seconds, verify TV Box responsiveness
            tvbox_check_counter += 1
            if tvbox_check_counter >= 5:
                tvbox_check_counter = 0
                new_ip = find_active_tvbox_ip()
                if new_ip != tvbox_ip:
                    tvbox_ip = new_ip
                    proxy.check_and_heal(tvbox_ip)
                ensure_tvbox_service_running(tvbox_ip)

    except KeyboardInterrupt:
        pass
    finally:
        proxy.stop()


def main():
    if is_linux():
        # Running directly on the TV Box / Linux appliance: execute Kiosk Manager
        script_dir = os.path.dirname(os.path.abspath(__file__))
        kiosk_script = os.path.join(script_dir, "kiosk_manager.py")
        if os.path.exists(kiosk_script):
            os.execv(sys.executable, [sys.executable, kiosk_script] + sys.argv[1:])
        else:
            print(f"Error: {kiosk_script} not found on Linux host.")
            sys.exit(1)

    parser = argparse.ArgumentParser(description="WysePlay Unified Orchestrator")
    parser.add_argument("action", nargs="?", default="run", choices=["run", "start", "stop", "status", "install", "uninstall"],
                        help="Action to perform: run (foreground), status, install (24/7 background), uninstall, stop")
    parser.add_argument("--ip", dest="tvbox_ip", help="Explicit TV Box IP address", default=None)
    parser.add_argument("--run", action="store_true", help="Direct run mode for launchd")

    args = parser.parse_args()

    action = args.action
    if args.run:
        action = "run"

    if action == "status":
        print_status()
    elif action == "install":
        install_launchd_service()
    elif action == "uninstall":
        uninstall_launchd_service()
    elif action == "stop":
        uninstall_launchd_service()
        subprocess.run("pkill -9 -f 'dns-sd.*P27FBA-RAGL' 2>/dev/null || true", shell=True)
        print("✅ Đã dừng toàn bộ tiến trình WysePlay.")
    elif action in ("run", "start"):
        run_orchestrator(tvbox_ip=args.tvbox_ip, loop_forever=True)


if __name__ == "__main__":
    main()
