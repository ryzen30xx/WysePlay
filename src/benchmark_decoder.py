#!/usr/bin/env python3
# ==============================================================================
# WysePlay - Hardware & Video Decoder Benchmark Utility
# Determines optimal streaming resolution and FPS targeting 60fps playback
# ==============================================================================

import os
import sys
import time
import json
import re
import shutil
import subprocess
import argparse

# ANSI Colors
C_RESET = '\033[0m'
C_BOLD = '\033[1m'
C_CYAN = '\033[38;5;45m'
C_BLUE = '\033[38;5;39m'
C_GREEN = '\033[38;5;82m'
C_YELLOW = '\033[38;5;214m'
C_RED = '\033[38;5;196m'
C_GRAY = '\033[38;5;244m'

DEFAULT_CONFIG_PATH = "/opt/airplay/hw_profile.json"
ETC_CONFIG_PATH = "/etc/wyseplay.conf"

def log_step(msg):
    print(f"\n{C_BOLD}{C_CYAN}▶  {msg}{C_RESET}")

def log_info(msg):
    print(f"{C_BLUE}ℹ  {msg}{C_RESET}")

def log_success(msg):
    print(f"{C_GREEN}✔  {msg}{C_RESET}")

def log_warn(msg):
    print(f"{C_YELLOW}⚠  {msg}{C_RESET}")

def log_error(msg):
    print(f"{C_RED}✖  {msg}{C_RESET}", file=sys.stderr)

def get_cpu_info():
    """Extracts CPU architecture, core count, and processor name."""
    info = {
        "arch": os.uname().machine,
        "cores": os.cpu_count() or 1,
        "model": "Unknown CPU"
    }

    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    info["model"] = line.split(":", 1)[1].strip()
                    break
                elif "Hardware" in line or "Processor" in line:
                    info["model"] = line.split(":", 1)[1].strip()
    except Exception:
        pass

    if info["model"] in ("Unknown CPU", "-"):
        try:
            out = subprocess.check_output("lscpu 2>/dev/null", shell=True).decode()
            for line in out.splitlines():
                if "Model name:" in line:
                    m = line.split(":", 1)[1].strip()
                    if m and m != "-":
                        info["model"] = m
                        break
        except Exception:
            pass

    return info

def locate_benchmark_file(filename):
    """Finds the benchmark sample file from standard paths or assets."""
    search_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "benchmark", filename),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "benchmark", filename),
        os.path.join("/opt/airplay/assets/benchmark", filename),
        os.path.join("/tmp", filename)
    ]
    for p in search_paths:
        if os.path.isfile(p) and os.path.getsize(p) > 1000:
            return os.path.abspath(p)
    return None

def generate_fallback_clip(res, out_path, num_frames=120):
    """Generates an H.264 sample clip if pre-encoded assets are missing."""
    w, h = res.split('x')
    encoders = ['openh264enc', 'x264enc']
    for enc in encoders:
        cmd = [
            'gst-launch-1.0', '-q',
            'videotestsrc', f'num-buffers={num_frames}', 'pattern=ball',
            '!', f'video/x-raw,width={w},height={h},framerate=60/1',
            '!', enc,
            '!', 'video/x-h264',
            '!', 'filesink', f'location={out_path}'
        ]
        try:
            ret = subprocess.run(cmd, capture_output=True, timeout=15)
            if ret.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 5000:
                return out_path
        except Exception:
            continue
    return None

def detect_functional_decoders(test_file):
    """Checks for hardware decoders and standard software decoder."""
    candidate_hw = ['v4l2h264dec', 'vaapih264dec', 'nvh264dec']
    working_hw = []

    for hw in candidate_hw:
        # Check if plugin is registered in gstreamer
        insp = subprocess.run(['gst-inspect-1.0', hw], capture_output=True)
        if insp.returncode == 0:
            # Test decoding 10 frames to verify device node / driver is actually functional
            test_cmd = [
                'gst-launch-1.0', '-q',
                'filesrc', f'location={test_file}',
                '!', 'h264parse',
                '!', hw,
                '!', 'fakesink', 'sync=false', 'num-buffers=10'
            ]
            try:
                res = subprocess.run(test_cmd, capture_output=True, timeout=5)
                if res.returncode == 0:
                    working_hw.append(hw)
            except Exception:
                pass

    return working_hw

