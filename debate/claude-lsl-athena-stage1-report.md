# Báo cáo: chặng 1 LSL Athena — extension API v3

Ngày 2026-10-08. Người dùng duyệt "chặng 1 API v3". Làm theo mục 2 của `claude-lsl-athena-round-2.md`, các điều chỉnh của `codex-lsl-athena-round-3/4.md`, và mục *Chốt* cuối `claude-lsl-athena-round-3.md`. Nhánh `api-v3`, chưa commit.

Kết quả test: 156 pass, 3 skip; có 9 test mới ở `tests/test_api_v3.py`.

## Thay đổi

| File | Thay đổi |
|---|---|
| `plugins/api.py` | `API_VERSION = 3`; ba hook mới `on_eeg_samples(x, ts_raw)`, `on_optics_samples`, `on_imu_samples`, có docstring nói rõ `ts_raw` là thời điểm host nhận, có thể trùng hoặc đi lùi, và chỉ có ở live |
| `plugins/manager.py` | `HOOKS` thêm 3 tên; `wants(hook)` cho biết có extension nào override hook đó |
| `ui/main_window.py` | `on_data`, `on_optics`, `on_imu` gọi hook v3 **sau** hook cũ, với đúng `ts` nhận từ worker (`float64`). Nếu worker chỉ đưa một số thì khai triển bằng `core.timing.ts_vector`. Khi không có extension nào dùng hook v3 thì bỏ qua hoàn toàn (`_dispatch_samples`) |
| `docs/EXTENSIONS.md` | bảng hook, `requires_api` (app cung cấp 3), mục mới §10 *Per-sample timestamps (API 3)* |
| `README.md` | dòng `api.py` |
| `tests/test_review_extensions.py` | phép kiểm phiên bản đổi từ `== 2` thành `>= 2` |

**Không đổi:**
- chữ ký hook cũ;
- `plugins/replay.py`: cửa sổ xem lại vẫn chỉ phát lại hook API 1;
- worker, Recorder, CSV, `SignalStore`;
- cửa sổ xem lại.

## Test (`tests/test_api_v3.py`)

| Test | Kiểm tra |
|---|---|
| `test_version_and_requires_api` | `API_VERSION == 3`; extension `requires_api = 3` chạy, `= 4` bị đánh dấu *incompatible* |
| `test_per_sample_timestamps_are_exactly_what_the_worker_delivered` | timestamp kiểu Athena (gói 12 mẫu chung một giá trị): ghép các `ts_raw` lại **trùng từng bit** với vector worker đưa, giữ nguyên các giá trị trùng; dữ liệu khớp; `float64`, độ dài đúng |
| `test_same_values_as_the_csv` | `ts_raw` của hook bằng đúng cột `timestamp` mà `Recorder` ghi (so sau khi đọc lại CSV) |
| `test_old_hooks_unchanged_and_called_first` | hook API 1 vẫn nhận timestamp mẫu cuối dạng `float` và được gọi trước; extension chỉ có hook cũ không bị ảnh hưởng |
| `test_all_three_streams` | optics và IMU; IMU đi lùi được truyền nguyên trạng |
| `test_scalar_timestamp_from_an_old_worker_is_expanded` | worker cũ đưa một số thì được khai triển theo `fs` danh định, mẫu cuối giữ đúng giá trị |
| `test_no_cost_when_no_extension_uses_v3` | không extension nào override thì `ts_vector` không bị gọi |
| `test_error_in_v3_hook_is_isolated` | lỗi trong hook v3 chỉ tắt extension đó, kèm tên hook trong thông báo; extension khác vẫn nhận dữ liệu |
| `test_review_windows_never_call_v3_hooks` | trong cửa sổ xem lại, extension `supports_review` chỉ nhận hook API 1 |

## Chưa làm (các chặng sau, đã thống nhất trong debate)

- Chặng 2: prototype `OnlineTimeline`, CI dùng dữ liệu tổng hợp 20 seed, kèm báo cáo số đo để chốt tham số.
- Chặng 3: extension `lsl_outlet` (EEG + Markers, `push_chunk` với vector timestamp).
- Dữ liệu thật cho chặng 2: theo đề nghị gửi người dùng, gồm một bản ghi 10 phút ngồi yên và một bản ghi khoảng 3 phút có gián đoạn BLE được đánh nhãn. Chỉ để trong `data/`, không đưa vào repo.

## Kiểm chứng trên Muse S Athena thật (2026-10-09)

Dùng extension kiểm tra `TS Check` (đặt ngoài repo, ở `~/.musemonitor/extensions/ts_check.py`). Nó dùng hook API 3, ghép mọi `ts_raw` nhận được rồi so với cột `timestamp` của CSV trong một phiên ghi khoảng 30 s:

| Luồng | Kết quả | Số mẫu CSV | Δts = 0 | Lần đi lùi |
|---|---|---|---|---|
| EEG | **OK**: chuỗi `ts_raw` trùng từng bit với CSV | 7752 (≈ 30,3 s) | 38 % | 0 |
| Optics | **OK** | 1936 | 14 % | 0 |
| IMU | **OK** | 1569 | 0 % | 2 |

Kết luận: hợp đồng chặng 1 đúng trên thiết bị thật (vector timestamp của hook bằng đúng vector CSV ghi). Đặc điểm timestamp lặp lại số đo trước đó (38 % / 14 % trùng ở EEG/optics, IMU có đi lùi), là cơ sở cho `OnlineTimeline` ở chặng 2.
