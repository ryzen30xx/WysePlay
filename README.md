# 🍏 WysePlay — Apple TV-style AirPlay Receiver Appliance

<p align="center">
  <img src="assets/airplay_large.png" width="100" alt="WysePlay AirPlay Logo" />
</p>

<p align="center">
  <b>Biến bất kỳ máy tính Mini PC / Thin Client nào (Dell Wyse, HP Thin Client, Intel NUC, Raspberry Pi) thành thiết bị nhận Apple AirPlay chuyên dụng chuẩn tvOS Conference Room Display.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License MIT" />
  <img src="https://img.shields.io/badge/Platform-Debian%20%7C%20Ubuntu%20%7C%20Raspberry%20Pi%20OS-red.svg" alt="Platform" />
  <img src="https://img.shields.io/badge/Arch-x86__64%20%7C%20aarch64%20%7C%20armv7l-green.svg" alt="Architecture" />
  <img src="https://img.shields.io/badge/AirPlay-2%20Mirroring%20%26%20Audio-orange.svg" alt="AirPlay" />
</p>

---

## 🌟 Điểm Nổi Bật (Features)

- 🖥️ **Giao diện Apple TV Conference Room chuẩn mực**:
  - Tông màu đen sâu chuẩn True Dark `#070709` kết hợp hiệu ứng quầng sáng xanh sapphire (*ambient sapphire glow*) sang trọng.
  - Biểu tượng AirPlay chuẩn **Apple SF Symbols** trích xuất từ macOS AppKit.
  - Bộ phông chữ chính hãng **Apple San Francisco Pro** (`SF Pro Display`, `SF Pro Text`) với kỹ thuật khử răng cưa **2x Lanczos Supersampling**, đảm bảo hiển thị sắc nét tuyệt đối trên mọi độ phân giải (1080p, 2K, 4K).
- 📶 **Màn hình cài đặt Wi-Fi tương tác thông minh (tvOS Wi-Fi Onboarding)**:
  - Tự động hiển thị khi thiết bị chưa có mạng hoặc bị rút dây LAN.
  - Thẻ mạng bo góc tròn mềm mại dạng squircle, biểu tượng sóng Wi-Fi và ổ khóa bảo mật chính hãng Apple.
  - Điều khiển 100% bằng bàn phím máy tính: `↑` / `↓` để duyệt danh sách, `Enter` để chọn & kết nối, `Esc` để quay lại danh sách mạng.
  - **Auto-scan ngầm mỗi 10 giây** mà không giật lag màn hình, giữ nguyên vị trí con trỏ và không gây gián đoạn khi người dùng đang gõ mật khẩu.
- 🔌 **Dynamic EDID & Monitor Hotplug Supervisor**:
  - Tự động đọc thông tin EDID phần cứng qua DRM/RandR để lấy tên thật của màn hình (ví dụ: *Dell UltraSharp, LG UltraFine, Sony BRAVIA, Samsung TV*...).
  - Tự động cập nhật tên thiết bị AirPlay trên iPhone/iPad/Mac theo đúng màn hình đang cắm.
  - Hỗ trợ rút/cắm nóng màn hình mà không cần khởi động lại thiết bị; tự động điều chỉnh độ phân giải và tần số quét (lên đến 4K 60Hz).
- 🔒 **Input Locking an toàn khi trình chiếu**:
  - Tự động vô hiệu hóa toàn bộ chuột và bàn phím vật lý khi có luồng AirPlay đang phản chiếu hình ảnh, ngăn chặn người ngoài can thiệp làm gián đoạn bài thuyết trình.
  - Tự động mở khóa trở lại khi kết thúc phiên chiếu.
- ⚡ **Thiết bị vận hành độc lập (Zero-touch Appliance)**:
  - Tự động khởi động trực tiếp vào Kiosk thông qua `systemd` và môi trường X11 siêu nhẹ (Openbox).
  - Không hiện con trỏ chuột, không hiện viền cửa sổ, tự phục hồi tức thì nếu có lỗi.

---

## 🚀 Cài Đặt Nhanh (One-Liner Installation)

Chỉ cần mở terminal trên thiết bị Linux (Debian 12 / Ubuntu 22.04+ / Raspberry Pi OS) và chạy dòng lệnh duy nhất sau:

```bash
curl -fsSL https://raw.githubusercontent.com/ryzen30xx/WysePlay/main/install.sh | sudo bash
```

> [!TIP]
> Script cài đặt tích hợp sẵn bộ **Pre-flight Checks** tự động kiểm tra hệ điều hành, kiến trúc CPU, dung lượng ổ đĩa, quyền hạn root và tự động nhận diện người dùng hệ thống để cấu hình.

Nếu muốn chỉ định một tài khoản người dùng cụ thể để chạy giao diện Kiosk:
```bash
curl -fsSL https://raw.githubusercontent.com/ryzen30xx/WysePlay/main/install.sh | sudo bash -s -- --user ten_nguoi_dung
```

---

## 🛠️ Yêu Cầu Hệ Thống (Requirements)

