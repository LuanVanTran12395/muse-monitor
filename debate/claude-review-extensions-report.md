# Báo cáo: giai đoạn 2 — extension trong cửa sổ xem lại (API 2) + extension `artifact_log`

Ngày 2026-10-08. Người dùng duyệt "cả hai": giai đoạn 2 theo mục 5 của `claude-session-review-round-2.md` và extension mới `artifact_log` (đề xuất số 1 trong danh sách extension). Nhánh `review-extensions`, chưa commit.

Kết quả test: 126 pass, 3 skip. Trong đó có 11 test mới ở `tests/test_review_extensions.py`.

## Thay đổi API (bổ sung, không phá vỡ API cũ)

| Thành phần | Thay đổi |
|---|---|
| `API_VERSION` | 1 → 2. Extension có `requires_api = 1` vẫn chạy ở live như cũ (đã có test) |
| `Extension.supports_review` | Mặc định `False`. Không khai báo thì trong cửa sổ xem lại hiện "not applicable", kèm lý do |
| `Extension.on_view_changed(t_end)` | Hook mới, chỉ có trong cửa sổ xem lại. `t_end` là Unix time của mép phải khung nhìn |
| `ExtensionContext.is_review`, `.view_end` | Thuộc tính mới |
| `ExtensionContext.store` | Trong lúc phát lại, trả về con trỏ phát lại; sau đó trả về store của cửa sổ |
| `mark_event` (khi xem lại) | Chỉ tạo marker tạm và thêm "(temporary)" vào danh sách event; không ghi file |
| `set_setting` (khi xem lại) | Ghi vào bộ nhớ của cửa sổ đó; QSettings không đổi |

## Hợp đồng phát lại (`plugins/replay.py`), đúng như đã cam kết

- **Chia chunk:** mỗi luồng cắt thành chunk 0,1 s. Mọi luồng và event được trộn theo thời gian của mẫu cuối mỗi chunk; event đứng sau dữ liệu tới thời điểm của nó. Luồng không có extension nào nghe thì bỏ qua.
- **Dữ liệu gửi đi:** mỗi chunk là bản sao float64, kèm timestamp gốc (raw) của mẫu cuối, giống live.
- **Tính nhất quán:** trong lúc gọi hook, `app.store` chứa đúng phần dữ liệu đã tới thời điểm đó. Điều này nhờ `ReviewStore.fork()`: một con trỏ thứ hai dùng chung mảng dữ liệu, không sao chép. Nhờ vậy việc phát lại không làm dời vị trí người dùng đang xem.
- **Chạy nền:** QTimer chạy theo từng lát 30 ms, phần trăm tiến độ hiện ở thanh trạng thái. Đóng cửa sổ thì huỷ phát lại và gọi `deactivate`.
- **Sau phát lại:** gọi `on_view_changed` một lần, rồi gọi mỗi khi người dùng cuộn.

Đo trên phiên giả lập 2 giờ, với 3 extension hỗ trợ xem lại:
- phát lại hết trong 5,0 s;
- cửa sổ bị đơ lâu nhất 78 ms;
- vẽ lại các tab mất 1–6 ms.

## Extension mẫu

| Extension | Xem lại | Thay đổi |
|---|---|---|
| `hello_world` | ✓ | Thêm `supports_review = True` |
| `band_power` | ✓ | Khi xem lại giữ toàn bộ lịch sử (live vẫn giữ 900 điểm). Tab vẽ theo `time_ref`, chỉ tới vị trí đang xem; live cũng dùng `time_ref` nên khớp marker hơn trước |
| `artifact_log` (mới) | ✓ | Xem dưới |
| `eye_interaction`, `head_motion`, `head_motion_plus` | — | Hiển thị trạng thái tức thời (avatar, tư thế đầu, camera), nên chỉ chạy ở live |

## `artifact_log`

Mỗi đoạn 1 giây liên tiếp được kiểm tra bằng các quy tắc tường minh. Ngưỡng đặt trong cài đặt của extension:

