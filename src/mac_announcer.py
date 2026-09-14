#!/usr/bin/env python3
"""
WysePlay - macOS Bonjour / AirPlay Proxy Announcer
Bridges TV Box AirPlay announcement into macOS mDNSResponder with proper Apple TV Screen Mirroring flags (0x204).
"""

import sys, os, time, subprocess, signal

TVBOX_IPS = ["192.168.2.133", "192.168.2.97", "192.168.2.20"]
AIRPLAY_NAME = "P27FBA-RAGL"

def get_config_for_ip(ip):
    mac_clean = "0200D5218EC0"
    mac_colon = "02:00:d5:21:8e:c0"
    hostname = "x96q.local."
    
    airplay_txt = [
        f"deviceid={mac_colon}",
        "features=0x527FFEE6,0x0",
        "flags=0x4",
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
        "sf=0x4", "vs=220.68", "vn=65537",
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

def main():
    target_ip = sys.argv[1] if len(sys.argv) > 1 else find_active_tvbox_ip()
    hostname, raop_name, airplay_txt, raop_txt = get_config_for_ip(target_ip)
    print(f"[Mac Announcer] Target TV Box IP: {target_ip} (Host: {hostname})")
    print(f"[Mac Announcer] Registering proxy for '{AIRPLAY_NAME}' ({raop_name}) in macOS mDNSResponder...")

    cmd_airplay = [
        "dns-sd", "-P", AIRPLAY_NAME, "_airplay._tcp", "local.", "7000",
        hostname, target_ip
    ] + airplay_txt

    cmd_raop = [
        "dns-sd", "-P", raop_name, "_raop._tcp", "local.", "7000",
        hostname, target_ip
    ] + raop_txt

    while True:
        p_airplay = subprocess.Popen(cmd_airplay)
        p_raop = subprocess.Popen(cmd_raop)

        def cleanup(sig, frame):
            print("\n[Mac Announcer] Stopping proxy registrations...")
            try:
                p_airplay.terminate()
                p_raop.terminate()
            except Exception:
                pass
            sys.exit(0)

        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)

        print(f"[Mac Announcer] Active! '{AIRPLAY_NAME}' is now registered with Screen Mirroring capabilities.")
        sys.stdout.flush()

        try:
            while True:
                time.sleep(2)
                if p_airplay.poll() is not None or p_raop.poll() is not None:
                    print("[Mac Announcer] Process exited, respawning...")
                    try:
                        p_airplay.terminate()
                        p_raop.terminate()
                    except Exception:
                        pass
                    time.sleep(1)
                    break
        except KeyboardInterrupt:
            cleanup(None, None)

if __name__ == "__main__":
    main()
