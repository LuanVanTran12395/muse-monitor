# Information Architecture — Muse Monitor

Cấu trúc thông tin của app gồm 4 lớp: (1) cửa sổ và màn hình, (2) menu và hộp thoại, (3) điều hướng giữa các
trạng thái, (4) dữ liệu trên đĩa và extension. Tên giữ nguyên như trong app.

## 1. Bản đồ tổng thể

```mermaid
flowchart TD
    APP(["Muse Monitor"]) --> LIVE["Cửa sổ Live<br/>(1 cửa sổ / device profile)"]
    APP --> REV["Cửa sổ Review<br/>(0…n, mỗi phiên một cửa sổ)"]
    APP --> DATA[("data/<br/>phiên đã ghi")]
    APP --> EXT[("extensions/<br/>~/.musemonitor/extensions<br/>$MUSEMONITOR_EXTENSIONS · pip")]
    APP --> SET[("QSettings<br/>theme, thiết bị cuối, time range,<br/>panel đang hiện, extension tắt")]

    LIVE --> MB["Menu bar"]
    LIVE --> PAGES["Trang (stack)"]
    LIVE --> SB["Status bar<br/>thông báo · Theme"]
    LIVE --> DLG["Hộp thoại"]

    PAGES --> P1["Connect"]
    PAGES --> P2["Fit-test"]
    PAGES --> P3["Recording"]

    REV --> RMB["Menu bar<br/>File · Analysis · HCI/BCI · Extensions"]
    REV --> RP3["Recording (chế độ review)"]
    REV --> RNAV["Thanh cuộn thời gian · vị trí ·<br/>danh sách event"]

    LIVE -. "File ▸ Open session…" .-> REV
    LIVE -- "Start/Stop recording" --> DATA
    DATA -- "Open session…" --> REV
    EXT -- "nạp khi mở app /<br/>Check for new extensions" --> LIVE
    EXT -- "chỉ extension supports_review" --> REV
```

## 2. Cửa sổ Live

### 2.1 Menu bar

```mermaid
flowchart LR
    MB["Menu bar"] --> F["File"]
    MB --> AN["Analysis"]
    MB --> HB["HCI/BCI"]
    MB --> EX["Extensions"]

    F --> F1["New session ⌘N"]
    F --> F2["Open session… ⌘O"]
    F --> F3["Close window ⌘W"]

    AN --> AN1["EEG ▸ Band power"]
    AN --> AN2["Heart & optics ▸ …"]
    AN --> AN3["Data quality ▸ Artifacts"]
    AN --> AN4["Other ▸ …"]
    AN --> AN5["Show all / Hide all panels"]

    HB --> HB1["Eyes ▸ Eyes (experimental)"]
    HB --> HB2["Motion ▸ 3D head · 3D head +"]
    HB --> HB3["Show all / Hide all panels"]

    EX --> EX1["‹Extension› ▸ action<br/>vd. LSL Outlet ▸ Start LSL streams · LSL status…<br/>Band power ▸ Clear history"]
    EX --> EX2["Check for new extensions"]
    EX --> EX3["Manage extensions…"]
```

- **Analysis** và **HCI/BCI** chứa *panel* (tab của extension), gom theo `category` khai báo trong extension
  (`plugins/api.py: CATEGORIES`). Panel mặc định ẩn, hiện khi được tick; trạng thái tick được nhớ riêng cho cửa sổ live và review.
- **Extensions** chứa *action* (`app.add_action`), mỗi extension một submenu.
- Mục trong menu là ví dụ từ extension đi kèm; danh sách thay đổi theo extension được cài.

### 2.2 Trang và nội dung

