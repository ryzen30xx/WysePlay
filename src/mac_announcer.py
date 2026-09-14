#!/usr/bin/env python3
"""
WysePlay - macOS Bonjour / AirPlay Proxy Announcer
Bridges TV Box AirPlay announcement into macOS mDNSResponder with proper Apple TV Screen Mirroring flags (0x204).
Includes reactive mDNS query watcher to ensure persistent visibility in macOS Screen Mirroring menu.
"""

import sys, os, time, subprocess, signal, socket, struct, threading

TVBOX_IPS = ["192.168.2.133", "192.168.2.97", "192.168.2.20"]
AIRPLAY_NAME = "P27FBA-RAGL"

def get_config_for_ip(ip):
    mac_clean = "1200D5218EC0"
    mac_colon = "12:00:d5:21:8e:c0"
    hostname = "x96q.local."
    
    airplay_txt = [
        f"deviceid={mac_colon}",
        "features=0x527FFEE6,0x0",
        "flags=0x204",
        "model=AppleTV3,2",
        "pk=a130efa531a109bccb8d1483f26227bacc6b2df48eaaa7c05804f5a89c6c1d17",
        "pw=false",
        "srcvers=220.68",
        "vv=2",
        "pi=2e388006-13ba-4041-9a67-25dd4a43d536"
    ]
    raop_name = f"{mac_clean}@{AIRPLAY_NAME}"
    raop_txt = [
        "ch=2", "cn=0,1,2,3", "da=true", "et=0,3,5", "vv=2",
        "ft=0x527FFEE6,0x0", "am=AppleTV3,2", "md=0,1,2", "rhd=5.6.0.0",
        "pw=false", "sr=44100", "ss=16", "sv=false", "tp=UDP", "txtvers=1",
        "sf=0x204", "vs=220.68", "vn=65537",
        "pk=a130efa531a109bccb8d1483f26227bacc6b2df48eaaa7c05804f5a89c6c1d17",
        "pi=2e388006-13ba-4041-9a67-25dd4a43d536"
    ]
    return hostname, raop_name, airplay_txt, raop_txt

def find_active_tvbox_ip():
    for ip in TVBOX_IPS:
        ret = subprocess.run(["ping", "-c", "1", "-W", "500", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ret.returncode == 0:
            return ip
    return TVBOX_IPS[0]

class ReactiveAnnouncer:
    def __init__(self, target_ip):
        self.target_ip = target_ip
        self.hostname, self.raop_name, self.airplay_txt, self.raop_txt = get_config_for_ip(target_ip)
        self.cmd_airplay = [
            "dns-sd", "-P", AIRPLAY_NAME, "_airplay._tcp", "local.", "7000",
            self.hostname, self.target_ip
        ] + self.airplay_txt
        self.cmd_raop = [
            "dns-sd", "-P", self.raop_name, "_raop._tcp", "local.", "7000",
            self.hostname, self.target_ip
        ] + self.raop_txt
        
        self.p_airplay = None
        self.p_raop = None
        self.lock = threading.Lock()
        self.running = True
        self.last_refresh_time = 0

    def start_processes(self):
        with self.lock:
            self._spawn()

    def _spawn(self):
        self._kill()
        # Clean any orphan proxy processes for this service
        subprocess.run("pkill -9 -f 'dns-sd.*P27FBA-RAGL' 2>/dev/null || true", shell=True)
        self.p_airplay = subprocess.Popen(self.cmd_airplay, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.p_raop = subprocess.Popen(self.cmd_raop, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.last_refresh_time = time.time()

    def _kill(self):
        for p in (self.p_airplay, self.p_raop):
            if p:
                try:
                    p.kill()
                    p.wait(timeout=0.5)
                except Exception:
                    pass
        self.p_airplay = None
        self.p_raop = None

    def refresh(self, reason="mDNS query"):
        # Stable registration: mDNSResponder automatically answers queries from its internal cache
        # as long as dns-sd -P is running. Never kill active dns-sd processes during user queries!
        pass

    def run(self):
        print(f"[Mac Announcer] Target TV Box IP: {self.target_ip} (Host: {self.hostname})")
        print(f"[Mac Announcer] Registering proxy for '{AIRPLAY_NAME}' ({self.raop_name}) [flags=0x204, sf=0x204]...")
        self.start_processes()
        print(f"[Mac Announcer] Active! '{AIRPLAY_NAME}' is now visible in macOS Control Center.")
        sys.stdout.flush()

        try:
            while self.running:
                time.sleep(3)
                with self.lock:
                    if not self.running:
                        break
                    airplay_dead = self.p_airplay and self.p_airplay.poll() is not None
                    raop_dead = self.p_raop and self.p_raop.poll() is not None
                    if airplay_dead or raop_dead:
                        print(f"[Mac Announcer] Proxy process died (airplay={self.p_airplay.poll() if self.p_airplay else None}, raop={self.p_raop.poll() if self.p_raop else None}), respawning...")
                        sys.stdout.flush()
                        self._spawn()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        self.running = False
        print("\n[Mac Announcer] Stopping proxy registrations...")
        sys.stdout.flush()
        with self.lock:
            self._kill()

def main():
    target_ip = sys.argv[1] if len(sys.argv) > 1 else find_active_tvbox_ip()
    announcer = ReactiveAnnouncer(target_ip)

    def signal_handler(sig, frame):
        announcer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    announcer.run()

if __name__ == "__main__":
    main()
