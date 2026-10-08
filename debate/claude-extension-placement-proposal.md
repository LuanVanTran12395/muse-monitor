# Đề xuất: gọn giao diện extension — panel bật/tắt qua menu bar, vị trí do extension khai báo

Trạng thái: **đã duyệt 2026-10-08 — phương án A, với Eyes và Motion trong một menu riêng `HCI/BCI`** (xem mục *Quyết định* cuối file). Đề xuất thay đổi giao diện và thêm trường tuỳ chọn vào API extension, nên theo `CLAUDE.md` cần được cho phép trước khi làm. Không đổi cấu trúc thư mục, CSV, `DeviceSpec`, `SignalStore`, hay vòng đời phiên.

## Vấn đề

Mỗi extension có giao diện đều gọi `app.add_tab(...)`, nên thanh tab của màn Recording dài ra theo số extension:

```
Signals | EEG PSD | PPG · HRV · fNIRS | Artifacts | Band power | Eyes · EEG/alpha | 3D head | 3D head +
```

Đã có 5 tab extension, trong khi người dùng thường chỉ cần 1–2 cái mỗi lần. Các action của extension cũng nằm lẫn trong một menu Extensions phẳng: "Hello: say hi", "Band power: clear history", "Artifacts: clear list"…

## Các phương án

| | Phương án | Gọn mắt | Thay đổi | Rủi ro |
|---|---|---|---|---|
| A | **Tab ẩn mặc định, bật/tắt qua menu `Analysis`** theo nhóm; chỉ tab đã bật mới hiện | Cao | Nhỏ: `RecordingPage` dùng `setTabVisible`, thêm một menu | Thấp: hook của tab giữ nguyên |
| B | Panel thành **dock** (kéo ra cạnh, nổi, gộp tab với nhau) | Cao, linh hoạt | Vừa: hook `on_frame`/`on_analysis` hiện chỉ gọi cho tab đang chọn, phải thêm logic "dock đang hiện" | Vừa: đổi vòng đời hiển thị của tab |
| C | Gom mọi extension vào **một tab "Extensions"** có danh sách bên trái | Cao | Vừa: tab chứa tab | Thấp, nhưng phải bấm 2 lần mới tới panel; không xem được 2 panel cạnh nhau |
| D | Mỗi panel là **cửa sổ riêng** | Trung bình | Vừa | Nhiều cửa sổ rời rạc, và mỗi cửa sổ phải tự quản lý theme |

**Đề xuất: A**, và để B làm bước sau nếu cần. A giải quyết đúng vấn đề rối mắt, giữ nguyên `BaseTab` và các hook, và mọi extension hiện có chạy tiếp mà không phải sửa.

## Phương án A chi tiết

### Menu bar

```
File      View                    Analysis                         Extensions
          ☑ Events list (review)  EEG ▸        ☐ Band power        Band power ▸ Clear history
                                  Eyes ▸       ☐ Eyes · EEG/alpha  Artifacts ▸  Clear list
                                  Motion ▸     ☐ 3D head           Hello World ▸ Say hi
                                               ☐ 3D head +         ─────────────
                                  Data quality ▸ ☐ Artifacts       Check for new extensions
                                  ─────────────                    Manage extensions…
                                  Show all  /  Hide all
```

- **`Analysis`** (mới) chứa **panel** của extension, chia theo nhóm. Mỗi mục là ô tick: tick thì tab hiện, bỏ tick thì tab ẩn. Lựa chọn được nhớ trong QSettings, riêng cho từng extension và từng loại cửa sổ (live hay xem lại).
- **`Extensions`** chỉ còn **hành động** của extension, gom theo submenu mang tên từng extension, cùng 2 mục quản lý như hiện nay.
- **`View`** chưa cần ở bước này. Sơ đồ trên chỉ minh hoạ chỗ đặt tuỳ chọn hiển thị sau này (ví dụ ẩn/hiện danh sách event); có thể bỏ.
- Ba tab có sẵn (Signals, EEG PSD, PPG · HRV · fNIRS) **luôn hiện**, không đưa vào menu.
- **Mặc định khi mới cài:** panel của extension **ẩn**. Lần đầu extension được nạp, thanh trạng thái báo: "New panel 'Artifacts' — Analysis ▸ Data quality". Để bạn đỡ bất ngờ sau khi cập nhật, panel nào bạn đã dùng trước đó có thể bật sẵn (xem câu hỏi 2).

### API (bổ sung, tuỳ chọn, tương thích ngược)

Gộp vào API 2 vì API 2 chưa được commit (nhánh `review-extensions`):

| Trường / tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `Extension.category` | `"Other"` | Nhóm trong menu `Analysis`: `"EEG"`, `"Heart & optics"`, `"Eyes"`, `"Motion"`, `"Data quality"`, `"Other"`. Tên lạ thì xếp vào `Other` |
| `add_tab(tab, title=None, shown=None)` | `shown=None` = theo lựa chọn đã lưu, mặc định ẩn | Extension không tự ép tab hiện; người dùng quyết |
| `add_action(text, cb, shortcut=None)` | — | Không đổi chữ ký; app tự đặt action vào submenu mang tên extension |

Extension cũ không có `category` thì nằm ở `Analysis ▸ Other` và vẫn chạy. Không có gì bị bỏ.

