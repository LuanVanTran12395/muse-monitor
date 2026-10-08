# Đề xuất: menu File — New session và Open (xem lại phiên đã ghi)

Trạng thái: **chờ người dùng duyệt**. Đề xuất này thay đổi vòng đời UI/phiên (thêm chế độ xem lại không cần thiết bị) nên theo `CLAUDE.md` cần được cho phép trước khi làm.

## Yêu cầu (đã chốt với người dùng, 2026-10-08)

- Thêm menu **File** trên thanh menu.
- **New session**: làm mới cửa sổ — ngắt kết nối nếu đang nối, dừng ghi nếu đang ghi (vẫn xuất report như khi bấm Stop), xoá dữ liệu và event đang hiển thị, quay về màn Connect.
- **Open…**: chọn một bản ghi (folder `data/muse_<stamp>/` hoặc file `muse_eeg_<stamp>.csv` phẳng kiểu cũ). Phiên được mở trong **cửa sổ xem lại riêng**; cửa sổ đo trực tiếp vẫn chạy. Có thể mở nhiều phiên cùng lúc.
- Khi xem lại:
  - một thanh cuộn thời gian chung cho mọi plot; ô Time range quyết định độ rộng khung nhìn;
  - danh sách event, bấm vào để nhảy tới thời điểm đó;
  - các extension cũng chạy trên dữ liệu cũ.
- Không cần nút phát lại như realtime.

## Phương án

### Ý chính: "con trỏ xem"

Hiện mọi tab đọc **n mẫu mới nhất** từ `SignalStore` (`eeg_display(n)`, `opt.get(n)`, `imu.get(n)`), đặt trục x bằng `time_axis()` với mẫu cuối = 0, và marker event ở `t_event − time_ref()`.

Chế độ xem lại nạp **toàn bộ phiên** vào các `Ring` có dung lượng bằng độ dài phiên, rồi đặt con trỏ `i`/`n` của Ring tại **vị trí đang xem**. Với các tab, mẫu tại con trỏ chính là "mẫu mới nhất", nên code vẽ hầu như giữ nguyên. Cuộn = dời con trỏ rồi vẽ lại. Không sao chép dữ liệu khi cuộn.

### Trục thời gian khi xem lại

Trục x hiển thị **thời gian tính từ đầu phiên** (giây), không phải "giây trước mẫu cuối":

- `SignalStore` có thêm thuộc tính `view_offset` (live = 0, nên chế độ đo trực tiếp không đổi);
- `time_axis()` cộng `view_offset`; `time_ref()` trừ `view_offset`, nên marker vẫn khớp đúng mẫu;
- `PlotRegistry` khoá trục x ở `(view_offset − T, view_offset)` thay vì `(−T, 0)`;
- `psd_tab` và `ppg_tab` đang gọi thẳng `clock.to_axis()` sẽ đổi sang hàm của store, để cùng nhận offset.

Quy tắc khớp thời gian (`StreamClock.fit`, khớp tuyến tính 30 s gần nhất) giữ nguyên, chỉ thêm vị trí con trỏ vào khoá cache.

### Đọc dữ liệu

Thêm module mới `storage/reader.py` (không phụ thuộc Qt):

- tìm file của phiên: folder mới, hoặc bộ file phẳng cũ (`muse_eeg_<stamp>.csv` + `_optics`, `_imu`, `_events`);
- đọc CSV theo **tên cột** và bỏ qua `package_num` cho phần hiển thị, nên đọc được cả file trước và sau khi có cột này;
- tạo `DeviceSpec` cho phiên:
  - tên kênh EEG khớp Athena → dùng `athena_spec()`;
  - còn lại → spec dựng từ header CSV, với tần số ước lượng từ timestamp.
- file trống (0 byte, ví dụ iCloud chưa tải về) → báo rõ, không crash.

**Tuỳ chọn, cần bạn quyết:** từ nay ghi thêm `session.json` (profile thiết bị, tên thiết bị, phiên bản app) vào folder phiên để không phải đoán thiết bị. Đây là **file mới**; các CSV hiện có không đổi.

### Giao diện

- `ui/main_window.py`: menu **File** gồm New session (Ctrl+N), Open session… (Ctrl+O), Close window (Ctrl+W).
- `ui/review_window.py` (mới): cửa sổ dùng lại `RecordingPage` và các tab. Ẩn các nút Fit-test, Disconnect, Start recording; thêm thanh cuộn và danh sách event; tiêu đề là tên phiên.
- `app.py`: `WindowManager` giữ danh sách cửa sổ xem lại để chúng không bị thu hồi bộ nhớ, và đóng chúng khi thoát app. New session gọi từ cửa sổ xem lại sẽ đóng cửa sổ đó và đưa cửa sổ đo trực tiếp lên trước.
- Bộ lọc (Filtered/notch) khi xem lại: lọc lại toàn phiên một lần, cùng `CausalFilter` như khi đo.

