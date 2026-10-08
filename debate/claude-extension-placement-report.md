# Báo cáo: panel extension trong menu bar (Analysis, HCI/BCI)

Ngày 2026-10-08. Làm theo `claude-extension-placement-proposal.md` với quyết định của người dùng: phương án A, hai nhóm Eyes và Motion nằm trong menu riêng **HCI/BCI**. Nhánh `review-extensions` (chung với giai đoạn 2), chưa commit.

Kết quả test: 142 pass, 3 skip. Trong đó có 16 test mới ở `tests/test_panels.py`; 2 test cũ được chỉnh cho khớp vị trí action và thứ tự menu.

## Kết quả

```
File | Analysis (EEG · Heart & optics · Data quality · Other) | HCI/BCI (Eyes · Motion) | Extensions
```

- **Panel ẩn đến khi được tick:** mỗi tab do extension thêm là một *panel*, chỉ hiện khi được tick trong menu của nó.
  - Mặc định là ẩn. Lần đầu panel được nạp, thanh trạng thái báo chỗ tìm, ví dụ "5 new extension panels — tick them in the Analysis and HCI/BCI menus".
  - Tick thì tab hiện và được chọn; bỏ tick tab đang chọn thì app chuyển về Signals.
- **Nhớ lựa chọn:** lưu trong QSettings, riêng cho cửa sổ live (`panels/live/…`) và cửa sổ xem lại (`panels/review/…`).
- **Show all / Hide all:** mỗi menu có hai mục này, chỉ áp dụng cho chính menu đó. Nhóm không có panel thì không hiện; menu trống hiện "No extension panels" (bị vô hiệu).
- **Action:** nằm trong **Extensions ▸ ‹tên extension› ▸ …**. Đã bỏ tiền tố trùng lặp: "Band power: clear history" → "Clear history"; "Artifacts: clear list" → "Clear list"; "Hello: say hi" → "Say hi".
- **Hộp thoại Manage extensions:** thêm cột **Menu**, ví dụ "Analysis ▸ EEG", "HCI/BCI ▸ Eyes", "Extensions ▸ Hello World (actions only)".
- **Tạo extension mới:**
  - `python -m musemonitor.plugins new` gợi ý `category` dựa vào từ khoá trong tên. Ví dụ: alpha/band/psd → EEG; eye/blink/gaze/wink → Eyes; head/imu/motion → Motion; hrv/ppg/fnirs/breath → Heart & optics; artifact/quality/noise → Data quality.
  - CLI in ra vị trí sẽ xuất hiện; `--category` ghi đè gợi ý; tên nhóm lạ thì báo lỗi kèm danh sách nhóm hợp lệ.
  - Template có sẵn dòng `category = "..."` kèm comment liệt kê các nhóm.
  - Nút "New extension…" trong hộp thoại cũng gợi ý và báo vị trí.

## Vị trí của các extension hiện có

| Extension | `category` | Menu |
|---|---|---|
| `band_power` | EEG | Analysis ▸ EEG |
| `artifact_log` | Data quality | Analysis ▸ Data quality |
| `eye_interaction` | Eyes | HCI/BCI ▸ Eyes |
| `head_motion`, `head_motion_plus` | Motion | HCI/BCI ▸ Motion |
| `hello_world` | Other | chỉ có action: Extensions ▸ Hello World |

## API (gộp vào API 2, chưa phát hành)

- `Extension.category`: mặc định `"Other"`; giá trị lạ cũng được coi là `Other`.
- `plugins.api.CATEGORIES`: bảng nhóm → menu.
- `app.add_tab(tab, title=None, shown=None)`: `shown` chỉ có tác dụng lần đầu tiên; sau đó lựa chọn của người dùng được ưu tiên.
- `app.add_action`: chữ ký không đổi; action tự vào submenu của extension.
- Extension không có `category` vẫn chạy (nằm ở Analysis ▸ Other); có test cho trường hợp này.

## File

- **Mới:** `src/musemonitor/ui/panels.py`, `tests/test_panels.py`, báo cáo này.
- **Sửa:**
  - `plugins/api.py`, `plugins/manager.py`, `plugins/scaffold.py`, `plugins/__main__.py`
  - `ui/main_window.py`, `ui/review_window.py`, `ui/pages/recording_page.py` (`set_tab_shown`), `ui/widgets/extensions_dialog.py`
  - 6 extension mẫu (thêm `category`, bỏ tiền tố action)
  - `tests/test_plugins.py`, `tests/test_review.py`
  - `docs/EXTENSIONS.md` (mục "Where your extension appears"), `README.md`
- **Không đổi:** cấu trúc thư mục, `BaseTab` và các hook của tab, `PlotRegistry` và marker, `SignalStore`, CSV, lệnh chạy app.

## Kiểm chứng

- Tự động (`tests/test_panels.py`):
  - thứ tự menu bar và nội dung từng nhóm;
  - panel ẩn mặc định, 3 tab có sẵn luôn hiện;
  - tick hiện và chọn tab, bỏ tick ẩn tab và về Signals;
  - lựa chọn được nhớ sang cửa sổ mới;
  - Show all / Hide all chỉ tác động đúng menu;
  - thông báo panel mới chỉ một lần;
  - Unload / Load cập nhật cả menu panel lẫn submenu action;
  - `category` thiếu hoặc lạ; `shown=True` lần đầu;
  - menu trống;
  - cửa sổ xem lại có lựa chọn riêng (Eyes/Motion không có ở đó vì chỉ chạy live);
  - cột Menu trong hộp thoại;
  - gợi ý nhóm cho 6 tên mẫu, CLI và `--category`.
- Bằng mắt: đã render cửa sổ thật (thanh tab chỉ còn 3 tab có sẵn + 2 panel đã tick) cùng nội dung các menu Analysis, HCI/BCI, Extensions.

## Chưa kiểm chứng

- Menu native của macOS khi chạy thật (test chạy offscreen). Trên macOS, Qt đưa menu bar lên thanh menu hệ thống; cần người dùng mở thử.
- Sau khi cập nhật, các panel bạn đang dùng sẽ **ẩn** cho tới khi tick lại một lần. Đây là mặc định đã chọn; nếu muốn bật sẵn một số panel thì chỉ cần thêm `shown=True` ở extension đó.
