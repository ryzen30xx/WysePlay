#!/bin/bash
# ==============================================================================
# WysePlay - Apple TV-style AirPlay Receiver Appliance
# Installer & Environment Provisioning Script
# Repository: https://github.com/ryzen30xx/WysePlay
# ==============================================================================

set -euo pipefail

# --- Visual Styling & Colors ---
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_BLUE='\033[38;5;39m'
C_CYAN='\033[38;5;45m'
C_GREEN='\033[38;5;82m'
C_YELLOW='\033[38;5;214m'
C_RED='\033[38;5;196m'
C_GRAY='\033[38;5;244m'

log_banner() {
    cat << "BANNER_EOF"

  ██╗    ██╗██╗   ██╗███████╗███████╗██████╗ ██╗      █████╗ ██╗   ██╗
  ██║    ██║╚██╗ ██╔╝██╔════╝██╔════╝██╔══██╗██║     ██╔══██╗╚██╗ ██╔╝
  ██║ █╗ ██║ ╚████╔╝ ███████╗█████╗  ██████╔╝██║     ███████║ ╚████╔╝ 
  ██║███╗██║  ╚██╔╝  ╚════██║██╔══╝  ██╔═══╝ ██║     ██╔══██║  ╚██╔╝  
  ╚███╔███╔╝   ██║   ███████║███████╗██║     ███████╗██║  ██║   ██║   
   ╚══╝╚══╝    ╚═╝   ╚══════╝╚══════╝╚═╝     ╚══════╝╚═╝  ╚═╝   ╚═╝   
             Apple TV-style AirPlay Receiver for Thin Clients
BANNER_EOF
    echo -e "${C_GRAY}──────────────────────────────────────────────────────────────────────${C_RESET}"
}

log_info()    { echo -e "${C_BLUE}ℹ  ${1}${C_RESET}"; }
log_step()    { echo -e "\n${C_BOLD}${C_CYAN}▶  ${1}${C_RESET}"; }
log_success() { echo -e "${C_GREEN}✔  ${1}${C_RESET}"; }
log_warn()    { echo -e "${C_YELLOW}⚠  ${1}${C_RESET}"; }
log_error()   { echo -e "${C_RED}✖  ${1}${C_RESET}" >&2; }

# --- Arguments & Flags ---
AUTO_START=true
SPECIFIED_USER=""
REPO_URL="https://github.com/ryzen30xx/WysePlay.git"
RAW_BASE_URL="https://raw.githubusercontent.com/ryzen30xx/WysePlay/main"
TEMP_DIR=""

show_help() {
    cat << HELP_EOF
WysePlay Installer

Usage:
  sudo bash install.sh [options]
  curl -fsSL ${RAW_BASE_URL}/install.sh | sudo bash -s -- [options]

Options:
  --user <username>   Specify target Linux user (default: current sudo user or UID 1000)
  --no-start          Do not start the airplay-kiosk service immediately after installation
  -h, --help          Show this help message
HELP_EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)
            SPECIFIED_USER="$2"
            shift 2
            ;;
        --no-start)
            AUTO_START=false
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            log_warn "Tham số không xác định: $1"
            shift
            ;;
    esac
done

cleanup() {
    if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
        rm -rf "${TEMP_DIR}"
    fi
}
trap cleanup EXIT INT TERM

# ==============================================================================
# PRE-FLIGHT CHECKS (KIỂM TRA MÔI TRƯỜNG HỆ THỐNG TRƯỚC KHI CÀI ĐẶT)
# ==============================================================================