```mermaid
flowchart TD
    subgraph C["Connect"]
        C1["Tiêu đề + hướng dẫn<br/>thiết bị hỗ trợ"]
        C2["⟳ Rescan · trạng thái quét"]
        C3["Danh sách thiết bị<br/>tên · RSSI · profile · last used"]
        C4["Or enter name"]
        C5["Status · Connect → / Cancel"]
    end
    subgraph FT["Fit-test"]
        F1["Fit-test · ‹thiết bị› · 🔋 pin"]
        F2["Hướng dẫn đeo"]
        F3["Sơ đồ đầu<br/>4 điện cực theo màu chất lượng"]
        F4["Trace 4 kênh + chất lượng<br/>(cửa sổ cố định)"]
        F5["Disconnect · n/4 Good · Accept →"]
    end
    subgraph R["Recording"]
        R1["Thanh điều khiển:<br/>● Start / ■ Stop · mm:ss │ ◀ Fit-test │ Filtered · Notch · Fixed │ Time range │ 🔋 · status │ Disconnect"]
        R2["Thanh thống kê:<br/>EEG rate · Received · Events (Space / 1–9) · Timing │ Latest µV"]
        R3["Tab"]
        R4["Ghi chú research prototype"]
    end
    R3 --> T1["Signals<br/>EEG 4 kênh + chất lượng · Optics · IMU accel/gyro"]
    R3 --> T2["EEG PSD<br/>phổ · spectrogram"]
    R3 --> T3["PPG · HRV · fNIRS<br/>kênh PPG · HRV window · ô chỉ số · HbO/HbR"]
    R3 --> T4["Panel extension đang hiện<br/>(theo menu Analysis / HCI-BCI)"]
```

### 2.3 Hộp thoại

| Hộp thoại | Mở từ | Nội dung |
|---|---|---|
| **Mark event** | Space trên trang Recording | Thời điểm nhấn Space (ms), ô nhãn điền sẵn nhãn trước; Return = lưu, Esc = huỷ, gợi ý phím 1–9 |
| **Recording in progress** | Disconnect / New session / Close khi đang ghi | Thời gian đã ghi, hậu quả; *Stop recording* / **Keep recording** (mặc định) |
| **Extensions** | Extensions ▸ Manage extensions… | Bảng Enabled · Extension · Version · Status · Menu; chi tiết + lỗi; Update · Load/Unload · New extension… · Open extensions folder |
| **New extension** | Extensions dialog ▸ New extension… | Tên, category → vị trí menu dự kiến |
| **Open recording** | File ▸ Open session… | Chọn file, mở sẵn thư mục `data/` |
| **Which device recorded this?** | Mở file không có `session.json` | Chọn profile hoặc "Other device — estimate rates" |
| **Loading…** | Sau khi chọn file | Tiến độ nạp, Cancel |
| Hộp thoại riêng của extension | Action của extension | vd. LSL status… |

## 3. Cửa sổ Review

```mermaid
flowchart TD
    RW["Muse Monitor — Review: ‹thư mục phiên›"] --> RMF["File: New session · Open session… · Close window"]
    RW --> RMA["Analysis · HCI/BCI<br/>(panel của extension supports_review)"]
    RW --> RME["Extensions: action · Manage extensions…"]
    RW --> RPG["Recording page (review mode)<br/>ẩn Record · Disconnect · Fit-test · pin · rate"]
    RPG --> RT["Tab Signals · EEG PSD · PPG<br/>+ panel review"]
    RW --> RNV["Điều hướng thời gian"]
    RNV --> RN1["Thanh cuộn ngang (0.1 s / bước)"]
    RNV --> RN2["Nhãn vị trí h:mm:ss.s"]
    RNV --> RN3["Danh sách event → nhảy tới<br/>(event tạm của extension: '(temporary)')"]
    RW --> RST["Status bar: tiến độ replay cho extension"]
```

Trong Review, extension chỉ có tác dụng tạm: `mark_event` vẽ marker tạm, `set_setting` chỉ giữ trong bộ nhớ,
không ghi file nào.

## 4. Điều hướng (trạng thái cửa sổ Live)

```mermaid
stateDiagram-v2
    [*] --> Connect: mở app (tự quét)
    Connect --> Connecting: Connect →
    Connecting --> Connect: Cancel / lỗi
    Connecting --> FitTest: stream bắt đầu
    FitTest --> Recording: Accept →
    Recording --> FitTest: ◀ Fit-test
    FitTest --> Connect: Disconnect
    Recording --> Connect: Disconnect / mất kết nối

    state Recording {
        [*] --> Viewing
        Viewing --> Saving: ● Start recording
        Saving --> Viewing: ■ Stop recording → report.html
    }

    Recording --> Confirm: Disconnect / ⌘N / ⌘W khi đang ghi
    Confirm --> Recording: Keep recording (mặc định)
    Confirm --> Connect: Stop recording
    Connect --> [*]: Close window
```

