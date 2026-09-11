#!/bin/bash
# ==============================================================================
# WysePlay - Apple TV-style AirPlay Receiver Appliance
# Uninstaller & System Restoration Script
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
             Gỡ Cài Đặt WysePlay & Khôi Phục Hệ Thống
BANNER_EOF
    echo -e "${C_GRAY}──────────────────────────────────────────────────────────────────────${C_RESET}"
}

log_info()    { echo -e "${C_BLUE}ℹ  ${1}${C_RESET}"; }
log_step()    { echo -e "\n${C_BOLD}${C_CYAN}▶  ${1}${C_RESET}"; }
log_success() { echo -e "${C_GREEN}✔  ${1}${C_RESET}"; }
log_warn()    { echo -e "${C_YELLOW}⚠  ${1}${C_RESET}"; }
log_error()   { echo -e "${C_RED}✖  ${1}${C_RESET}" >&2; }

PURGE_PACKAGES=false
ASSUME_YES=false

show_help() {
    cat << HELP_EOF
WysePlay Uninstaller

Sử dụng:
  sudo bash uninstall.sh [tùy chọn]
  curl -fsSL https://raw.githubusercontent.com/ryzen30xx/WysePlay/main/uninstall.sh | sudo bash -s -- [tùy chọn]

Tùy chọn:
  --purge-packages   Gỡ bỏ cả các gói thư viện APT đã cài đặt (uxplay, openbox, gstreamer...)
  -y, --yes          Tự động xác nhận gỡ cài đặt không cần hỏi lại
  -h, --help         Hiển thị trợ giúp này
HELP_EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge-packages)
            PURGE_PACKAGES=true
            shift
            ;;
        -y|--yes)
            ASSUME_YES=true
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

# 1. Check Root Privileges
if [[ "$EUID" -ne 0 ]]; then
    log_error "Lỗi: Script yêu cầu quyền root hoặc sudo."
    echo -e "Vui lòng chạy lại với: ${C_BOLD}sudo bash uninstall.sh${C_RESET}"
    exit 1
fi

log_banner

# Confirm uninstallation if not assume-yes
if [[ "$ASSUME_YES" != true ]]; then
    echo -e "${C_YELLOW}Cảnh báo: Thao tác này sẽ gỡ bỏ hoàn toàn dịch vụ WysePlay Kiosk và các tệp liên quan.${C_RESET}"
    if [[ "$PURGE_PACKAGES" == true ]]; then
        echo -e "${C_RED}Lựa chọn --purge-packages sẽ gỡ bỏ cả các gói apt (uxplay, openbox, gstreamer...).${C_RESET}"
    fi
    confirm=""
    if [[ -t 0 ]]; then
        read -rp "Bạn có chắc chắn muốn gỡ cài đặt WysePlay? (y/N): " confirm
    elif [[ -e /dev/tty ]]; then
        read -rp "Bạn có chắc chắn muốn gỡ cài đặt WysePlay? (y/N): " confirm < /dev/tty
    else
        log_warn "Không phát hiện terminal tương tác (non-interactive). Đang tiếp tục gỡ cài đặt..."
        confirm="y"
    fi
    if [[ ! "$confirm" =~ ^[yY]([eE][sS])?$ ]]; then
        log_info "Đã hủy thao tác gỡ cài đặt."
        exit 0
    fi
fi

# 2. Stop and Disable systemd service
log_step "Dừng và vô hiệu hóa dịch vụ airplay-kiosk.service..."
if systemctl is-active --quiet airplay-kiosk.service 2>/dev/null; then
    systemctl stop airplay-kiosk.service || true
    log_success "Đã dừng dịch vụ airplay-kiosk"
fi

if systemctl is-enabled --quiet airplay-kiosk.service 2>/dev/null; then
    systemctl disable airplay-kiosk.service || true
    log_success "Đã vô hiệu hóa tự khởi động airplay-kiosk"
fi

# Kill any leftover kiosk/uxplay processes
pkill -9 -f 'start_kiosk.sh|kiosk_manager.py|wifi_gui.py|uxplay' 2>/dev/null || true

# Remove systemd service file
if [[ -f /etc/systemd/system/airplay-kiosk.service ]]; then
    rm -f /etc/systemd/system/airplay-kiosk.service
    systemctl daemon-reload
    log_success "Đã xóa tệp cấu hình: /etc/systemd/system/airplay-kiosk.service"
