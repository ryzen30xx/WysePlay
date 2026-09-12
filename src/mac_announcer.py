#!/usr/bin/env python3
"""
WysePlay - macOS Bonjour / AirPlay Proxy Announcer
Bridges TV Box AirPlay announcement into macOS mDNSResponder when Wi-Fi routers
(such as Huawei / GPON routers) drop multicast packets between wireless clients.
"""

import sys, os, time, subprocess, signal

TVBOX_IPS = ["192.168.2.20", "192.168.2.97"]
TVBOX_HOSTNAME = "x96q.local."
AIRPLAY_NAME = "P27FBA-RAGL"
RAOP_NAME = f"1200D5218EC0@{AIRPLAY_NAME}"

AIRPLAY_TXT = [
    "deviceid=12:00:d5:21:8e:c0",
    "features=0x527FFEE6,0x0",
    "flags=0x4",
    "model=AppleTV3,2",
    "pk=f31f2ddf6bf1b7ec65beb1c18b0ea76acf34f6ebdb0386b4000e28b77ebfb0e4",
    "pw=false",
    "pi=2e388006-13ba-4041-9a67-25dd4a43d536",
    "srcvers=220.68",
    "vv=2"
]

RAOP_TXT = [
    "ch=2", "cn=0,1,2,3", "da=true", "et=0,3,5", "vv=2",
    "ft=0x527FFEE6,0x0", "am=AppleTV3,2", "md=0,1,2", "rhd=5.6.0.0",
    "pw=false", "sr=44100", "ss=16", "sv=false", "tp=UDP", "txtvers=1",
    "sf=0x4", "vs=220.68", "vn=65537",
    "pk=f31f2ddf6bf1b7ec65beb1c18b0ea76acf34f6ebdb0386b4000e28b77ebfb0e4"
]

def find_active_tvbox_ip():
    for ip in TVBOX_IPS:
        ret = subprocess.run(["ping", "-c", "1", "-W", "500", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ret.returncode == 0:
            return ip
    return TVBOX_IPS[0]

def main():
    target_ip = sys.argv[1] if len(sys.argv) > 1 else find_active_tvbox_ip()
    print(f"[Mac Announcer] Target TV Box IP: {target_ip}")
    print(f"[Mac Announcer] Registering proxy for '{AIRPLAY_NAME}' in macOS mDNSResponder...")

    cmd_airplay = [
        "dns-sd", "-P", AIRPLAY_NAME, "_airplay._tcp", "local.", "7000",
        TVBOX_HOSTNAME, target_ip
    ] + AIRPLAY_TXT

    cmd_raop = [
        "dns-sd", "-P", RAOP_NAME, "_raop._tcp", "local.", "7000",
        TVBOX_HOSTNAME, target_ip
    ] + RAOP_TXT

    p_airplay = subprocess.Popen(cmd_airplay, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p_raop = subprocess.Popen(cmd_raop, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cleanup(sig, frame):
        print("\n[Mac Announcer] Stopping proxy registrations...")
        p_airplay.terminate()
        p_raop.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print(f"[Mac Announcer] Active! '{AIRPLAY_NAME}' is now visible in macOS Control Center / Screen Mirroring.")
    sys.stdout.flush()

    try:
        while True:
            time.sleep(1)
            if p_airplay.poll() is not None or p_raop.poll() is not None:
                print("[Mac Announcer] Process exited, restarting...")
                break
    except KeyboardInterrupt:
        cleanup(None, None)

if __name__ == "__main__":
    main()