def run_decode_test(clip_path, decoder, num_frames=120, timeout=15):
    """
    Executes a decode benchmark on clip_path using decoder.
    Returns (measured_fps, error_str).
    """
    cmd = [
        'gst-launch-1.0', '-v',
        'filesrc', f'location={clip_path}',
        '!', 'h264parse',
        '!', decoder,
        '!', 'fpsdisplaysink', 'video-sink=fakesink', 'text-overlay=false', 'sync=false', 'fps-update-interval=10'
    ]

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        wall_time = time.time() - t0
    except subprocess.TimeoutExpired:
        return 0.0, "Timeout (>15s)"
    except Exception as e:
        return 0.0, str(e)

    if proc.returncode != 0:
        return 0.0, f"GStreamer pipeline error (code {proc.returncode})"

    output = proc.stdout + "\n" + proc.stderr
    
    # 1. Look for fpsdisplaysink last-message: average: XXX.XX
    averages = re.findall(r'last-message\s*=\s*rendered:\s*(\d+),\s*dropped:\s*(\d+).*?average:\s*([0-9.]+)', output)
    if averages:
        last_rendered, last_dropped, last_avg = averages[-1]
        try:
            fps_val = float(last_avg)
            if fps_val > 0:
                return fps_val, None
        except Exception:
            pass

    # 2. Fallback: Parse Execution ended after 0:00:00.XXXXXX
    m_exec = re.search(r'Execution ended after ([0-9:]+)\.([0-9]+)', output)
    if m_exec:
        time_str = m_exec.group(1)
        sub_str = m_exec.group(2)
        parts = time_str.split(':')
        seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + float("0." + sub_str)
        if seconds > 0.005:
            fps_val = num_frames / seconds
            return fps_val, None

    # 3. Fallback to wall-clock time
    if wall_time > 0.005:
        return (num_frames / wall_time), None

    return 60.0, None