run_preflight_checks() {
    log_step "Kiểm tra môi trường hệ thống (Pre-flight Checks)..."

    # 1. Check Root Privileges
    if [[ "$EUID" -ne 0 ]]; then
        log_error "Lỗi: Script yêu cầu quyền root hoặc sudo để cấu hình hệ thống."
        echo -e "Vui lòng chạy lại với: ${C_BOLD}sudo bash install.sh${C_RESET} hoặc ${C_BOLD}curl -fsSL ... | sudo bash${C_RESET}"
        exit 1
    fi
    log_success "Quyền Root: Đã xác thực"

    # 2. Check Operating System
    if [[ ! -f /etc/os-release ]]; then
        log_error "Lỗi: Không tìm thấy tệp /etc/os-release. Không thể nhận diện hệ điều hành."
        exit 1
    fi

    # shellcheck source=/dev/null
    source /etc/os-release
    OS_ID="${ID:-}"
    OS_LIKE="${ID_LIKE:-}"
    OS_NAME="${PRETTY_NAME:-$NAME}"

    IS_DEBIAN_BASED=false
    for match in debian ubuntu raspbian armbian linuxmint pop kali; do
        if [[ "$OS_ID" == *"$match"* ]] || [[ "$OS_LIKE" == *"$match"* ]]; then
            IS_DEBIAN_BASED=true
            break
        fi
    done

    if [[ "$IS_DEBIAN_BASED" != true ]]; then
        log_error "Lỗi hệ điều hành: ${OS_NAME} không được hỗ trợ chính thức."
        log_error "WysePlay hiện tối ưu hóa cho các bản phân phối Debian/Ubuntu/Raspberry Pi OS (sử dụng apt)."
        exit 1
    fi
    log_success "Hệ điều hành: ${OS_NAME} (Hỗ trợ tốt)"

    # 3. Check Architecture
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64|aarch64|arm64|armv7l|i686)
            log_success "Kiến trúc CPU: ${ARCH} (Tương thích)"
            ;;
        *)
            log_warn "Kiến trúc CPU ${ARCH} có thể chưa được kiểm thử toàn diện."
            ;;
    esac

    # 4. Check Systemd Presence
    if ! command -v systemctl >/dev/null 2>&1; then
        log_error "Lỗi: Không tìm thấy systemd (systemctl). WysePlay yêu cầu systemd để quản lý kiosk service."
        exit 1
    fi
    log_success "Init System: systemd (Khả dụng)"

    # 5. Check Disk Space (Min 500MB free on /)
    FREE_SPACE_MB=$(df -m / | awk 'NR==2 {print $4}')
    if [[ "$FREE_SPACE_MB" -lt 500 ]]; then
        log_warn "Dung lượng ổ đĩa còn trống thấp (${FREE_SPACE_MB}MB). Khuyến nghị tối thiểu 500MB trống."
    else
        log_success "Dung lượng đĩa: ${FREE_SPACE_MB}MB khả dụng"
    fi

    # 6. Check Target User
    TARGET_USER=""
    if [[ -n "$SPECIFIED_USER" ]]; then
        if id "$SPECIFIED_USER" >/dev/null 2>&1; then
            TARGET_USER="$SPECIFIED_USER"
        else
            log_error "Lỗi: Người dùng '$SPECIFIED_USER' được chỉ định không tồn tại."
            exit 1
        fi
    elif [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        TARGET_USER="${SUDO_USER}"
    else
        # Find the first user with UID >= 1000
        TARGET_USER=$(awk -F: '$3 >= 1000 && $3 < 65000 {print $1; exit}' /etc/passwd || true)
        if [[ -z "$TARGET_USER" ]]; then
            TARGET_USER="root"
        fi
    fi

    TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
    TARGET_GROUP=$(id -gn "$TARGET_USER")
    log_success "Người dùng mục tiêu: ${TARGET_USER} (Home: ${TARGET_HOME})"

    # 7. Check Internet Connectivity
    log_info "Kiểm tra kết nối mạng Internet..."
    if ! curl -s --connect-timeout 4 https://deb.debian.org >/dev/null 2>&1 && \
       ! curl -s --connect-timeout 4 https://archive.ubuntu.com >/dev/null 2>&1 && \
       ! ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1; then
        log_warn "Không thể kết nối Internet ra ngoài. Việc cài đặt các gói phụ thuộc apt có thể gặp lỗi nếu chưa cấu hình offline mirror."
    else
        log_success "Kết nối Internet: Sẵn sàng"
    fi
}