File ▸ New session (từ bất kỳ trạng thái nào) → dừng ghi nếu có, ngắt kết nối, xoá dữ liệu và event → Connect.

## 5. Dữ liệu trên đĩa

```mermaid
flowchart TD
    ROOT[("Thư mục dữ liệu<br/>$MUSEMONITOR_DATA_DIR → ‹repo›/data → ~/MuseMonitor/data")] --> S["muse_‹YYYYMMDD_HHMMSS›/<br/>(mỗi lần Start recording)"]
    S --> S1["muse_eeg_‹time›.csv"]
    S --> S2["muse_eeg_‹time›_optics.csv · _imu.csv"]
    S --> S3["muse_eeg_‹time›_events.csv<br/>event 0 lúc bắt đầu, Space, 1–9, extension"]
    S --> S4["session.json<br/>profile, tần số, kênh, đơn vị"]
    S --> S5["report.html<br/>PSD cả phiên, band power, event"]
    S --> S6["psd_eeg.csv · psd_optics.csv · psd_imu.csv"]
    S --> S7["File của extension<br/>vd. ‹rec›_artifacts.csv"]
```

## 6. Kiến trúc extension (góc nhìn người phát triển)

```mermaid
flowchart LR
    subgraph SRC["Nguồn extension"]
        E1["extensions/‹tên›/__init__.py"]
        E2["~/.musemonitor/extensions"]
        E3["$MUSEMONITOR_EXTENSIONS"]
        E4["pip entry point"]
    end
    SRC --> MGR["ExtensionManager<br/>nạp · kiểm tra requires_api / supports(spec) · cô lập lỗi"]
    MGR --> CTX["ExtensionContext (app)"]
    CTX --> O1["Đọc: spec · store · theme · window_sec<br/>is_streaming · is_recording · recording_path · is_review · view"]
    CTX --> O2["Ghi lên UI: add_tab → panel trong Analysis / HCI-BCI<br/>add_action → Extensions ▸ ‹tên›<br/>show_status → status bar"]
    CTX --> O3["Dữ liệu: mark_event → events.csv<br/>setting / set_setting · data_dir"]
    HOOK["Hook app gọi vào extension"] --> H1["Vòng đời: activate · deactivate"]
    HOOK --> H2["Dữ liệu: on_eeg / on_optics / on_imu<br/>API 3: on_*_samples(x, ts_raw)"]
    HOOK --> H3["Phiên: on_connected · on_disconnected · on_event<br/>on_recording_started · on_recording_stopped"]
    HOOK --> H4["Hiển thị: on_theme_changed · on_view_changed (review)"]
    MGR --> HOOK
```

## 7. Nhận xét IA

1. **Tổ chức theo tác vụ là hợp lý:** 3 trang nối tiếp nhau khớp với nhiệm vụ 2 → 3 → 4/5 trong [HTA.md](HTA.md).
2. **Menu chia theo bản chất nội dung:** *panel* (xem) nằm trong Analysis / HCI-BCI, *action* (làm) nằm trong
   Extensions. Người phát triển chỉ cần khai báo `category`. Nhược điểm: một extension có cả panel lẫn action thì
   bị chia ra hai nơi.
3. **Thiếu một nơi cho cài đặt:** Theme ở status bar, Time range và bộ lọc ở thanh điều khiển, extension tắt/bật
   ở hộp thoại. Không có menu View/Preferences (V9).
4. **Thông tin chẩn đoán chưa có chỗ riêng:** telemetry chiếm vị trí chính trên trang Recording (V4). Một panel
   "Diagnostics" sẽ tách được lớp thông tin này.
5. **Liên kết dữ liệu → app đi một chiều:** app ghi vào `data/` nhưng chỉ có status bar trỏ về đó; không có
   "Recent sessions" hay nút mở thư mục (V13).