def benchmark_hardware():
    """Runs the comprehensive video decoding benchmark across candidate profiles."""
    cpu = get_cpu_info()
    print(f"\n{C_BOLD}======================================================================{C_RESET}")
    print(f"{C_BOLD}  ⚡ WYSEPLAY DECODER PERFORMANCE BENCHMARK{C_RESET}")
    print(f"{C_BOLD}======================================================================{C_RESET}")
    print(f"  • CPU Model:        {C_CYAN}{cpu['model']}{C_RESET}")
    print(f"  • Kiến trúc / Cores: {C_CYAN}{cpu['arch']} ({cpu['cores']} cores){C_RESET}")

    # 1. Resolve benchmark clips
    clip_1080p = locate_benchmark_file("bench_1080p.h264")
    clip_720p = locate_benchmark_file("bench_720p.h264")

    if not clip_1080p:
        log_info("Tạo mẫu H.264 1080p để đo kiểm...")
        clip_1080p = generate_fallback_clip("1920x1080", "/tmp/bench_1080p.h264")
    if not clip_720p:
        log_info("Tạo mẫu H.264 720p để đo kiểm...")
        clip_720p = generate_fallback_clip("1280x720", "/tmp/bench_720p.h264")

    if not clip_720p and not clip_1080p:
        log_warn("Không thể tạo tệp kiểm thử video. Sử dụng ước lượng thông số dựa trên CPU...")
        return fallback_profile(cpu)

    # 2. Check for functional hardware decoders
    test_clip = clip_720p or clip_1080p
    working_hw = detect_functional_decoders(test_clip)
    
    selected_decoder = "avdec_h264"
    if working_hw:
        selected_decoder = working_hw[0]
        log_success(f"Phát hiện giải mã phần cứng GPU: {C_BOLD}{selected_decoder}{C_RESET}")
    else:
        log_info(f"Sử dụng bộ giải mã CPU đa luồng tiêu chuẩn: {C_BOLD}avdec_h264 (libav/ffmpeg){C_RESET}")

    # 3. Execute Benchmarks
    results = {}

    # Benchmark 1080p
    if clip_1080p:
        print(f"\n  [1/2] Đang đo kiểm tốc độ giải mã {C_BOLD}1080p (Full HD){C_RESET} qua {selected_decoder}...")
        fps_1080, err = run_decode_test(clip_1080p, selected_decoder)
        if err:
            log_warn(f"Lỗi khi đo 1080p: {err}")
            fps_1080 = 0.0
        results["1080p"] = {
            "fps": round(fps_1080, 1),
            "passed_60": fps_1080 >= 58.0,
            "passed_30": fps_1080 >= 28.0
        }
        status_1080 = f"{C_GREEN}ĐẠT 60 FPS{C_RESET}" if results["1080p"]["passed_60"] else (
            f"{C_YELLOW}ĐẠT 30 FPS{C_RESET}" if results["1080p"]["passed_30"] else f"{C_RED}KHÔNG ĐẠT{C_RESET}"
        )
        print(f"        ↳ Tốc độ đạt được: {C_BOLD}{results['1080p']['fps']} FPS{C_RESET} ({status_1080})")

    # Benchmark 720p
    if clip_720p:
        print(f"  [2/2] Đang đo kiểm tốc độ giải mã {C_BOLD}720p (HD Ready){C_RESET} qua {selected_decoder}...")
        fps_720, err = run_decode_test(clip_720p, selected_decoder)
        if err:
            log_warn(f"Lỗi khi đo 720p: {err}")
            fps_720 = 0.0
        results["720p"] = {
            "fps": round(fps_720, 1),
            "passed_60": fps_720 >= 58.0,
            "passed_30": fps_720 >= 28.0
        }
        status_720 = f"{C_GREEN}ĐẠT 60 FPS{C_RESET}" if results["720p"]["passed_60"] else (
            f"{C_YELLOW}ĐẠT 30 FPS{C_RESET}" if results["720p"]["passed_30"] else f"{C_RED}KHÔNG ĐẠT{C_RESET}"
        )
        print(f"        ↳ Tốc độ đạt được: {C_BOLD}{results['720p']['fps']} FPS{C_RESET} ({status_720})")

    # 4. Profile Decision Logic (Goal: "phải đạt được 60fps nếu có thể")
    p1080 = results.get("1080p", {"passed_60": False, "passed_30": False, "fps": 0.0})
    p720 = results.get("720p", {"passed_60": False, "passed_30": False, "fps": 0.0})

    if p1080["passed_60"]:
        selected = {
            "resolution": "1920x1080",
            "width": 1920,
            "height": 1080,
            "max_fps": 60,
            "tier": "Full HD @ 60 FPS (Mượt mà tối đa)",
            "reason": f"CPU/GPU mạnh mẽ, giải mã 1080p đạt {p1080['fps']} FPS (vượt ngưỡng 60 FPS)."
        }
    elif p720["passed_60"]:
        # Priority rule: User requires 60 FPS if possible!
        # If 1080p cannot do 60fps, prefer 720p@60fps over 1080p@30fps for ultra-smooth AirPlay interaction!
        selected = {
            "resolution": "1280x720",
            "width": 1280,
            "height": 720,
            "max_fps": 60,
            "tier": "HD Ready @ 60 FPS (Ưu tiên độ mượt 60 FPS)",
            "reason": f"1080p chỉ đạt {p1080['fps']} FPS. Ưu tiên 720p @ 60 FPS ({p720['fps']} FPS) để AirPlay không bị giật lag."
        }
    elif p1080["passed_30"]:
        selected = {
            "resolution": "1920x1080",
            "width": 1920,
            "height": 1080,
            "max_fps": 30,
            "tier": "Full HD @ 30 FPS (Sắc nét ổn định)",
            "reason": f"Phần cứng không duy trì được 60 FPS. Chọn 1080p @ 30 FPS ({p1080['fps']} FPS) để bảo đảm độ sắc nét."
        }
    elif p720["passed_30"]:
        selected = {
            "resolution": "1280x720",
            "width": 1280,
            "height": 720,
            "max_fps": 30,
            "tier": "HD Ready @ 30 FPS (Tiết kiệm tải CPU)",
            "reason": f"Cấu hình tối ưu 720p @ 30 FPS ({p720['fps']} FPS) giúp thiết bị hoạt động mát mẻ, không drop frame."
        }
    else:
        selected = {
            "resolution": "960x540",
            "width": 960,
            "height": 540,
            "max_fps": 30,
            "tier": "SD 540p @ 30 FPS (Cấu hình tối thiểu)",
            "reason": "Phần cứng siêu nhẹ, giảm tải tối đa để tránh quá nhiệt."
        }

    profile_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu": cpu,
        "decoder": selected_decoder,
        "video_sink": "ximagesink",
        "benchmarks": results,
        "selected_profile": selected
    }

    return profile_data