fi

# 3. Restore systemd power management targets & TTY1
log_step "Khôi phục trạng thái quản lý nguồn điện & TTY1..."
systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1 || true
log_success "Đã mở khóa (unmask) chế độ Sleep / Suspend / Hibernate"

systemctl enable --now getty@tty1.service >/dev/null 2>&1 || true
log_success "Đã khôi phục dịch vụ bàn điều khiển getty@tty1"

# 4. Remove WysePlay Application Files
log_step "Xóa tệp chương trình và tài nguyên ứng dụng..."
if [[ -d /opt/airplay ]]; then
    rm -rf /opt/airplay
    log_success "Đã xóa thư mục ứng dụng: /opt/airplay"
fi

if [[ -f /etc/wyseplay.conf ]]; then
    rm -f /etc/wyseplay.conf
    log_success "Đã xóa cấu hình: /etc/wyseplay.conf"
fi

# Remove temporary files
rm -f /tmp/airplay_streaming /tmp/uxplay.log /tmp/kiosk.log /tmp/sc_*.png /tmp/utm_*.png 2>/dev/null || true
log_success "Đã dọn dẹp các tệp tạm thời trong /tmp"

# 5. Remove Apple Fonts
log_step "Xóa phông chữ Apple San Francisco Pro..."
if [[ -d /usr/local/share/fonts/apple-sf-pro ]]; then
    rm -rf /usr/local/share/fonts/apple-sf-pro
    fc-cache -f 2>/dev/null || true
    log_success "Đã gỡ bỏ phông chữ Apple SF Pro và làm mới font cache"
fi

# 6. Remove X11 Xwrapper config
if [[ -f /etc/X11/Xwrapper.config ]]; then
    rm -f /etc/X11/Xwrapper.config
    log_success "Đã xóa: /etc/X11/Xwrapper.config"
fi

# 7. Clean User Environment Configs (Openbox & Xresources)
log_step "Dọn dẹp cấu hình giao diện người dùng..."
TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
    TARGET_USER=$(awk -F: '$3 >= 1000 && $3 < 65000 {print $1; exit}' /etc/passwd || true)
fi

if [[ -n "$TARGET_USER" ]]; then
    TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
    if [[ -d "${TARGET_HOME}/.config/openbox" ]]; then
        # Check if rc.xml was generated by WysePlay
        if grep -qi "WifiKiosk\|airplay" "${TARGET_HOME}/.config/openbox/rc.xml" 2>/dev/null; then
            rm -f "${TARGET_HOME}/.config/openbox/rc.xml"
            log_success "Đã xóa tệp rc.xml tùy biến của WysePlay trong: ${TARGET_HOME}/.config/openbox"
        fi
    fi
    if [[ -f "${TARGET_HOME}/.Xresources" ]]; then
        rm -f "${TARGET_HOME}/.Xresources"
        log_success "Đã xóa tệp: ${TARGET_HOME}/.Xresources"
    fi
fi

# 8. Optional: Purge APT Packages
if [[ "$PURGE_PACKAGES" == true ]]; then
    log_step "Gỡ bỏ các gói thư viện APT đã cài đặt theo yêu cầu..."
    export DEBIAN_FRONTEND=noninteractive
    PACKAGES=(
        uxplay
        openbox
        unclutter
        xdotool
        feh
        scrot
        python3-pyudev
    )
    apt-get remove --purge -y "${PACKAGES[@]}" 2>/dev/null || true
    apt-get autoremove -y 2>/dev/null || true
    log_success "Đã gỡ bỏ các gói phụ thuộc và dọn dẹp thư viện thừa"
fi

echo ""
echo -e "${C_BOLD}${C_GREEN}======================================================================${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}  ✔ ĐÃ GỠ CÀI ĐẶT WYSEPLAY THÀNH CÔNG VÀ KHÔI PHỤC HỆ THỐNG!${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}======================================================================${C_RESET}"
echo -e "Hệ thống đã được trả về trạng thái nguyên bản sạch sẽ."
echo -e "Bạn có thể khởi động lại máy để áp dụng hoàn toàn bằng lệnh: ${C_CYAN}sudo reboot${C_RESET}\n"