| Loại | Quy tắc | Ngưỡng mặc định |
|---|---|---|
| `blink` | Cả hai kênh trán có biên độ đỉnh-đỉnh ở 0,5–6 Hz vượt ngưỡng, và hai kênh tương quan > 0,5 | 100 µV |
| `emg` | RMS ở 30–45 Hz | 8 µV |
| `amplitude` | Biên độ đỉnh-đỉnh ở 1–40 Hz (đoạn chưa bị tính là chớp mắt) | 250 µV |
| `flat` | Độ lệch chuẩn của tín hiệu thô | 1 µV |
| `motion` | Giá trị lớn nhất của độ lớn gyro | 30 °/s |

- **Bộ lọc riêng:** extension tự lọc zero-phase trên cửa sổ 3 s, nên kết quả không phụ thuộc ô Filtered/notch.
- **Tab Artifacts:** mỗi kênh một hàng, thêm hàng `head`; mỗi loại nhiễu có một làn riêng để không che nhau; có marker event.
- **Khi đang ghi:** ghi `<rec>_artifacts.csv`. Đây là file kèm mới; CSV hiện có không đổi.
- **Tính nhất quán:** cùng một dữ liệu, kết quả khi xem lại trùng với live (có test: chớp mắt rơi đúng đoạn 4 s và 11 s ở cả hai).

**Giới hạn quan trọng: ngưỡng chưa được hiệu chỉnh trên dữ liệu thật.** Chỉ có 2 bản ghi thật (tổng 28 s) để thử, và cả hai đều rất nhiễu: biên độ đỉnh-đỉnh trung vị khoảng 1090 µV, EMG trung vị khoảng 13 µV. Kết quả là mọi đoạn đều bị đánh dấu `emg` + `amplitude`, phù hợp với tín hiệu thực tế của 2 bản ghi đó. Cần một bản ghi dài với headset tiếp xúc tốt để chỉnh `emg_uv` và `amplitude_uv`.

## Ghi chú cho người dùng

- 4 bản ghi phẳng cũ (06–07/10) không còn trong `data/`. Lần cuối thấy là sáng 2026-10-08 trước 09:58; folder `data/` được Finder thao tác lúc 10:00. Không lệnh nào trong phiên làm việc này xoá hay di chuyển chúng. Cần người dùng xác nhận đó là chủ động.
- Unload rồi Load lại một extension trong cửa sổ xem lại sẽ không phát lại dữ liệu cho nó; muốn có lại thì mở lại bản ghi. Điều này đã ghi trong `docs/EXTENSIONS.md` §9.

## File

- **Mới:**
  - `src/musemonitor/plugins/replay.py`
  - `extensions/artifact_log/__init__.py`
  - `extensions/artifact_log/README.md`
  - `tests/test_review_extensions.py`
  - báo cáo này
- **Sửa:**
  - `plugins/api.py`, `plugins/manager.py`
  - `core/review.py` (`fork`)
  - `ui/review_window.py`, `ui/main_window.py` (truyền thư mục extension sang cửa sổ xem lại)
  - `extensions/hello_world.py`, `extensions/band_power/__init__.py`
  - `docs/EXTENSIONS.md` (§4, §5, §9 mới), `README.md`

## Bổ sung (2026-10-08): sửa quy tắc chớp mắt + plot tín hiệu để đối chiếu

Người dùng thấy chớp mắt bị đánh dấu sai. Nguyên nhân trong bản đầu, theo thứ tự nghiêm trọng:
1. Đoạn 1 s được phân tích nằm ở **cuối** cửa sổ lọc zero-phase, tức đúng chỗ bộ lọc bị méo mép.
2. Quy tắc dùng biên độ đỉnh-đỉnh của cả giây và tương quan của cả giây, không xét hình dạng sóng: trôi chậm hay hai kênh cùng trôi bị tính là chớp mắt; chớp mắt trong tín hiệu nhiễu bị bỏ sót.
3. Đánh dấu cả giây, nên khó đối chiếu; chớp mắt nằm vắt qua ranh giới hai đoạn có thể bị lỡ.

