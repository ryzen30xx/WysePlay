#!/usr/bin/env python3
# ==============================================================================
# WysePlay - Hardware & Video Decoder Benchmark Utility
# Tests from 4K down to 720p, targeting 60 FPS for ultra-smooth AirPlay.
# Features automatic Hardware VPU (Cedrus/V4L2/VA-API) activation & evaluation,
# comparing FPS, CPU load, and temperature to select the optimal configuration.
# ==============================================================================

import os
import sys
import time
import json
import re
import glob
import shutil
import threading
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

# ==============================================================================
# HARDWARE & TELEMETRY MONITORING (CPU, TEMP, GPU)
# ==============================================================================

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

    if info["model"] in ("Unknown CPU", "-"):
        try:
            m = subprocess.check_output("sysctl -n machdep.cpu.brand_string 2>/dev/null", shell=True).decode().strip()
            if m:
                info["model"] = m
        except Exception:
            pass

    return info

def read_cpu_stat():
    """Returns (total_ticks, idle_ticks) from /proc/stat."""
    try:
        with open("/proc/stat", "r") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = [float(x) for x in line.split()[1:]]
                    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                    total = sum(parts)
                    return total, idle
    except Exception:
        pass
    return None, None

def get_system_temp():
    """Returns the highest current thermal zone or hwmon temperature in Celsius."""
    temps = []
    # 1. /sys/class/thermal/thermal_zone*/temp
    if os.path.isdir("/sys/class/thermal"):
        try:
            for entry in os.listdir("/sys/class/thermal"):
                if entry.startswith("thermal_zone"):
                    p = os.path.join("/sys/class/thermal", entry, "temp")
                    if os.path.isfile(p):
                        with open(p, "r") as f:
                            raw = float(f.read().strip())
                            if raw > 1000:
                                raw /= 1000.0
                            if 0 < raw < 130:
                                temps.append(raw)
        except Exception:
            pass

    # 2. /sys/class/hwmon/hwmon*/temp*_input
    if not temps and os.path.isdir("/sys/class/hwmon"):
        try:
            for hw in os.listdir("/sys/class/hwmon"):
                hw_dir = os.path.join("/sys/class/hwmon", hw)
                for f_name in os.listdir(hw_dir):
                    if f_name.startswith("temp") and f_name.endswith("_input"):
                        with open(os.path.join(hw_dir, f_name), "r") as f:
                            raw = float(f.read().strip()) / 1000.0
                            if 0 < raw < 130:
                                temps.append(raw)
        except Exception:
            pass

    if temps:
        return max(temps)
    return None

def get_gpu_utilization():
    """Attempts to read GPU/VPU busy percent from sysfs/debugfs."""
    paths = [
        "/sys/class/drm/card0/device/gpu_busy_percent",
        "/sys/kernel/debug/mali/gpu_utilization",
        "/sys/devices/platform/*.mali/utilization",
        "/sys/class/misc/mali0/device/utilization",
        "/sys/devices/platform/*.gpu/utilization"
    ]
    for p in paths:
        try:
            for match in glob.glob(p):
                with open(match, "r") as f:
                    content = f.read().strip()
                    nums = re.findall(r'\d+', content)
                    if nums:
                        return float(nums[0])
        except Exception:
            pass
    return None

