# Hierarchical Task Analysis — Muse Monitor

Persona: nhà nghiên cứu BCI (xem [README.md](README.md)). Ký hiệu HTA chuẩn: mỗi nhiệm vụ được chia thành
nhiệm vụ con, kèm **Plan** nói thứ tự / điều kiện thực hiện. Tên nút, menu, phím giữ nguyên tiếng Anh như trong app.

Cột **UX** đánh dấu điểm đau từ bản đánh giá heuristic (V1–V13); ✅ = đã sửa trên nhánh hiện tại.

## 0. Tổng quan

```mermaid
flowchart TD
    G0["0. Thực hiện R&D BCI với Muse<br/>qua Muse Monitor"]
    G0 --> T1["1. Chuẩn bị môi trường"]
    G0 --> T2["2. Kết nối thiết bị"]
    G0 --> T3["3. Kiểm tra tiếp xúc<br/>(Fit-test)"]
    G0 --> T4["4. Theo dõi tín hiệu trực tiếp"]
    G0 --> T5["5. Ghi phiên thí nghiệm"]
    G0 --> T6["6. Xem lại phiên đã ghi"]
    G0 --> T7["7. Xuất luồng sang công cụ ngoài<br/>(LSL)"]
    G0 --> T8["8. Phát triển & nhúng extension"]
    G0 --> T9["9. Kết thúc phiên"]

    classDef ops fill:#dbeafe,stroke:#1d4ed8,color:#0b1b3f
    classDef dev fill:#dcfce7,stroke:#15803d,color:#052e16
    class T1,T2,T3,T4,T5,T6,T7,T9 ops
    class T8 dev
```

**Plan 0:** Lần đầu: 1. Mỗi phiên vận hành: 2 → 3 → 4 → 5 (lặp 4–5 theo protocol) → 9; quay về 3 bất cứ lúc
nào chất lượng tụt. 6 và 7 tuỳ chọn, 6 có thể chạy song song khi cửa sổ live vẫn mở. 8 là vòng lặp riêng của
vai phát triển, xen kẽ với 4–6 để thử extension trên dữ liệu thật hoặc dữ liệu đã ghi.

---

## 1. Chuẩn bị môi trường

```mermaid
flowchart TD
    T1["1. Chuẩn bị môi trường"] --> T11["1.1 Cài app<br/>run.command / pip install -e ."]
    T1 --> T12["1.2 Cài phần tuỳ chọn<br/>pip install -e .[lsl], opencv…"]
    T1 --> T13["1.3 Mở app<br/>run.command hoặc python -m musemonitor"]
    T1 --> T14["1.4 Chọn theme<br/>status bar ▸ Theme"]
```

**Plan 1:** 1.1 → (1.2 nếu cần LSL / camera) → 1.3; 1.4 tuỳ ý, được nhớ giữa các lần mở.

| UX | Ghi chú |
|---|---|
| V9 | Chọn theme nằm ở status bar thay vì menu — khó tìm |

## 2. Kết nối thiết bị

```mermaid
flowchart TD
    T2["2. Kết nối thiết bị"] --> T21["2.1 Bật headset,<br/>đóng app khác đang kết nối"]
    T2 --> T22["2.2 Quét Bluetooth<br/>(tự động 5 s / ⟳ Rescan)"]
    T2 --> T23["2.3 Chọn thiết bị"]
    T23 --> T231["2.3.1 Chọn trong danh sách<br/>(tên · RSSI · last used)"]
    T23 --> T232["2.3.2 hoặc gõ tên<br/>Or enter name"]
    T2 --> T24["2.4 Connect →<br/>(double-click cũng được)"]
    T2 --> T25["2.5 Chờ stream bắt đầu<br/>hoặc Cancel"]
```

**Plan 2:** 2.1 → 2.2 (app tự quét khi mở). Nếu "No device found" → 2.1 rồi 2.2 lại. 2.3.1 hoặc 2.3.2 → 2.4 → 2.5.
Stream bắt đầu → tự chuyển sang 3. Lỗi kết nối → status báo lỗi, quay lại 2.1. Thiết bị thuộc profile khác →
app mở cửa sổ mới cho profile đó.

