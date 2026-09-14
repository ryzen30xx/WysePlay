# WysePlay - Agent Guidelines, Invariants & Anti-Drift Playbook

Tài liệu này là quy chuẩn bắt buộc (Single Source of Truth) dành cho tất cả các AI Agent và lập trình viên làm việc trên repository WysePlay. Mọi vi phạm các quy tắc bất biến (Invariants) dưới đây đều dẫn đến việc dịch vụ AirPlay bị Apple client từ chối hoặc biến mất khỏi hệ thống.

---

## 1. Bản chất sự cố: Tại sao Flag và Thông tin Thiết bị (MAC) liên tục bị lệch? (Root Cause Post-Mortem)

### 1.1. Lỗi lệch cờ AirPlay (`flags=0x4` vs `flags=0x204`):
1. **Kiến trúc hai luồng của AirPlay**:
   - Dịch vụ Video / Phản chiếu: `_airplay._tcp` (cổng 7000).
   - Dịch vụ Âm thanh / RAOP: `_raop._tcp` (cổng 7000, định dạng `<MAC>@<NAME>`).
2. **Cấu trúc bitfield của cờ `flags` (AirPlay) và `sf` (RAOP)**:
   - **Bit 2 (`0x04`)**: Yêu cầu xác thực OTP / mã PIN (`PIN required`).
   - **Bit 9 (`0x200`)**: Khả năng nhận luồng hình ảnh phản chiếu (`SupportsScreenMirroring`).
   - **Hợp bit chuẩn**: `0x200 | 0x04 = 0x204`.
3. **Tại sao lại bị lệch liên tục**:
   - Trên TV Box (X96Q), `uxplay` chạy với `flags=0x204` và `sf=0x204`.
   - Khi tạo proxy phát sóng trên máy Mac (`src/mac_announcer.py`), các agent trước đó đã **hardcode độc lập** giá trị `flags=0x4` và `sf=0x4` (chỉ kích hoạt bit PIN mà bỏ quên bit `0x200`).
   - Mỗi lần script proxy được viết lại hoặc chạy lại, giá trị `0x4` lại bị sao chép mà không qua bước kiểm tra chéo (cross-check).
   - **Hậu quả**: Khi macOS mDNSResponder nhận được thông tin dịch vụ với `flags=0x4`, hệ điều hành xác định đây **KHÔNG PHẢI MÀN HÌNH** (thiếu bit `0x200`) mà chỉ là loa phát nhạc, dẫn đến việc macOS lập tức xóa thiết bị khỏi menu **"Mirror or Extend to"** trong Control Center!

### 1.2. Lỗi lệch địa chỉ phần cứng (MAC Address / Device ID):
1. **Nguyên nhân cốt lõi**:
   - TV Box X96Q có 2 interface mạng vật lý/ảo:
     - Ethernet: `02:00:d5:21:8e:c0` (hoặc virtual interface).
     - Wi-Fi nội bộ: `12:00:d5:21:8e:c0` (do driver gán hoặc hardcode).
   - Service systemd `airplay-kiosk` trên TV Box chạy UxPlay với cờ:
     ```bash
     -m 12:00:d5:21:8e:c0
     ```
     khiến TV Box luôn phát sinh định danh:
     `deviceid=12:00:d5:21:8e:c0` và RAOP là `1200D5218EC0@P27FBA-RAGL`.
   - Tuy nhiên, trong script `mac_announcer.py`, code lại bị hardcode thành:
     `mac_clean = "0200D5218EC0"` và `mac_colon = "02:00:d5:21:8e:c0"`.
   - **Hậu quả**: macOS phát hiện sự bất đồng bộ danh tính nghiêm trọng: Bản ghi Video xưng MAC `02:...`, nhưng bản ghi Audio RAOP xưng MAC `12:...`. macOS coi đây là trạng thái "corrupted identity / spoofed target" và từ chối thiết lập phiên kết nối.

---

## 2. Quy tắc bất biến bắt buộc (Strict Invariants - Single Source of Truth)

TẤT CẢ các agent, script triển khai, bản vá source code và công cụ proxy PHẢI tuân thủ bảng tham số bất biến sau. **NGHIÊM CẤM TỰ Ý SỬA ĐỔI:**