def fallback_profile(cpu):
    """Fallback profile based purely on core count if benchmark files unavailable."""
    if cpu["cores"] >= 4 and cpu["arch"] in ("x86_64", "amd64"):
        res, fps = "1920x1080", 60
        tier = "Full HD @ 60 FPS"
    elif cpu["cores"] >= 4:
        res, fps = "1280x720", 60
        tier = "HD Ready @ 60 FPS"
    else:
        res, fps = "1280x720", 30
        tier = "HD Ready @ 30 FPS"

    w, h = res.split('x')
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu": cpu,
        "decoder": "avdec_h264",
        "video_sink": "ximagesink",
        "benchmarks": {},
        "selected_profile": {
            "resolution": res,
            "width": int(w),
            "height": int(h),
            "max_fps": fps,
            "tier": tier,
            "reason": f"Ước lượng theo thông số {cpu['cores']} nhân ({cpu['arch']})."
        }
    }

def save_profile(profile_data, json_path=DEFAULT_CONFIG_PATH, etc_path=ETC_CONFIG_PATH):
    """Persists profile configuration to disk."""
    try:
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(profile_data, f, indent=2)
        log_success(f"Đã lưu hồ sơ phần cứng vào: {C_BOLD}{json_path}{C_RESET}")
    except Exception as e:
        log_warn(f"Không thể ghi {json_path}: {e}")

    try:
        sp = profile_data["selected_profile"]
        lines = [
            "# WysePlay Auto-Generated Hardware Profile",
            f"# Generated: {profile_data.get('timestamp')}",
            f"WYSEPLAY_RESOLUTION={sp['resolution']}",
            f"WYSEPLAY_WIDTH={sp['width']}",
            f"WYSEPLAY_HEIGHT={sp['height']}",
            f"WYSEPLAY_MAX_FPS={sp['max_fps']}",
            f"WYSEPLAY_DECODER={profile_data.get('decoder', 'avdec_h264')}",
            f"WYSEPLAY_VIDEOSINK={profile_data.get('video_sink', 'ximagesink')}",
            f"WYSEPLAY_TIER=\"{sp['tier']}\"",
            ""
        ]
        with open(etc_path, "w") as f:
            f.write("\n".join(lines))
        log_success(f"Đã cập nhật tệp cấu hình hệ thống: {C_BOLD}{etc_path}{C_RESET}")
    except Exception:
        # /etc/wyseplay.conf may require root permissions; warning is non-fatal if user is non-root
        pass

def print_summary(profile_data):
    """Prints a styled verdict summary."""
    sp = profile_data["selected_profile"]
    dec = profile_data["decoder"]

    print(f"\n{C_BOLD}----------------------------------------------------------------------{C_RESET}")
    print(f"{C_BOLD}{C_GREEN}  🎉 KẾT QUẢ TỐI ƯU HÓA CẤU HÌNH AIRPLAY (UXPLAY):{C_RESET}")
    print(f"{C_BOLD}----------------------------------------------------------------------{C_RESET}")
    print(f"  • Cấu hình lựa chọn:  {C_BOLD}{C_GREEN}{sp['tier']}{C_RESET}")
    print(f"  • Độ phân giải tối đa: {C_CYAN}{sp['resolution']}{C_RESET}")
    print(f"  • Tốc độ khung hình:   {C_CYAN}{sp['max_fps']} FPS{C_RESET}")
    print(f"  • Bộ giải mã video:   {C_CYAN}{dec}{C_RESET}")
    print(f"  • Phân tích lý do:     {C_GRAY}{sp['reason']}{C_RESET}")
    print(f"{C_BOLD}----------------------------------------------------------------------{C_RESET}\n")

def main():
    parser = argparse.ArgumentParser(description="WysePlay Hardware Decoder Benchmark")
    parser.add_argument("--force", action="store_true", help="Force re-run benchmark even if config exists")
    parser.add_argument("--json", action="store_true", help="Output raw JSON only")
    parser.add_argument("--out", default=DEFAULT_CONFIG_PATH, help="Output path for JSON profile")
    args = parser.parse_args()

    if not args.force and os.path.isfile(args.out) and not args.json:
        try:
            with open(args.out) as f:
                existing = json.load(f)
            log_info(f"Hồ sơ cấu hình đã tồn tại tại {args.out}.")
            print_summary(existing)
            print(f"{C_GRAY}(Chạy lại với tham số --force để đo kiểm lại){C_RESET}\n")
            return
        except Exception:
            pass

    profile = benchmark_hardware()
    save_profile(profile, json_path=args.out)

    if args.json:
        print(json.dumps(profile, indent=2))
    else:
        print_summary(profile)

if __name__ == "__main__":
    main()