**Đã sửa:**
- Chớp mắt được nhận diện theo **đỉnh**, giống `eye_interaction`:
  - lấy trung bình hai kênh trán, lọc 0,5–6 Hz;
  - đỉnh có độ nổi ≥ `blink_uv`, độ rộng 0,08–0,5 s;
  - cả hai kênh lệch cùng chiều; chấp nhận cả hai cực tính.
- Mỗi đoạn được phân tích **chậm 1 s**, khi đã có dữ liệu ở cả hai phía.
- Đánh dấu đúng khoảng của lần chớp mắt.
- Ngưỡng `blink_corr` được thay bằng `blink_min_s`, `blink_max_s`, `blink_pair_frac`.

**Tab mới:**
- Mỗi kênh vẽ tín hiệu EEG, phía sau tô mờ vùng nhiễu, ở đáy hàng có các làn theo loại; hàng `head` vẽ độ lớn gyro.
- Plot riêng cho **bộ phát hiện chớp mắt**: đúng tín hiệu mà quy tắc dùng, có đường ngưỡng ± và dấu ▼ ở các lần được chấp nhận.

**Test** (`tests/test_review_extensions.py`):
- chớp mắt được đánh dấu là một khoảng quanh đỉnh, không phải cả giây;
- chớp mắt cực tính âm trong tín hiệu nhiễu 25 µV vẫn bắt được;
- chớp mắt nằm trên ranh giới hai đoạn chỉ được tính một lần;
- liếc mắt (hai kênh ngược chiều), trôi chậm, và lệch một bên không bị tính là chớp mắt;
- live và xem lại cho cùng kết quả;
- tab vẽ đường của bộ phát hiện cùng đúng 2 dấu.

Toàn bộ: 147 pass, 3 skip.

**Kiểm tra bằng mắt** trên phiên giả lập 20 s có 3 lần chớp mắt, 1 lần liếc, 1 đợt cắn hàm, 1 đoạn trôi chậm: chỉ 3 lần chớp mắt và đợt cắn hàm bị đánh dấu.

**Vẫn chưa kiểm chứng trên dữ liệu thật đeo tốt:** ngưỡng 100 µV và độ rộng 0,08–0,5 s cần được chỉnh trên bản ghi của người dùng. Plot của bộ phát hiện giúp làm việc này: đỉnh vượt đường ngưỡng mà không có ▼ là bị loại do độ rộng hoặc do chỉ lệch một bên.

## Bổ sung: CI lỗi trên Ubuntu + Python 3.10 do PySide6 6.12.0

Lúc commit, CI của cả hai repo crash ở cùng một cấu hình là Ubuntu + Python 3.10, với lỗi `Fatal Python error: none_dealloc: deallocating None`. Ba cấu hình còn lại pass.

- **Nguyên nhân:** PySide6 6.12.0 (vừa phát hành) trừ refcount của `None` quá tay. Từ Python 3.12, `None` là bất tử nên lỗi không lộ ra; với Python 3.10/3.11 thì crash khi số lần trừ tích luỹ đủ lớn. Vì vậy chạy riêng test thì pass, chạy sau các test khác thì crash.
- **Bằng chứng:** chạy cùng bộ test trên Ubuntu + Python 3.10 (PR nháp #5, đã đóng): PySide6 6.11 pass, 6.12.0 crash. Faulthandler chỉ vào `pyqtgraph.AxisItem.setTextPen`, nhưng đó chỉ là nơi refcount cuối cùng chạm 0, không phải nơi gây lỗi.
- **Sửa:** `requirements.txt` và `pyproject.toml` chặn `PySide6>=6.6,<6.12`, có ghi chú lý do. Máy người dùng đang dùng 6.11 nên không bị ảnh hưởng. Khi PySide6 có bản sửa thì nới giới hạn này ra.