# ==============================================================================
# RESOLVE SOURCE ASSETS & CODE
# ==============================================================================

resolve_source_directory() {
    log_step "Chuẩn bị mã nguồn và tài nguyên WysePlay..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
    
    # Check if we are running directly from inside a cloned repository
    if [[ -d "${SCRIPT_DIR}/src" && -d "${SCRIPT_DIR}/assets" && -d "${SCRIPT_DIR}/fonts" ]]; then
        SOURCE_DIR="${SCRIPT_DIR}"
        log_success "Sử dụng mã nguồn tại chỗ từ: ${SOURCE_DIR}"
    else
        # We are running via piped curl or standalone script, need to fetch repository
        log_info "Đang tải xuống bộ mã nguồn mới nhất từ GitHub (${REPO_URL})..."
        TEMP_DIR=$(mktemp -d /tmp/wyseplay_install_XXXXXX)

        if command -v git >/dev/null 2>&1; then
            git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}"
        else
            log_info "Cài đặt git tạm thời để tải mã nguồn..."
            apt-get update -qq && apt-get install -y -qq git
            git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}"
        fi

        SOURCE_DIR="${TEMP_DIR}"
        log_success "Đã tải mã nguồn thành công về: ${SOURCE_DIR}"
    fi
}

# ==============================================================================
# INSTALL PACKAGES
# ==============================================================================

install_dependencies() {
    log_step "Cập nhật apt và cài đặt các thư viện phụ thuộc..."

    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y

    PACKAGES=(
        xserver-xorg
        xserver-xorg-legacy
        xinit
        openbox
        x11-xserver-utils
        x11-utils
        xinput
        xdotool
        unclutter
        feh
        scrot
        python3
        python3-pil
        python3-pil.imagetk
        python3-tk
        python3-pyudev
        network-manager
        avahi-daemon
        libnss-mdns
        uxplay
        gstreamer1.0-plugins-base
        gstreamer1.0-plugins-good
        gstreamer1.0-plugins-bad
        gstreamer1.0-libav
        gstreamer1.0-gl
        gstreamer1.0-x
        gstreamer1.0-alsa
        gstreamer1.0-tools
        fontconfig
        pulseaudio
    )

    log_info "Cài đặt các gói: ${PACKAGES[*]}"
    apt-get install -y --no-install-recommends "${PACKAGES[@]}"

    # Configure Xwrapper for rootless Xorg console access under systemd
    mkdir -p /etc/X11
    cat << 'XWRAP_EOF' > /etc/X11/Xwrapper.config
allowed_users=anybody
needs_root_rights=yes
XWRAP_EOF

    log_success "Đã hoàn thành cài đặt toàn bộ gói phụ thuộc hệ thống."
}

# ==============================================================================
# INSTALL APPLE SAN FRANCISCO FONTS
# ==============================================================================