class TelemetryTracker:
    """Tracks CPU utilization, peak temperature, and GPU usage during benchmark runs."""
    def __init__(self, sample_interval=0.1):
        self.sample_interval = sample_interval
        self._stop_event = threading.Event()
        self._thread = None
        self.temp_start = None
        self.temp_peak = None
        self.gpu_peak = None
        self.cpu_total_0 = None
        self.cpu_idle_0 = None
        self.cpu_total_1 = None
        self.cpu_idle_1 = None
        self.cpu_avg = 0.0

    def start(self):
        self.cpu_total_0, self.cpu_idle_0 = read_cpu_stat()
        self.temp_start = get_system_temp()
        self.temp_peak = self.temp_start
        self.gpu_peak = get_gpu_utilization()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def _monitor(self):
        while not self._stop_event.is_set():
            t = get_system_temp()
            if t is not None:
                if self.temp_peak is None or t > self.temp_peak:
                    self.temp_peak = t
            gpu = get_gpu_utilization()
            if gpu is not None:
                if self.gpu_peak is None or gpu > self.gpu_peak:
                    self.gpu_peak = gpu
            time.sleep(self.sample_interval)

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self.cpu_total_1, self.cpu_idle_1 = read_cpu_stat()
        
        t_final = get_system_temp()
        if t_final is not None:
            if self.temp_peak is None or t_final > self.temp_peak:
                self.temp_peak = t_final

        if self.cpu_total_0 is not None and self.cpu_total_1 is not None:
            dt = self.cpu_total_1 - self.cpu_total_0
            di = self.cpu_idle_1 - self.cpu_idle_0
            if dt > 0:
                self.cpu_avg = round(max(0.0, (dt - di) / dt) * 100.0, 1)

        delta_temp = None
        if self.temp_start is not None and self.temp_peak is not None:
            delta_temp = round(self.temp_peak - self.temp_start, 1)

        return {
            "cpu_avg": self.cpu_avg,
            "temp_start": self.temp_start,
            "temp_peak": self.temp_peak,
            "temp_delta": delta_temp,
            "gpu_peak": self.gpu_peak
        }

# ==============================================================================
# BENCHMARK SAMPLES & VIDEO GENERATION
# ==============================================================================

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

def generate_fallback_clip(res, out_path, codec="h264", num_frames=120):
    """Generates an H.264 or H.265 sample clip if pre-encoded assets are missing."""
    w, h = res.split('x')
    encoders = ['openh264enc', 'x264enc'] if codec == 'h264' else ['x265enc']
    gst_caps = 'video/x-h264' if codec == 'h264' else 'video/x-h265'

    for enc in encoders:
        cmd = [
            'gst-launch-1.0', '-q',
            'videotestsrc', f'num-buffers={num_frames}', 'pattern=ball',
            '!', f'video/x-raw,width={w},height={h},framerate=60/1',
            '!', enc,
            '!', gst_caps,
            '!', 'filesink', f'location={out_path}'
        ]
        try:
            ret = subprocess.run(cmd, capture_output=True, timeout=15)
            if ret.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 5000:
                return out_path
        except Exception:
            continue
    return None

# ==============================================================================
# HARDWARE VPU (CEDRUS / V4L2 / VA-API) ACTIVATION & PROBING
# ==============================================================================

def try_activate_hardware_vpu():
    """
    Attempts to enable hardware VPU kernel drivers (Cedrus, V4L2 M2M, VA-API, etc.)
    and discovers functional GStreamer hardware decoders.
    """
    log_info("Đang kiểm tra và kích hoạt VPU phần cứng (Cedrus/V4L2/VA-API)...")
    modules = [
        "cedrus",          # Allwinner H313, H616, H6, H3, A64 VPU
        "sunxi_cedrus",    # Allwinner alternative naming
        "v4l2_mem2mem",    # V4L2 M2M subsystem
        "videodev",
        "rkvdec",          # Rockchip VPU (RK3328, RK3399, RK3566, RK3588)
        "hantro_vpu",      # Hantro VPU
        "meson_vdec"       # Amlogic VPU (S905X, S905W, etc.)
    ]

    for mod in modules:
        try:
            subprocess.run(["modprobe", mod], capture_output=True, timeout=3)
        except Exception:
            pass

    # Check for V4L2 video devices in /dev
    v4l2_devices = []
    if os.path.isdir("/dev"):
        for dev in os.listdir("/dev"):
            if dev.startswith("video") or dev.startswith("media"):
                v4l2_devices.append(os.path.join("/dev", dev))

    if v4l2_devices:
        log_info(f"Phát hiện {len(v4l2_devices)} cổng V4L2: {', '.join(v4l2_devices[:4])}")

    # Re-inspect candidate hardware decoders in GStreamer
    hw_candidates = {
        "h264": ['v4l2slh264dec', 'v4l2h264dec', 'vaapih264dec', 'nvh264dec'],
        "h265": ['v4l2slh265dec', 'v4l2h265dec', 'vaapih265dec', 'nvh265dec']
    }

    discovered = {}
    for codec, candidates in hw_candidates.items():
        for cand in candidates:
            try:
                ret = subprocess.run(['gst-inspect-1.0', cand], capture_output=True, timeout=5)
                if ret.returncode == 0:
                    discovered.setdefault(codec, []).append(cand)
            except Exception:
                pass

    return discovered