| UX | Ghi chú |
|---|---|
| V5 | Đã tìm thấy 1 thiết bị nhưng Connect vẫn xám cho đến khi bấm vào dòng; danh sách chiếm phần lớn màn hình và có nền tối trong theme Light; không có spinner khi quét |

## 3. Kiểm tra tiếp xúc (Fit-test)

```mermaid
flowchart TD
    T3["3. Fit-test"] --> T31["3.1 Đọc sơ đồ đầu:<br/>màu + chữ Good/Fair/Bad mỗi điện cực"]
    T3 --> T32["3.2 Chỉnh headset<br/>lau trán, vén tóc, thả lỏng hàm"]
    T3 --> T33["3.3 Xem trace 4 kênh<br/>+ RMS, nhiễu 50 Hz"]
    T3 --> T34["3.4 Kiểm tra pin"]
    T3 --> T35["3.5 Quyết định"]
    T35 --> T351["3.5.1 Accept →<br/>(xanh khi 4/4 Good)"]
    T35 --> T352["3.5.2 Disconnect"]
```

**Plan 3:** 3.4 một lần. Lặp {3.1 → 3.2 → 3.3} đến khi "4/4 channels Good ✓ Ready to record" hoặc người dùng
chấp nhận chất lượng hiện có → 3.5.1 (sang 4). 3.5.2 nếu bỏ phiên → 2. Từ trang Recording có thể quay lại bằng ◀ Fit-test.

| UX | Ghi chú |
|---|---|
| V6 | Accept khi còn kênh Bad không có cảnh báo, chất lượng lúc Accept không được lưu |
| V7 | Chữ "Good" đè lên đường viền đầu; chữ trắng trên màu Fair tương phản thấp |
| V4 | Chỉ số `8 µV · 50Hz 2` thiếu nhãn/đơn vị |

## 4. Theo dõi tín hiệu trực tiếp

```mermaid
flowchart TD
    T4["4. Theo dõi trực tiếp"] --> T41["4.1 Cấu hình hiển thị"]
    T41 --> T411["Filtered 1–40 Hz"]
    T41 --> T412["50 Hz notch"]
    T41 --> T413["Fixed ±200 µV"]
    T41 --> T414["Time range (s)"]
    T4 --> T42["4.2 Tab Signals<br/>EEG 4 kênh · optics · IMU"]
    T4 --> T43["4.3 Tab EEG PSD<br/>phổ + spectrogram"]
    T4 --> T44["4.4 Tab PPG · HRV · fNIRS<br/>kênh PPG, HRV window, λ, DPF"]
    T4 --> T45["4.5 Bật panel extension<br/>Analysis / HCI-BCI ▸ nhóm ▸ panel"]
    T4 --> T46["4.6 Kiểm tra sức khoẻ luồng<br/>EEG rate · Timing · pin"]
    T4 --> T47["4.7 Quay lại Fit-test<br/>nếu chất lượng tụt"]
```

**Plan 4:** 4.1 khi cần (cài đặt áp dụng ngay cho mọi tab). Chuyển tự do giữa 4.2 / 4.3 / 4.4 / panel của 4.5.
4.6 liếc định kỳ; Timing ≠ OK hoặc kênh Bad → 4.7 (= 3).

| UX | Ghi chú |
|---|---|
| V4 | Hai hàng telemetry dày đặc (`Received`, `Latest µV` nhảy liên tục); `ts↓`, `seq?` khó hiểu |
| V7 | Nhãn trục "Optical (mean-remov…" bị cắt; chú thích x/y/z đè lên đường Gyro |
| V11 | Trục thời gian chỉ là tương đối, không có giờ thật |

## 5. Ghi phiên thí nghiệm