| Thuộc tính | Giá trị bắt buộc | Ý nghĩa kỹ thuật |
| :--- | :--- | :--- |
| **AirPlay flags** | `0x204` | Bit 9 (`0x200`) Screen Mirroring + Bit 2 (`0x04`) PIN Security. **TUYỆT ĐỐI CẤM dùng `0x4`**. |
| **RAOP sf** | `0x204` | System Flags của Apple RAOP Audio, phải đồng bộ với flags của AirPlay. |
| **Device MAC** | `12:00:d5:21:8e:c0` | Địa chỉ MAC chuẩn duy nhất gán cho UxPlay (`-m 12:00:d5:21:8e:c0`). |
| **RAOP Service Name** | `1200D5218EC0@P27FBA-RAGL` | Phải bắt đầu bằng 12 ký tự hex viết hoa không dấu hai chấm của MAC chuẩn. |
| **AirPlay features** | `0x527FFEE6,0x0` | Bật Screen Mirroring (Bit 7), tắt bắt buộc HomeKit Pairing ID (Bit 27=0). |
| **RAOP ft** | `0x527FFEE6,0x0` | Phải đồng bộ tuyệt đối với `features`. |
| **Model** | `AppleTV3,2` | Khai báo chuẩn Apple TV 3rd Gen Rev A. |
| **Port** | `7000` | Cổng RTSP / HTTP tiêu chuẩn của AirPlay Mirroring. |
| **Canonical Hostname**| `x96q.local.` | Tên hostname chuẩn trong bản ghi SRV. CẤM tạo hostname phụ gây đè cache. |

---

## 3. Quy chuẩn phòng ngừa lệch (Anti-Drift Guardrails)

### 3.1. Quy tắc CẤM (Strict Prohibitions):
1. **CẤM hardcode phân tán**: Tuyệt đối không hardcode các giá trị flag hoặc MAC khác nhau trên nhiều file kịch bản. Mọi công cụ phải tham chiếu từ cấu hình chuẩn.
2. **CẤM hạ cấp flag**: Nghiêm cấm gán `flags=0x4` hoặc `sf=0x4` trong bất kỳ hoàn cảnh nào.
3. **CẤM dùng MAC `02:...`**: CẤM dùng prefix `0200D5218EC0` khi target đang chạy với `1200D5218EC0`.
4. **CẤM báo cáo hoàn thành mà không kiểm tra Pre-flight**: Không được xác nhận với người dùng là "đã fix" nếu chưa chạy lệnh kiểm tra xác thực mDNS thực tế.

### 3.2. Quy trình kiểm tra bắt buộc trước khi kết thúc tác vụ (Pre-Flight Verification Checklist):
Mỗi khi khởi động hoặc sửa đổi bất kỳ dịch vụ nào liên quan đến mDNS / AirPlay, Agent BẮT BUỘC phải thực hiện lệnh sau trên Mac để kiểm chứng:
```bash
# 1. Kiểm tra bản ghi Video AirPlay
dns-sd -L P27FBA-RAGL _airplay._tcp
# -> PHẢI thấy: flags=0x204, features=0x527FFEE6,0x0, deviceid=12:00:d5:21:8e:c0

# 2. Kiểm tra bản ghi Audio RAOP
dns-sd -L 1200D5218EC0@P27FBA-RAGL _raop._tcp
# -> PHẢI thấy: sf=0x204, ft=0x527FFEE6,0x0
```
Nếu output trả về thiếu bit `0x200` hoặc sai MAC, Agent phải tự động rollback và sửa lại ngay lập tức.

---

## 4. Quy định ghi log trao đổi và sự cố (`AGENT_COMMUNICATION.log`)

Mọi sự cố lệch cấu hình, phát sinh lỗi kết nối hoặc các bước chuyển giao quan trọng giữa User, Agent và System PHẢI được ghi lại vào file `AGENT_COMMUNICATION.log` tại thư mục gốc repository.

### Định dạng bắt buộc:
```text
[YYYY-MM-DD HH:MM:SS] SENDER -> RECEIVER | NỘI_DUNG_TÓM_TẮT_DƯỚI_100_KÝ_TỰ
```
- **SENDER / RECEIVER**: `USER`, `AGENT`, `SYSTEM`, `REPO`.
- **Nội dung**: Ghi rõ nguyên nhân, hiện tượng hoặc hành động khắc phục cụ thể.

---

## 5. Quy chuẩn Git Commit Governance

- Sử dụng định dạng Portfolio Bracket-Tag:
  - `[Feature]`: Thêm tính năng mới (ví dụ: DRM native rendering).
  - `[Fix]`: Sửa lỗi (ví dụ: cờ mDNS, buffer chuột, build script).
  - `[Update]`: Cập nhật tài liệu, tài nguyên, dependencies.
  - `[Init]`: Khởi tạo module hoặc cấu trúc mới.
  - `[Finish]`: Hoàn tất một mốc lớn hoặc release.
- **Quy tắc cấm trong Git Governance**:
  - Không commit các file nhạy cảm hay file log runtime không cần thiết.
  - Mọi commit phải giải quyết nguyên vẹn 1 mục tiêu và không phá vỡ bảng Invariants ở Mục 2.