def detect_functional_decoders(test_clip_h264=None, test_clip_h265=None):
    """
    Discovers all available software and hardware decoders on the system.
    """
    decoders = {
        "sw_h264": "avdec_h264",
        "sw_h265": "avdec_h265",
        "hw_h264": [],
        "hw_h265": []
    }

    hw_map = try_activate_hardware_vpu()
    decoders["hw_h264"] = hw_map.get("h264", [])
    decoders["hw_h265"] = hw_map.get("h265", [])

    return decoders

# ==============================================================================
# PIPELINE EXECUTION & MEASUREMENT WITH TELEMETRY
# ==============================================================================

def run_decode_test(clip_path, decoder, parser="h264parse", num_frames=120, timeout=15):
    """
    Executes a decode benchmark on clip_path using decoder with full telemetry.
    Returns (measured_fps, telemetry_dict, error_str).
    """
    cmd = [
        'gst-launch-1.0', '-v',
        'filesrc', f'location={clip_path}',
        '!', parser,
        '!', decoder,
        '!', 'fpsdisplaysink', 'video-sink=fakesink', 'text-overlay=false', 'sync=false', 'fps-update-interval=10'
    ]

    tracker = TelemetryTracker()
    tracker.start()

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        wall_time = time.time() - t0
    except subprocess.TimeoutExpired:
        telemetry = tracker.stop()
        return 0.0, telemetry, "Timeout (>15s)"
    except Exception as e:
        telemetry = tracker.stop()
        return 0.0, telemetry, str(e)

    telemetry = tracker.stop()

    if proc.returncode != 0:
        return 0.0, telemetry, f"GStreamer pipeline error (code {proc.returncode})"

    output = proc.stdout + "\n" + proc.stderr
    
    # 1. Look for fpsdisplaysink last-message: average: XXX.XX
    averages = re.findall(r'last-message\s*=\s*rendered:\s*(\d+),\s*dropped:\s*(\d+).*?average:\s*([0-9.]+)', output)
    if averages:
        last_rendered, last_dropped, last_avg = averages[-1]
        try:
            fps_val = float(last_avg)
            if fps_val > 0:
                return fps_val, telemetry, None
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
            return fps_val, telemetry, None

    # 3. Fallback to wall-clock time
    if wall_time > 0.005:
        return (num_frames / wall_time), telemetry, None

    return 60.0, telemetry, None

def print_telemetry_line(decoder_name, fps, telem, is_hw=False):
    type_str = "VPU/GPU HW" if is_hw else "CPU Software"
    fps_status = f"{C_GREEN}ĐẠT 60 FPS{C_RESET}" if fps >= 58.0 else (
        f"{C_YELLOW}ĐẠT 30 FPS{C_RESET}" if fps >= 28.0 else f"{C_RED}CHƯA ĐẠT{C_RESET}"
    )
    temp_str = ""
    if telem.get("temp_peak") is not None:
        delta = f"(+{telem['temp_delta']}°C)" if telem.get("temp_delta") is not None else ""
        temp_str = f" | Nhiệt độ: {telem['temp_peak']}°C {delta}"
    
    gpu_str = ""
    if telem.get("gpu_peak") is not None:
        gpu_str = f" | GPU: {telem['gpu_peak']}%"

    print(f"        ↳ Tốc độ: {C_BOLD}{fps:.1f} FPS{C_RESET} ({fps_status}) | CPU: {telem.get('cpu_avg', 0)}%{temp_str}{gpu_str} [{type_str}]")