```mermaid
flowchart TD
    T5["5. Ghi phiên"] --> T51["5.1 ● Start recording<br/>tự tạo data/muse_‹time›/ + event 0"]
    T5 --> T52["5.2 Chạy protocol & đánh dấu event"]
    T52 --> T521["5.2.1 Space → nhập nhãn<br/>(điền sẵn nhãn trước) → Return"]
    T52 --> T522["5.2.2 Phím 1–9:<br/>event tức thì, không hộp thoại"]
    T52 --> T523["5.2.3 Extension tự đánh dấu<br/>app.mark_event()"]
    T5 --> T53["5.3 Theo dõi trạng thái ghi<br/>nút đỏ ■ Stop · mm:ss, tiêu đề ● REC"]
    T5 --> T54["5.4 ■ Stop recording<br/>→ report.html + PSD CSV"]
    T5 --> T55["5.5 Tìm file kết quả<br/>status bar ▸ thư mục"]
```

**Plan 5:** 5.1 → lặp {5.2 theo protocol, 5.3 liếc định kỳ} → 5.4 → 5.5. Trong 5.2: 5.2.1 cho event cần mô tả,
5.2.2 cho mã kích thích lặp lại; 5.2.3 chạy nền. Ngắt kết nối / New session / đóng cửa sổ khi đang ghi → hộp
xác nhận, mặc định "Keep recording". Mất kết nối giữa chừng → dữ liệu và report vẫn được ghi.

| UX | Ghi chú |
|---|---|
| ✅ V1 | Trạng thái ghi: nút đỏ có đồng hồ, tiêu đề cửa sổ "● REC 3:07 — Muse Monitor" (hiện cả trên Dock, ở mọi trang) |
| ✅ V2 | Disconnect / ⌘N / ⌘W / nút đóng cửa sổ hỏi trước khi dừng ghi; Disconnect dời ra mép phải, xa nút ghi |
| ✅ V3 | Phím 1–9 đánh dấu tức thì; Space điền sẵn và bôi đen nhãn trước → Return lặp lại nhãn, gõ để thay |
| V13 | Sau khi dừng không có nút "Mở thư mục / report" |

## 6. Xem lại phiên đã ghi

```mermaid
flowchart TD
    T6["6. Xem lại phiên"] --> T61["6.1 File ▸ Open session… ⌘O<br/>session.json / muse_eeg_*.csv"]
    T6 --> T62["6.2 Chọn loại thiết bị<br/>(chỉ khi thiếu session.json)"]
    T6 --> T63["6.3 Chờ nạp (có Cancel)"]
    T6 --> T64["6.4 Duyệt theo thời gian<br/>thanh cuộn · Time range"]
    T6 --> T65["6.5 Nhảy tới event<br/>danh sách event"]
    T6 --> T66["6.6 Xem tab & panel<br/>extension hỗ trợ review"]
    T6 --> T67["6.7 Mở report.html / CSV<br/>bằng công cụ ngoài"]
```

**Plan 6:** 6.1 → (6.2 nếu app hỏi) → 6.3 → lặp {6.4 | 6.5, 6.6} → 6.7 tuỳ ý. Mỗi phiên mở trong cửa sổ Review
riêng; cửa sổ live vẫn chạy.

## 7. Xuất luồng sang công cụ ngoài (LSL)

```mermaid
flowchart TD
    T7["7. Xuất LSL"] --> T71["7.1 Cài pylsl<br/>pip install -e .[lsl]"]
    T7 --> T72["7.2 Extensions ▸ LSL Outlet ▸<br/>Start LSL streams"]
    T7 --> T73["7.3 Ghi bằng LabRecorder → XDF"]
    T7 --> T74["7.4 Xem LSL status…"]
    T7 --> T75["7.5 Kiểm tra<br/>tools/lsl_check.py, xdf_check.py"]
```

**Plan 7:** 7.1 một lần → (sau 2) 7.2 → 7.3; 7.4 khi nghi ngờ; 7.5 sau khi ghi XDF.

## 8. Phát triển & nhúng extension (vai phát triển)