### Extension trên dữ liệu cũ — cần mở rộng API (giai đoạn 2)

Các extension hiện tích luỹ trạng thái qua hook realtime (`on_eeg`…), ví dụ lịch sử band power hay bộ ước lượng chớp mắt, rồi tab của chúng vẽ "trạng thái mới nhất". Để chạy đúng khi xem lại:

1. Khi mở phiên, app **phát lại** toàn bộ dữ liệu qua `on_eeg`/`on_optics`/`on_imu`/`on_event` theo từng chunk (chạy nhanh, không theo thời gian thật), nên extension tự dựng lịch sử như lúc đo. Không cần đổi gì ở phía extension.
2. Thêm vào API (bổ sung, không phá vỡ cái cũ; `API_VERSION` 1 → 2):
   - `ExtensionContext.is_review` (bool);
   - hook `on_view_changed(t_end)` khi người dùng cuộn, để tab extension vẽ theo vị trí đang xem;
   - extension cũ không override hook này vẫn chạy, chỉ là tab của chúng hiện trạng thái cuối phiên.
3. Mỗi cửa sổ xem lại có bộ extension **riêng**, nên extension không lẫn dữ liệu giữa phiên đo và phiên xem lại.
4. Extension ghi file kèm (`on_recording_started`) **không** được gọi khi xem lại, nên không ghi đè gì.

Mình đề nghị làm giai đoạn 1 (menu, New session, xem lại + cuộn + nhảy event cho các tab có sẵn) trước, rồi giai đoạn 2 (extension) sau khi bạn duyệt riêng phần thay đổi API.

## File bị ảnh hưởng

| File | Thay đổi |
|---|---|
| `src/musemonitor/storage/reader.py` | mới: đọc phiên (folder mới, file phẳng cũ), dựng spec |
| `src/musemonitor/core/store.py` | `load_session()`, `set_cursor()`, `view_offset`; chế độ live không đổi |
| `src/musemonitor/core/timing.py` | khoá cache của phép khớp có thêm con trỏ |
| `src/musemonitor/ui/plotkit.py` | khoá trục x theo `view_offset` |
| `src/musemonitor/ui/main_window.py` | menu File, `new_session()` |
| `src/musemonitor/ui/review_window.py` | mới: cửa sổ xem lại |
| `src/musemonitor/ui/pages/recording_page.py` | thanh cuộn, danh sách event, ẩn nút live khi xem lại |
| `src/musemonitor/ui/tabs/psd_tab.py`, `ppg_tab.py` | dùng hàm trục thời gian của store |
| `src/musemonitor/app.py` | quản lý cửa sổ xem lại |
| `src/musemonitor/plugins/api.py`, `manager.py` | giai đoạn 2: `is_review`, `on_view_changed`, phát lại hook |
| `tests/test_review.py` | mới |

Không đổi: định dạng CSV, `DeviceSpec`, lệnh chạy app, API extension ở giai đoạn 1.

## Kiểm chứng

- Tạo phiên giả lập bằng `RecordingSession` thật (90 s, có event), mở lại:
  - số mẫu và giá trị khớp với dữ liệu đã ghi;
  - cuộn tới đầu, giữa và cuối phiên: trục x đúng, marker event nằm đúng mẫu;
  - nhảy event đưa khung nhìn tới đúng thời điểm;
  - mọi tab và theme Dark/Light vẽ không lỗi.
- Mở file phẳng kiểu cũ (có và không có cột `package_num`); file trống được báo lỗi rõ.
- Mở phiên khi cửa sổ live đang stream: dữ liệu live không bị ảnh hưởng.
- New session khi đang ghi: report vẫn được xuất, buffer và event sạch, quay về Connect.
- Toàn bộ test hiện có vẫn pass, kể cả trong CI.
- Thử tay với các bản ghi thật trong `data/` (cần bạn xác nhận hiển thị đúng) và đo bộ nhớ khi mở phiên dài (ước tính khoảng 60 MB cho mỗi giờ dữ liệu Athena).

## Câu hỏi cho người dùng

1. Duyệt giai đoạn 1 chưa? Duyệt luôn giai đoạn 2 (mở rộng API extension) hay để sau?
2. Có ghi thêm `session.json` cho các bản ghi mới không?