# ==============================================================================
# RESOLUTION TIER TESTER WITH VPU AUTO-EVALUATION
# ==============================================================================

def test_resolution_tier(name, res_label, clip_path, codec="h264", default_dec="avdec_h264", hw_decoders=None):
    """
    Tests resolution tier with default decoder. If default decoder does not reach 60fps,
    or if hardware VPU decoders are available, benchmarks hardware VPU decoders as well,
    comparing FPS, CPU usage, temperature, and GPU usage to pick the absolute best configuration.
    """
    parser = "h265parse" if codec == "h265" else "h264parse"
    print(f"\n  ▶ Đo kiểm độ phân giải {C_BOLD}{res_label}{C_RESET}...")

    # Phase 1: Test with standard/default decoder
    print(f"      [1] Thử nghiệm bộ giải mã mặc định/CPU ({C_CYAN}{default_dec}{C_RESET})...")
    fps_def, telem_def, err_def = run_decode_test(clip_path, default_dec, parser=parser)
    
    passed_60_def = fps_def >= 58.0
    passed_30_def = fps_def >= 28.0

    print_telemetry_line(default_dec, fps_def, telem_def, is_hw=False)

    best_decoder = default_dec
    best_fps = fps_def
    best_telem = telem_def
    best_is_hw = False
    
    # Phase 2: If default decoder fails 60 FPS OR if hardware decoders exist, try VPU hardware acceleration!
    tested_hw = []
    
    # Check if we should activate VPU
    if (not passed_60_def) or (hw_decoders and len(hw_decoders) > 0):
        if not hw_decoders:
            log_info(f"Tốc độ giải mã mặc định ({fps_def:.1f} FPS) chưa đạt 60 FPS. Thử kích hoạt VPU phần cứng (Cedrus/V4L2/VA-API)...")
            discovered_map = try_activate_hardware_vpu()
            hw_decoders = discovered_map.get(codec, [])
        
        for hw_dec in hw_decoders:
            if hw_dec == default_dec:
                continue
            print(f"      [2] Thử nghiệm tăng tốc VPU phần cứng ({C_GREEN}{hw_dec}{C_RESET})...")
            fps_hw, telem_hw, err_hw = run_decode_test(clip_path, hw_dec, parser=parser)
            if err_hw:
                log_warn(f"          ↳ VPU {hw_dec} không thể giải mã mẫu này: {err_hw}")
                continue
            
            print_telemetry_line(hw_dec, fps_hw, telem_hw, is_hw=True)
            tested_hw.append({
                "decoder": hw_dec,
                "fps": fps_hw,
                "telemetry": telem_hw
            })

            # Compare and evaluate:
            # Criteria 1: HW passes 60 FPS while default did not -> HW wins!
            if fps_hw >= 58.0 and not passed_60_def:
                best_decoder = hw_dec
                best_fps = fps_hw
                best_telem = telem_hw
                best_is_hw = True
                log_success(f"          ↳ VPU phần cứng ({hw_dec}) đã nâng tốc độ lên {fps_hw:.1f} FPS (Đạt chuẩn 60 FPS)!")
            # Criteria 2: Both pass 60 FPS -> Compare CPU % and Temp!
            elif fps_hw >= 58.0 and passed_60_def:
                cpu_saved = telem_def["cpu_avg"] - telem_hw["cpu_avg"]
                if cpu_saved > 10.0 or (telem_hw.get("temp_peak") and telem_def.get("temp_peak") and telem_hw["temp_peak"] < telem_def["temp_peak"]):
                    best_decoder = hw_dec
                    best_fps = fps_hw
                    best_telem = telem_hw
                    best_is_hw = True
                    log_success(f"          ↳ Cả 2 đều đạt 60 FPS nhưng VPU ({hw_dec}) giảm tải CPU {cpu_saved:.1f}% và nhiệt độ mát hơn. Chọn VPU!")
            # Criteria 3: Neither passes 60 FPS -> Pick whichever is faster & cooler
            elif (not passed_60_def) and (fps_hw > best_fps or (fps_hw >= 28.0 and telem_hw["cpu_avg"] < best_telem["cpu_avg"])):
                best_decoder = hw_dec
                best_fps = fps_hw
                best_telem = telem_hw
                best_is_hw = True

    # Thermal Warning Guard
    thermal_warning = False
    if best_telem.get("temp_peak") and best_telem["temp_peak"] >= 75.0:
        thermal_warning = True
        log_warn(f"Cảnh báo nhiệt độ: Đỉnh nhiệt đạt {best_telem['temp_peak']}°C! Nguy cơ tụt xung (thermal throttle) khi sử dụng lâu dài.")
    elif best_telem.get("cpu_avg", 0) >= 90.0:
        log_warn(f"Cảnh báo tải CPU: CPU hoạt động ở mức {best_telem['cpu_avg']}%, thiết bị tản nhiệt thụ động có thể bị quá nhiệt.")

    return {
        "decoder": best_decoder,
        "is_hw": best_is_hw,
        "fps": round(best_fps, 1),
        "passed_60": best_fps >= 58.0,
        "passed_30": best_fps >= 28.0,
        "telemetry": best_telem,
        "default_telemetry": telem_def,
        "thermal_warning": thermal_warning,
        "tested_hw": tested_hw
    }