### Gợi ý vị trí khi tạo extension mới

`python -m musemonitor.plugins new "My Extension"`:
- Thêm tuỳ chọn `--category EEG`. Nếu không truyền, CLI **gợi ý** nhóm dựa trên từ khoá trong tên (alpha/band/psd → EEG; blink/eye/gaze → Eyes; head/imu/motion → Motion; hr/ppg/hrv/fnirs → Heart & optics; artifact/quality/noise → Data quality) và in ra:

  ```
  Created extensions/my_extension/
  Its panel will appear in: Analysis ▸ EEG ▸ My Extension  (hidden until ticked)
  Its actions will appear in: Extensions ▸ My Extension ▸ …
  Change `category = "EEG"` in extensions/my_extension/__init__.py to move it.
  ```
- Template có sẵn dòng `category = "..."` kèm comment liệt kê các nhóm hợp lệ.
- Hộp thoại **Manage extensions** có thêm cột **Menu**, ví dụ `Analysis ▸ EEG`, để biết mỗi extension nằm ở đâu.

### Nhóm cho các extension hiện có

| Extension | `category` | Có panel |
|---|---|---|
| `band_power` | EEG | ✓ |
| `eye_interaction` | Eyes | ✓ |
| `head_motion`, `head_motion_plus` | Motion | ✓ |
| `artifact_log` | Data quality | ✓ |
| `hello_world` | Other | — (chỉ có action) |

## File bị ảnh hưởng

| File | Thay đổi |
|---|---|
| `ui/pages/recording_page.py` | `set_tab_shown(tab, on)` (dùng `setTabVisible`); `on_analysis` bỏ qua tab đang ẩn; tab đang chọn bị ẩn thì chuyển về Signals |
| `ui/main_window.py`, `ui/review_window.py` | Menu `Analysis` dựng từ các extension đang chạy; lưu/đọc lựa chọn hiển thị; action gom vào submenu |
| `plugins/api.py` | `category`; tham số `shown` trong `add_tab`; `add_action` đặt vào submenu của extension |
| `plugins/manager.py` | Khi unload/load thì cập nhật menu; thêm thông tin vị trí menu cho hộp thoại |
| `plugins/scaffold.py`, `plugins/__main__.py` | `--category`, gợi ý theo từ khoá, in ra vị trí |
| `ui/widgets/extensions_dialog.py` | Cột Menu |
| `extensions/*` | Thêm một dòng `category = ...` mỗi extension |
| `docs/EXTENSIONS.md`, `README.md` | Mục "Where your extension appears" |
| `tests/` | Test mới (dưới đây) |

**Không đổi:** cấu trúc thư mục, `BaseTab` và các hook của tab, `PlotRegistry`/marker, cửa sổ xem lại và phát lại, CSV, lệnh chạy app.

## Kiểm chứng

- Mặc định: chỉ 3 tab có sẵn hiện; menu `Analysis` có đủ nhóm và mục; tick thì tab hiện, bỏ tick thì ẩn; lựa chọn còn sau khi mở lại cửa sổ.
- Tab ẩn không bị gọi `on_frame`/`on_analysis`. Ẩn tab đang chọn thì về Signals.
- Unload/Load một extension: mục menu và submenu action biến mất rồi xuất hiện lại đúng chỗ; extension lỗi thì mục bị vô hiệu.
- Extension không có `category` nằm ở `Other` và vẫn chạy; extension API 1 trong `tests/test_plugins.py` vẫn pass.
- Cửa sổ xem lại có menu riêng, lựa chọn lưu riêng.
- `plugins new` gợi ý đúng nhóm cho vài tên mẫu; `--category` ghi đè được gợi ý; tên nhóm lạ báo lỗi kèm danh sách hợp lệ.
- Toàn bộ test hiện có pass; chụp ảnh menu ở cả hai theme.

## Câu hỏi cho người dùng

1. Chọn A (đề xuất), hay muốn dock (B) ngay từ đầu?
2. Panel mặc định **ẩn** hết, hay bật sẵn những panel bạn đang dùng? Nếu bật sẵn thì là những cái nào?
3. Tên menu: `Analysis` có ổn không, hay muốn `Panels` / `Tools`? Danh sách nhóm trên đã đủ chưa?
4. Làm chung nhánh `review-extensions` (chưa commit) hay tách nhánh riêng sau khi commit phần extension xem lại?

## Quyết định (2026-10-08)

Người dùng chọn A, kèm một thay đổi: hai nhóm Eyes và Motion **không** nằm trong `Analysis` mà ở một menu riêng tên **`HCI/BCI`**. Menu bar:

```
File | Analysis (EEG · Heart & optics · Data quality · Other) | HCI/BCI (Eyes · Motion) | Extensions
```

Extension vẫn chỉ khai báo `category`; bảng `CATEGORIES` trong `plugins/api.py` quyết định nhóm nào thuộc menu nào. Hai câu hỏi người dùng chưa trả lời được làm theo mặc định của đề xuất:
- panel **ẩn** khi mới cài, kèm một thông báo trên thanh trạng thái lần đầu;
- làm chung nhánh `review-extensions`.

Kết quả: `debate/claude-extension-placement-report.md`.