```mermaid
flowchart TD
    T8["8. Phát triển extension"] --> T81["8.1 Tạo khung"]
    T81 --> T811["CLI: python -m musemonitor.plugins<br/>new 'Tên' --category …"]
    T81 --> T812["GUI: Extensions ▸ Manage ▸<br/>New extension…"]
    T8 --> T82["8.2 Chọn category<br/>→ vị trí menu Analysis / HCI-BCI"]
    T8 --> T83["8.3 Viết code theo Extension API"]
    T83 --> T831["activate / deactivate"]
    T83 --> T832["Hook dữ liệu: on_eeg, on_optics, on_imu<br/>API 3: on_*_samples (ts_raw)"]
    T83 --> T833["Hook phiên: on_connected, on_event,<br/>on_recording_started/stopped"]
    T83 --> T834["UI: add_tab (BaseTab), add_action,<br/>show_status, mark_event"]
    T83 --> T835["Dữ liệu: setting/set_setting, data_dir,<br/>recording_path"]
    T83 --> T836["Tương thích: supports(spec),<br/>supports_review, requires_api"]
    T8 --> T84["8.4 Nạp vào app<br/>Check for new extensions / Update / restart"]
    T8 --> T85["8.5 Hiện panel<br/>tick trong menu"]
    T8 --> T86["8.6 Gỡ lỗi<br/>Manage ▸ Status / chi tiết lỗi"]
    T8 --> T87["8.7 Kiểm thử<br/>tests/, dữ liệu synthetic, review"]
    T8 --> T88["8.8 Bật / tắt / Unload"]
    T8 --> T89["8.9 Chia sẻ<br/>thư mục, ~/.musemonitor/extensions, pip"]
```

**Plan 8:** 8.1 (CLI hoặc GUI) → 8.2 → lặp {8.3 → 8.4 → 8.5 → (lỗi? 8.6)} đến khi chạy đúng → 8.7 → 8.9.
Extension mới mặc định ẩn: sau 8.4 phải 8.5. Thêm extension mới: 8.4 nạp ngay; sửa code extension đã nạp: phải
khởi động lại app. Extension lỗi bị tắt riêng, app tiếp tục chạy → 8.6. 8.8 khi cần so sánh có/không extension.

| UX | Ghi chú |
|---|---|
| — | Sửa code extension đang chạy phải khởi động lại app → vòng lặp 8.3–8.5 chậm |
| V10 | `show_status` của extension lẫn với thông báo hệ thống trên status bar |

## 9. Kết thúc phiên

```mermaid
flowchart TD
    T9["9. Kết thúc"] --> T91["9.1 Disconnect"]
    T9 --> T92["9.2 File ▸ New session ⌘N<br/>xoá dữ liệu, về Connect"]
    T9 --> T93["9.3 Close window ⌘W"]
```

**Plan 9:** 9.1 hoặc 9.2 để bắt đầu người tham gia tiếp theo; 9.3 để thoát. Nếu đang ghi, cả ba hỏi xác nhận
trước (✅ V2), dừng ghi và vẫn ghi report.

---

## Nhận xét từ HTA

1. **Nhiệm vụ 5 là chỗ cần chú ý nhất:** chú ý của người dùng bị chia đôi (người tham gia ↔ màn hình). V1–V3 nằm
   ở đây và đã được sửa.
2. **Vòng lặp 8.3 → 8.5 là nút thắt của vai phát triển.** Hot-reload extension đang nạp sẽ rút ngắn vòng lặp này,
   nhưng đụng vòng đời của extension nên cần đề xuất trong `debate/` trước.
3. **Nhiệm vụ 3 ↔ 4 lặp lại nhiều** nhưng chuyển qua lại chỉ cần một nút (◀ Fit-test / Accept), đã hợp lý.
4. **Nhiệm vụ 6 tách thành cửa sổ riêng** nên xem lại không chặn phiên live, khớp nhu cầu so sánh ngay trong lab.