# ==============================================================================
# MAIN BENCHMARK ENGINE
# ==============================================================================

def benchmark_hardware():
    """
    Runs the comprehensive video decoding benchmark testing from 4K down to 720p.
    Prioritizes achieving 60 FPS for ultra-smooth AirPlay interaction, with
    telemetry comparison (CPU usage, temperature, GPU) between Software & Hardware VPU.
    """
    cpu = get_cpu_info()
    print(f"\n{C_BOLD}======================================================================{C_RESET}")
    print(f"{C_BOLD}  ⚡ WYSEPLAY DECODER PERFORMANCE BENCHMARK (4K -> 1080p -> 720p){C_RESET}")
    print(f"{C_BOLD}======================================================================{C_RESET}")
    print(f"  • CPU Model:        {C_CYAN}{cpu['model']}{C_RESET}")
    print(f"  • Kiến trúc / Cores: {C_CYAN}{cpu['arch']} ({cpu['cores']} cores){C_RESET}")

    if not shutil.which('gst-launch-1.0'):
        log_warn("Không tìm thấy công cụ GStreamer (gst-launch-1.0). Sử dụng hồ sơ ước tính theo phần cứng CPU...")
        return fallback_profile(cpu)

    # 1. Resolve benchmark clips
    clip_4k = locate_benchmark_file("bench_4k.h265")
    clip_1080p = locate_benchmark_file("bench_1080p.h264")
    clip_720p = locate_benchmark_file("bench_720p.h264")

    if not clip_4k:
        clip_4k = generate_fallback_clip("3840x2160", "/tmp/bench_4k.h265", codec="h265")
    if not clip_1080p:
        log_info("Tạo mẫu H.264 1080p để đo kiểm...")
        clip_1080p = generate_fallback_clip("1920x1080", "/tmp/bench_1080p.h264", codec="h264")
    if not clip_720p:
        log_info("Tạo mẫu H.264 720p để đo kiểm...")
        clip_720p = generate_fallback_clip("1280x720", "/tmp/bench_720p.h264", codec="h264")

    if not clip_720p and not clip_1080p and not clip_4k:
        log_warn("Không thể tạo tệp kiểm thử video. Sử dụng ước lượng thông số dựa trên CPU...")
        return fallback_profile(cpu)

    # 2. Discover available decoders
    decoders = detect_functional_decoders(clip_1080p or clip_720p, clip_4k)
    hw_h264 = decoders["hw_h264"]
    hw_h265 = decoders["hw_h265"]

    if hw_h264 or hw_h265:
        log_success(f"Phát hiện VPU/GPU tăng tốc phần cứng: H.264 ({', '.join(hw_h264) or 'None'}), H.265 ({', '.join(hw_h265) or 'None'})")
    else:
        log_info("Chưa phát hiện VPU phần cứng sẵn sàng. Sẽ đo kiểm CPU trước và tự kích hoạt VPU nếu cần.")

    # 3. Execute Benchmarks from 4K down
    results = {}

    # Benchmark 4K (3840x2160, H.265)
    if clip_4k:
        default_4k_dec = hw_h265[0] if hw_h265 else decoders["sw_h265"]
        results["4k"] = test_resolution_tier(
            "4k", "4K UHD (3840x2160, H.265)", clip_4k,
            codec="h265", default_dec=default_4k_dec, hw_decoders=hw_h265
        )

    # Benchmark 1080p (1920x1080, H.264)
    if clip_1080p:
        default_1080_dec = decoders["sw_h264"]
        results["1080p"] = test_resolution_tier(
            "1080p", "1080p Full HD (1920x1080, H.264)", clip_1080p,
            codec="h264", default_dec=default_1080_dec, hw_decoders=hw_h264
        )

    # Benchmark 720p (1280x720, H.264)
    if clip_720p:
        default_720_dec = decoders["sw_h264"]
        results["720p"] = test_resolution_tier(
            "720p", "720p HD Ready (1280x720, H.264)", clip_720p,
            codec="h264", default_dec=default_720_dec, hw_decoders=hw_h264
        )

    # 4. Profile Decision Logic (Goal: Max 60 FPS, Thermally Safe, Hardware VPU Prioritized)
    p4k = results.get("4k", {"passed_60": False, "passed_30": False, "fps": 0.0, "decoder": decoders["sw_h265"], "telemetry": {}, "is_hw": False})
    p1080 = results.get("1080p", {"passed_60": False, "passed_30": False, "fps": 0.0, "decoder": decoders["sw_h264"], "telemetry": {}, "is_hw": False})
    p720 = results.get("720p", {"passed_60": False, "passed_30": False, "fps": 0.0, "decoder": decoders["sw_h264"], "telemetry": {}, "is_hw": False})

    # Decision tree:
    if p4k["passed_60"] and not p4k.get("thermal_warning"):
        hw_tag = " [VPU Phần cứng]" if p4k["is_hw"] else " [CPU]"
        selected = {
            "resolution": "3840x2160",
            "width": 3840,
            "height": 2160,
            "max_fps": 60,
            "h265": True,
            "tier": f"4K Ultra HD @ 60 FPS{hw_tag}",
            "reason": f"Giải mã 4K H.265 đạt {p4k['fps']} FPS (vượt ngưỡng 60 FPS) qua {p4k['decoder']}. Hỗ trợ 4K native và downscale siêu nét cho màn hình 2K/1080p."
        }
        chosen_decoder = p4k["decoder"]
    elif p1080["passed_60"] and not p1080.get("thermal_warning"):
        hw_tag = " [VPU Phần cứng]" if p1080["is_hw"] else " [CPU]"
        selected = {
            "resolution": "1920x1080",
            "width": 1920,
            "height": 1080,
            "max_fps": 60,
            "h265": False,
            "tier": f"Full HD @ 60 FPS{hw_tag}",
            "reason": f"1080p đạt {p1080['fps']} FPS chuẩn 60 FPS qua {p1080['decoder']} (CPU: {p1080['telemetry'].get('cpu_avg', 0)}%). Đạt độ nét và độ mượt tối đa."
        }
        chosen_decoder = p1080["decoder"]
    elif p720["passed_60"]:
        hw_tag = " [VPU Phần cứng]" if p720["is_hw"] else " [CPU]"
        thermal_note = " (1080p bị cảnh báo quá tải/quá nhiệt)" if p1080.get("thermal_warning") else ""
        selected = {
            "resolution": "1280x720",
            "width": 1280,
            "height": 720,
            "max_fps": 60,
            "h265": False,
            "tier": f"HD Ready @ 60 FPS{hw_tag}",
            "reason": f"Ưu tiên 720p @ 60 FPS ({p720['fps']} FPS qua {p720['decoder']}){thermal_note} để bảo đảm trải nghiệm vuốt chạm phản hồi tức thì, máy mát và không giật lag."
        }
        chosen_decoder = p720["decoder"]
    elif p4k["passed_30"]:
        selected = {
            "resolution": "3840x2160",
            "width": 3840,
            "height": 2160,
            "max_fps": 30,
            "h265": True,
            "tier": f"4K Ultra HD @ 30 FPS",
            "reason": f"Phần cứng giải mã 4K ở mức 30 FPS ổn định ({p4k['fps']} FPS) qua {p4k['decoder']}."
        }
        chosen_decoder = p4k["decoder"]
    elif p1080["passed_30"]:
        selected = {
            "resolution": "1920x1080",
            "width": 1920,
            "height": 1080,
            "max_fps": 30,
            "h265": False,
            "tier": f"Full HD @ 30 FPS",
            "reason": f"Phần cứng không duy trì được 60 FPS. Chọn 1080p @ 30 FPS ({p1080['fps']} FPS qua {p1080['decoder']}) để bảo đảm độ sắc nét."
        }
        chosen_decoder = p1080["decoder"]
    elif p720["passed_30"]:
        selected = {
            "resolution": "1280x720",
            "width": 1280,
            "height": 720,
            "max_fps": 30,
            "h265": False,
            "tier": f"HD Ready @ 30 FPS",
            "reason": f"Cấu hình 720p @ 30 FPS ({p720['fps']} FPS) giúp thiết bị hoạt động mát mẻ, không drop frame."
        }
        chosen_decoder = p720["decoder"]
    else:
        selected = {
            "resolution": "960x540",
            "width": 960,
            "height": 540,
            "max_fps": 30,
            "h265": False,
            "tier": "SD 540p @ 30 FPS",
            "reason": "Phần cứng siêu nhẹ, giảm tải tối đa để tránh quá nhiệt."
        }
        chosen_decoder = p720.get("decoder", "avdec_h264")

    profile_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu": cpu,
        "decoder": chosen_decoder,
        "video_sink": "autovideosink",
        "benchmarks": results,
        "selected_profile": selected
    }

    return profile_data