| Thành phần | Yêu cầu tối thiểu | Khuyến nghị |
| :--- | :--- | :--- |
| **Phần cứng** | Dell Wyse 3040/5070, HP T630/T640, Intel NUC, Raspberry Pi 4 | Mini PC chip Intel Celeron/Pentium/Core hoặc AMD Ryzen, Raspberry Pi 5 |
| **RAM** | 1 GB RAM | 2 GB - 4 GB RAM |
| **Ổ cứng** | 500 MB dung lượng trống | Ổ flash eMMC / SSD |
| **Hệ điều hành** | Debian 12 (Bookworm), Ubuntu 22.04 LTS trở lên, Raspberry Pi OS (64-bit) | Debian 12 Minimal (không cần cài sẵn Desktop Environment nặng) |
| **Kết nối mạng** | Cổng mạng LAN RJ45 hoặc Wi-Fi 2.4/5GHz | Wi-Fi 5/6 Dual-Band hoặc Gigabit Ethernet |
| **Màn hình** | Cổng HDMI hoặc DisplayPort (720p, 1080p) | Màn hình hoặc TV hỗ trợ Full HD 1080p / 4K 60Hz |

---

## 📦 Cài Đặt Thủ Công Từng Bước (Manual Installation)

Nếu bạn muốn tự tay thiết lập từng bước hoặc tùy biến theo nhu cầu:

### Bước 1: Sao chép mã nguồn về máy
```bash
git clone https://github.com/ryzen30xx/WysePlay.git
cd WysePlay
```

### Bước 2: Cài đặt các gói phụ thuộc hệ thống
```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    xserver-xorg xinit openbox x11-xserver-utils xinput xdotool unclutter feh \
    python3 python3-pil python3-pil.imagetk python3-tk python3-pyudev \
    network-manager avahi-daemon libnss-mdns uxplay fontconfig pulseaudio
```

### Bước 3: Cài đặt bộ phông chữ Apple San Francisco Pro
```bash
sudo mkdir -p /usr/local/share/fonts/apple-sf-pro
sudo cp fonts/*.ttf /usr/local/share/fonts/apple-sf-pro/
sudo chmod 644 /usr/local/share/fonts/apple-sf-pro/*.ttf
sudo fc-cache -fv /usr/local/share/fonts/apple-sf-pro/
```

### Bước 4: Triển khai mã nguồn vào `/opt/airplay`
```bash
sudo mkdir -p /opt/airplay/assets
sudo cp src/*.py src/*.sh /opt/airplay/
sudo cp assets/*.png /opt/airplay/assets/
sudo chmod +x /opt/airplay/*.py /opt/airplay/*.sh
sudo chown -R $USER:$USER /opt/airplay
```

### Bước 5: Cấu hình Openbox và Khử răng cưa Xresources
```bash
# Thêm quyền điều khiển phần cứng cho tài khoản
sudo usermod -a -G video,audio,input,netdev $USER

# Tạo cấu hình Openbox
mkdir -p ~/.config/openbox
cp config/rc.xml ~/.config/openbox/rc.xml

# Cấu hình Xresources chống vỡ font
cp config/Xresources ~/.Xresources
```

### Bước 6: Đăng ký dịch vụ Systemd
```bash
# Thay thế tên người dùng và thư mục home vào file service
sudo sed -e "s|@TARGET_USER@|$USER|g" \
         -e "s|@TARGET_HOME@|$HOME|g" \
         config/airplay-kiosk.service | sudo tee /etc/systemd/system/airplay-kiosk.service > /dev/null

sudo chmod 644 /etc/systemd/system/airplay-kiosk.service
sudo systemctl daemon-reload
sudo systemctl enable airplay-kiosk.service
sudo systemctl restart airplay-kiosk.service
```

---

## 📂 Cấu Trúc Thư Mục Dự Án (Repository Structure)

```text
WysePlay/
├── install.sh                  # Bộ cài đặt tự động one-liner kèm pre-flight checks
├── README.md                   # Tài liệu hướng dẫn chi tiết
├── LICENSE                     # Giấy phép nguồn mở MIT
├── config/
│   ├── airplay-kiosk.service   # Mẫu dịch vụ systemd tự chạy nền
│   ├── rc.xml                  # Cấu hình Openbox tối ưu (toàn màn hình, không viền)
│   └── Xresources              # Thiết lập Xft subpixel antialiasing & LCD filter
├── src/
│   ├── kiosk_manager.py        # Hotplug supervisor, quản lý UxPlay, failover mạng & khóa input
│   ├── make_wallpaper.py       # Render hình nền Apple TV với ambient glow & supersampling
│   ├── wifi_gui.py             # Giao diện cài đặt Wi-Fi chuẩn tvOS điều khiển bằng bàn phím
│   ├── detect_display.py       # Helper nhận diện độ phân giải và tần số quét màn hình
│   └── start_kiosk.sh          # Launcher khởi động X11, Openbox và Kiosk Manager
├── assets/                     # Bộ biểu tượng SF Symbols chuẩn Apple (PNG có kênh Alpha)
│   ├── airplay_large.png       # Biểu tượng AirPlay lớn
│   ├── wifi_badge.png          # Huy hiệu Wi-Fi xanh tròn
│   ├── wifi_white.png / wifi_muted.png
│   ├── lock_white.png / lock_muted.png
│   └── ...
└── fonts/                      # Bộ phông chữ Apple San Francisco Pro đầy đủ
    ├── SFProDisplay-Bold.ttf
    ├── SFProDisplay-Semibold.ttf
    ├── SFProText-Medium.ttf
    ├── SFProText-Regular.ttf
    └── ...
```