install_apple_fonts() {
    log_step "Cài đặt bộ phông chữ chuẩn Apple San Francisco Pro..."

    FONT_DEST="/usr/local/share/fonts/apple-sf-pro"
    mkdir -p "${FONT_DEST}"

    if [[ -d "${SOURCE_DIR}/fonts" ]]; then
        cp -f "${SOURCE_DIR}/fonts"/*.ttf "${FONT_DEST}/" 2>/dev/null || true
        chmod 644 "${FONT_DEST}"/*.ttf 2>/dev/null || true
        fc-cache -fv "${FONT_DEST}" >/dev/null 2>&1
        log_success "Đã cài đặt phông chữ SF Pro vào: ${FONT_DEST}"
    else
        log_warn "Không tìm thấy thư mục fonts/ trong source. Bỏ qua bước cài phông chữ."
    fi
}

# ==============================================================================
# DEPLOY APPLICATION FILES TO /opt/airplay
# ==============================================================================

deploy_application() {
    log_step "Triển khai mã nguồn WysePlay vào /opt/airplay..."

    APP_DIR="/opt/airplay"
    mkdir -p "${APP_DIR}/assets"

    # Copy Python scripts & launchers
    cp -f "${SOURCE_DIR}/src"/*.py "${APP_DIR}/"
    cp -f "${SOURCE_DIR}/src"/*.sh "${APP_DIR}/"
    chmod +x "${APP_DIR}"/*.py "${APP_DIR}"/*.sh

    # Copy SF Symbol PNG Assets
    if [[ -d "${SOURCE_DIR}/assets" ]]; then
        cp -f "${SOURCE_DIR}/assets"/*.png "${APP_DIR}/assets/" 2>/dev/null || true
        chmod 644 "${APP_DIR}/assets"/*.png 2>/dev/null || true
    fi

    # Copy Benchmark Video Assets
    if [[ -d "${SOURCE_DIR}/assets/benchmark" ]]; then
        mkdir -p "${APP_DIR}/assets/benchmark"
        cp -f "${SOURCE_DIR}/assets/benchmark"/* "${APP_DIR}/assets/benchmark/" 2>/dev/null || true
        chmod 644 "${APP_DIR}/assets/benchmark"/* 2>/dev/null || true
    fi

    # Set ownership
    chown -R "${TARGET_USER}:${TARGET_GROUP}" "${APP_DIR}"
    log_success "Đã triển khai toàn bộ scripts và assets vào: ${APP_DIR}"
}

# ==============================================================================
# BENCHMARK HARDWARE DECODING (CPU/GPU)
# ==============================================================================

benchmark_hardware_decoding() {
    log_step "Đo kiểm hiệu năng giải mã phần cứng CPU/GPU (Mục tiêu 60 FPS)..."

    if [[ -f "${APP_DIR}/benchmark_decoder.py" ]]; then
        python3 "${APP_DIR}/benchmark_decoder.py" --force
    else
        log_warn "Không tìm thấy benchmark_decoder.py. Bỏ qua bước đo kiểm."
    fi
}

# ==============================================================================
# CONFIGURE USER ENVIRONMENT (OPENBOX & XRESOURCES)
# ==============================================================================

configure_user_environment() {
    log_step "Cấu hình môi trường đồ họa người dùng (${TARGET_USER})..."

    # Add user to required hardware groups
    for grp in video audio input netdev tty; do
        if getent group "$grp" >/dev/null 2>&1; then
            usermod -a -G "$grp" "$TARGET_USER" || true
        fi
    done

    # Openbox Configuration
    OPENBOX_DIR="${TARGET_HOME}/.config/openbox"
    mkdir -p "${OPENBOX_DIR}"
    if [[ -f "${SOURCE_DIR}/config/rc.xml" ]]; then
        cp -f "${SOURCE_DIR}/config/rc.xml" "${OPENBOX_DIR}/rc.xml"
    fi

    # Xresources (Subpixel Anti-Aliasing for crisp Apple typography)
    if [[ -f "${SOURCE_DIR}/config/Xresources" ]]; then
        cp -f "${SOURCE_DIR}/config/Xresources" "${TARGET_HOME}/.Xresources"
    fi

    # Fix ownership
    chown -R "${TARGET_USER}:${TARGET_GROUP}" "${TARGET_HOME}/.config" "${TARGET_HOME}/.Xresources" 2>/dev/null || true
    log_success "Đã cấu hình Openbox và Xresources cho: ${TARGET_USER}"
}

# ==============================================================================
# CONFIGURE SYSTEMD SERVICE
# ==============================================================================

configure_systemd_service() {
    log_step "Cấu hình systemd service tự khởi động cùng hệ thống..."

    SERVICE_SRC="${SOURCE_DIR}/config/airplay-kiosk.service"
    SERVICE_DEST="/etc/systemd/system/airplay-kiosk.service"

    if [[ -f "${SERVICE_SRC}" ]]; then
        sed -e "s|@TARGET_USER@|${TARGET_USER}|g" \
            -e "s|@TARGET_HOME@|${TARGET_HOME}|g" \
            "${SERVICE_SRC}" > "${SERVICE_DEST}"
        
        chmod 644 "${SERVICE_DEST}"
        systemctl daemon-reload
        systemctl enable airplay-kiosk.service
        
        # Mask systemd sleep/suspend so appliance server runs 24/7 (monitor sleeps via DPMS)
        systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1 || true
        
        log_success "Đã kích hoạt dịch vụ: airplay-kiosk.service"

        if [[ "$AUTO_START" == true ]]; then
            log_info "Đang khởi động dịch vụ WysePlay Kiosk..."
            systemctl restart airplay-kiosk.service || true
            sleep 2
            if systemctl is-active --quiet airplay-kiosk.service; then
                log_success "Dịch vụ airplay-kiosk đang chạy thành công!"
            else
                log_warn "Dịch vụ đã được kích hoạt. Bạn có thể kiểm tra trạng thái bằng: systemctl status airplay-kiosk"
            fi
        fi
    else
        log_error "Lỗi: Không tìm thấy file mẫu cấu hình service: ${SERVICE_SRC}"
        exit 1
    fi
}

# ==============================================================================
# MAIN INSTALLER ENTRYPOINT
# ==============================================================================

main() {
    log_banner
    run_preflight_checks
    resolve_source_directory
    install_dependencies
    install_apple_fonts
    deploy_application
    benchmark_hardware_decoding
    configure_user_environment
    configure_systemd_service

    echo ""
    echo -e "${C_BOLD}${C_GREEN}======================================================================${C_RESET}"
    echo -e "${C_BOLD}${C_GREEN}  🎉 CHÚC MỪNG! WYSEPLAY ĐÃ ĐƯỢC CÀI ĐẶT THÀNH CÔNG!${C_RESET}"
    echo -e "${C_BOLD}${C_GREEN}======================================================================${C_RESET}"
    echo ""
    echo -e "${C_BOLD}Thông tin thiết bị:${C_RESET}"
    echo -e "  • Thư mục cài đặt:   ${C_CYAN}/opt/airplay${C_RESET}"
    echo -e "  • Người dùng Kiosk:   ${C_CYAN}${TARGET_USER}${C_RESET}"
    echo -e "  • Tên dịch vụ:        ${C_CYAN}airplay-kiosk.service${C_RESET}"
    if [[ -f /opt/airplay/hw_profile.json ]]; then
        PROFILE_INFO=$(python3 -c "
import json
try:
    with open('/opt/airplay/hw_profile.json') as f:
        d = json.load(f)
        sp = d.get('selected_profile', {})
        codec = 'H.265' if sp.get('h265') else 'H.264'
        print(f\"{sp.get('tier', 'Custom')} ({sp.get('resolution', '')} @ {sp.get('max_fps', 60)}fps, {codec}, {d.get('decoder', 'avdec')})\")
except Exception:
    pass
" 2>/dev/null || true)
        if [[ -n "$PROFILE_INFO" ]]; then
            echo -e "  • Cấu hình AirPlay:   ${C_GREEN}${PROFILE_INFO}${C_RESET}"
        fi
    fi
    echo ""
    echo -e "${C_BOLD}Các lệnh điều khiển hữu ích:${C_RESET}"
    echo -e "  • Kiểm tra trạng thái: ${C_YELLOW}sudo systemctl status airplay-kiosk${C_RESET}"
    echo -e "  • Xem nhật ký (logs):  ${C_YELLOW}sudo journalctl -u airplay-kiosk -f${C_RESET}"
    echo -e "  • Khởi động lại:       ${C_YELLOW}sudo systemctl restart airplay-kiosk${C_RESET}"
    echo -e "  • Dừng dịch vụ:        ${C_YELLOW}sudo systemctl stop airplay-kiosk${C_RESET}"
    echo ""
    echo -e "${C_GRAY}Màn hình TV/Monitor hiện đã sẵn sàng nhận kết nối AirPlay từ iPhone, iPad và Mac!${C_RESET}"
    echo ""
}

main "$@"