def fallback_profile(cpu):
    """Fallback profile based purely on core count if benchmark files unavailable."""
    if cpu["cores"] >= 8:
        res, fps, h265 = "3840x2160", 60, True
        tier = "4K Ultra HD @ 60 FPS"
    elif cpu["cores"] >= 4 and cpu["arch"] in ("x86_64", "amd64"):
        res, fps, h265 = "1920x1080", 60, False
        tier = "Full HD @ 60 FPS"
    elif cpu["cores"] >= 4:
        res, fps, h265 = "1280x720", 60, False
        tier = "HD Ready @ 60 FPS"
    else:
        res, fps, h265 = "1280x720", 30, False
        tier = "HD Ready @ 30 FPS"

    w, h = res.split('x')
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu": cpu,
        "decoder": "avdec_h265" if h265 else "avdec_h264",
        "video_sink": "autovideosink",
        "benchmarks": {},
        "selected_profile": {
            "resolution": res,
            "width": int(w),
            "height": int(h),
            "max_fps": fps,
            "h265": h265,
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
            f"WYSEPLAY_H265={'true' if sp.get('h265') else 'false'}",
            f"WYSEPLAY_DECODER={profile_data.get('decoder', 'avdec_h264')}",
            f"WYSEPLAY_VIDEOSINK={profile_data.get('video_sink', 'autovideosink')}",
            f"WYSEPLAY_TIER=\"{sp['tier']}\"",
            ""
        ]
        with open(etc_path, "w") as f:
            f.write("\n".join(lines))
        log_success(f"Đã cập nhật tệp cấu hình hệ thống: {C_BOLD}{etc_path}{C_RESET}")
    except Exception:
        pass