---

## ⌨️ Hướng Dẫn Sử Dụng & Thao Tác (User Guide)

### 1. Kết nối AirPlay thông thường (Khi đã có mạng LAN / Wi-Fi)
- Màn hình sẽ hiển thị trạng thái chuẩn của **Apple TV Conference Room Display**:
  - Tên thiết bị AirPlay (tự động theo tên màn hình cắm vào).
  - Tên mạng Wi-Fi và địa chỉ IP hiện tại của thiết bị.
  - Hướng dẫn kết nối: *"Mở Trung tâm điều khiển trên thiết bị Apple của bạn và chọn tên này để phản chiếu màn hình."*
- Trên iPhone/iPad: Vuốt mở **Control Center** > bấm biểu tượng **Screen Mirroring** (Phản chiếu màn hình) > chọn tên thiết bị.
- Trên máy Mac: Bấm biểu tượng **Control Center** trên thanh Menu > chọn **Screen Mirroring** > chọn tên thiết bị.

### 2. Cài đặt mạng Wi-Fi (Khi chưa có mạng hoặc đổi mật khẩu)
- Khi không có dây mạng LAN hoặc ngắt kết nối Wi-Fi, hộp thoại cài đặt Wi-Fi chuẩn Apple sẽ xuất hiện bên trái màn hình.
- **Phím `↑` / `↓`**: Di chuyển vệt sáng chọn mạng Wi-Fi trong danh sách.
- **Phím `Enter`**: Chọn mạng Wi-Fi để tiến hành kết nối.
  - Nếu là mạng có mật khẩu: Nhập mật khẩu và nhấn `Enter` (hoặc bấm chọn nút "Kết nối").
  - Nếu là mạng không có mật khẩu (mạng mở): Hệ thống sẽ kết nối ngay lập tức.
- **Phím `Esc`**: Hủy bỏ nhập mật khẩu và quay lại danh sách mạng.
- Ngay khi kết nối thành công, giao diện cài đặt sẽ tự động đóng lại và chuyển sang màn hình chờ nhận AirPlay.

---

## 🔧 Các Lệnh Quản Trị Hệ Thống (Maintenance & Commands)

```bash
# Xem trạng thái đang chạy của dịch vụ
sudo systemctl status airplay-kiosk

# Theo dõi nhật ký hoạt động thời gian thực (real-time logs)
sudo journalctl -u airplay-kiosk -f

# Khởi động lại dịch vụ Kiosk
sudo systemctl restart airplay-kiosk

# Tạm dừng dịch vụ Kiosk
sudo systemctl stop airplay-kiosk
```

---

## ❓ Câu Hỏi Thường Gặp (Troubleshooting & FAQ)

<details>
<summary><b>1. Thiết bị Apple không tìm thấy tên AirPlay trên mạng?</b></summary>

- Đảm bảo thiết bị Apple (iPhone, iPad, Mac) và WysePlay đang kết nối vào **cùng một mạng Wi-Fi / subnet LAN**.
- Kiểm tra xem dịch vụ phát quảng bá Bonjour/mDNS có đang chạy không:
  ```bash
  sudo systemctl status avahi-daemon
  ```
- Một số router Wi-Fi của cơ quan hoặc khách sạn có bật tính năng **"AP Isolation" / "Client Isolation"** khiến các thiết bị trong mạng không nhìn thấy nhau. Vui lòng tắt tính năng này trong phần cài đặt của Router.
</details>

<details>
<summary><b>2. Màn hình TV bị mất viền hoặc hình ảnh bị tràn lề (Overscan)?</b></summary>

- Trên TV, vào phần Cài đặt hình ảnh (Picture Settings) và chuyển chế độ tỉ lệ màn hình thành **"Just Scan"**, **"Fit to Screen"**, **"1:1 Pixel"** hoặc **"Original"** thay vì "16:9".
</details>

<details>
<summary><b>3. Làm thế nào để thay đổi tên thiết bị AirPlay cố định thay vì nhận diện tự động?</b></summary>

- Mở file `/opt/airplay/kiosk_manager.py`, tìm đoạn gọi `uxplay -n monitor_name` và sửa thành tên bạn mong muốn (ví dụ: `-n "Phòng Họp 01"`).
</details>

---

## 📄 Bản Quyền & Giấy Phép (License)

Dự án được phân phối dưới giấy phép **MIT License**. Bạn được toàn quyền sử dụng, sửa đổi và triển khai cho mục đích cá nhân hoặc doanh nghiệp.
Phông chữ San Francisco và biểu tượng SF Symbols là tài sản trí tuệ của Apple Inc.
