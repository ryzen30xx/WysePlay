# WysePlay - Agent Guidelines & Invariants

## Strict Invariant: Apple Screen Mirroring Target Classification
WysePlay is a dedicated AirPlay Screen Mirroring receiver platform. Under NO circumstances should any patch, configuration, or announcer downgrade devices to audio-only or trigger pairing rejections on Apple client devices.

### Mandatory DNS-SD / Bonjour Parameters:
1. **AirPlay Service (`_airplay._tcp`)**:
   - `features`: MUST be `0x527FFEE6,0x0`. Bit 7 (Screen Mirroring) is ON, while Bit 27 MUST be `0` (disabling legacy/HomeKit pairing ID requirement so Apple clients never reject with "Ignoring device found without pairing ID").
   - `flags`: MUST be `0x204`. Bit 9 (`0x200`) MUST be set (`0x200 | 0x4 = 0x204`) to explicitly declare the target as an Apple Screen Mirroring destination.
   - `model`: `AppleTV3,2`
   - `srcvers`: `220.68`
   - `vv`: `2`
   - `port`: `7000`

2. **RAOP Audio Service (`_raop._tcp`)**:
   - Name: `<MAC_ADDRESS_UPPERCASE_NO_COLONS>@<NAME>` (e.g., `1200D5218EC0@P27FBA-RAGL`).
   - `sf`: MUST be `0x204`. Bit 9 (`0x200`) MUST be set for Screen Mirroring.
   - `ft`: `0x527FFEE6,0x0`.
   - `am`: `AppleTV3,2`.
   - `tp`: `UDP`.

3. **Hostname & SRV Records**:
   - Hostnames announced in SRV records must match the canonical host (e.g. `x96q.local.`).
   - Do NOT invent divergent hostnames (such as `x96q-wifi.local.`) that cause mDNS collisions or suppression in `mDNSResponder`.

4. **macOS Client Discovery Behavior**:
   - New or disconnected Screen Mirroring receivers only appear in **Menu Bar -> Control Center -> Screen Mirroring**.
   - macOS **System Settings -> Displays** will NOT list an AirPlay target until it is selected and actively connected from the Screen Mirroring menu.