def print_summary(profile_data):
    """Prints a styled verdict summary with telemetry details."""
    sp = profile_data["selected_profile"]
    dec = profile_data["decoder"]

    print(f"\n{C_BOLD}----------------------------------------------------------------------{C_RESET}")
    print(f"{C_BOLD}{C_GREEN}  🎉 KẾT QUẢ TỐI ƯU HÓA CẤU HÌNH AIRPLAY (UXPLAY):{C_RESET}")
    print(f"{C_BOLD}----------------------------------------------------------------------{C_RESET}")
    print(f"  • Cấu hình lựa chọn:  {C_BOLD}{C_GREEN}{sp['tier']}{C_RESET}")
    print(f"  • Độ phân giải tối đa: {C_CYAN}{sp['resolution']}{C_RESET}")
    print(f"  • Tốc độ khung hình:   {C_CYAN}{sp['max_fps']} FPS{C_RESET}")
    print(f"  • Chuẩn nén (Codec):  {C_CYAN}{'H.265 / HEVC (4K)' if sp.get('h265') else 'H.264 / AVC'}{C_RESET}")
    print(f"  • Bộ giải mã video:   {C_CYAN}{dec}{C_RESET}")
    print(f"  • Phân tích lý do:     {C_GRAY}{sp['reason']}{C_RESET}")

    # Telemetry report if available
    bmarks = profile_data.get("benchmarks", {})
    if bmarks:
        print(f"\n{C_BOLD}  📊 BẢNG SO SÁNH HIỆU NĂNG & NHIỆT ĐỘ CHI TIẾT:{C_RESET}")
        print(f"  {'Độ phân giải':<14} | {'Bộ giải mã':<15} | {'FPS':<7} | {'CPU Load':<9} | {'Nhiệt độ (Đỉnh/Δ)':<18} | {'Đánh giá'}")
        print(f"  {'-'*14}-+-{'-'*15}-+-{'-'*7}-+-{'-'*9}-+-{'-'*18}-+-{'-'*18}")
        for res_key, res_data in bmarks.items():
            dec_name = res_data.get("decoder", "unknown")
            fps = res_data.get("fps", 0.0)
            telem = res_data.get("telemetry", {})
            cpu_val = f"{telem.get('cpu_avg', 0)}%"
            t_peak = telem.get("temp_peak")
            t_delta = telem.get("temp_delta")
            temp_val = f"{t_peak}°C (+{t_delta}°C)" if t_peak is not None else "N/A"
            status = "✔ Đạt 60fps" if res_data.get("passed_60") else ("⚠ 30fps" if res_data.get("passed_30") else "✖ Kém")
            print(f"  {res_key:<14} | {dec_name:<15} | {fps:<7.1f} | {cpu_val:<9} | {temp_val:<18} | {status}")

    print(f"{C_BOLD}----------------------------------------------------------------------{C_RESET}\n")

def main():
    parser = argparse.ArgumentParser(description="WysePlay Hardware Decoder Benchmark with VPU & Thermal Telemetry")
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
