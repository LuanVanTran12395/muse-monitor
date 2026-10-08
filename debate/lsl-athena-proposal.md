# Đề xuất: LSL outlet cho Muse S Athena

Ngày: 2026-10-08. Phạm vi: **Muse S Athena đang đo trực tiếp**. Không phát lại phiên review ra LSL, không đổi CSV hay luồng thu từ BrainFlow. Tài liệu này mô tả thay đổi API bổ sung trước khi sửa mã, theo `CLAUDE.md`.

## 1. Những gì đã có trong repo

- `device/worker.py` đã nhận EEG, optics và IMU từ BrainFlow dưới dạng `(x, ts, seq)`, với `ts` là vector timestamp Unix cho từng mẫu. `Recorder` ghi chính vector đó vào CSV mà không chỉnh sửa.
- `ui/main_window.py:on_data/on_optics/on_imu` nhận đủ vector `ts`, thêm vào `SignalStore`, nhưng chỉ dispatch hook extension v1 `on_eeg/on_optics/on_imu(x, last_ts)`; extension không thấy timestamp của từng mẫu.
- `ui/main_window.py:add_event` dispatch `on_event(t, label)` với `t` Unix. Nút Space lấy thời điểm trước khi mở hộp nhập nhãn.
- Extension API hiện là **v2**, đã có `supports_review=False` mặc định, `supports(spec)`, `on_connected`, `on_disconnected`, `add_action` và cơ chế cô lập lỗi. Review window chỉ nạp extension có `supports_review=True`.
- `DeviceSpec` có tên kênh và sampling rate. `session.json` đã ghi profile, kênh, rate và đơn vị cho file phiên. Hiện **không có** `pylsl`, `liblsl`, outlet hoặc test LSL.

## 2. Quyết định kiến trúc

Làm `extensions/lsl_outlet/` cho phần LSL; core app chỉ bổ sung hook dữ liệu có timestamp từng mẫu. Extension đặt `requires_api = 3`, `supports_review = False`, `supports(spec)` chỉ nhận Athena. API v1/v2 vẫn dispatch như hiện nay. Extension bật/tắt bằng action trong menu Extensions, mặc định **tắt** để không tạo outlet ngoài ý muốn; nó hoạt động khi đang stream, không phụ thuộc nút Start recording.

Không đưa `pylsl` vào dependencies bắt buộc. Thêm extra `lsl` trong `pyproject.toml` và hướng dẫn cài `liblsl` trên macOS. Import `pylsl` khi bật extension/outlet, không tại lúc import toàn app. Nếu thiếu native library, hiển thị lỗi rõ trong Manage/Status mà app vẫn đo và ghi CSV được.

## 3. Bổ sung extension API v3

Thêm `on_eeg_samples(x, ts)`, `on_optics_samples(x, ts)`, `on_imu_samples(x, ts)`; `ts` là vector `float64` Unix độ dài `x.shape[1]`, theo cùng thứ tự và giá trị mà `Recorder.write()` nhận. `MainWindow` dispatch chúng cùng các hook cũ, không sửa chữ ký hook cũ. `ExtensionManager.HOOKS` thêm ba tên và vẫn chỉ gọi hook được override.

BrainFlow Athena đã đưa vector thật. Khi một worker cũ đưa scalar, dùng `core.timing.ts_vector(ts, k, fs)` để khai triển và ghi rõ đây là timestamp ước lượng; test của Athena phải dùng vector. Hook v3 chỉ chạy cho live; review replay có thể giữ chỉ các hook cũ cho tới khi có hợp đồng review riêng. Không phát hook v3 trong review một cách ngầm định.

## 4. Outlet và metadata

Tạo bốn outlet riêng, chỉ khi extension đã bật và stream đang chạy:

| Outlet | Nội dung | Rate | Format |
|---|---|---:|---|
| EEG | `spec.eeg.names`, dữ liệu thô µV | `spec.eeg.fs` | float32 |
| Optics | `spec.optics.names`, cường độ quang học thô | `spec.optics.fs` | float32 |
| IMU | `spec.imu.names`, gia tốc g và gyro deg/s | `spec.imu.fs` | float32 |
| Markers | nhãn event | 0 (không đều) | string |

Metadata ghi tên kênh, đơn vị, profile `muse_athena`, model và nguồn MuseMonitor. Chọn `source_id` ổn định cho một thiết bị nhưng không chứa tên người dùng; tránh nhiều outlet trùng tên khi reconnect bằng cách đóng outlet cũ trước khi tạo mới. Không tuyên bố HSI, impedance hay fNIRS nồng độ: optics ở đây là raw channels.

## 5. Timestamp và độ tin cậy

LSL `local_clock()` là đồng hồ đơn điệu, còn `ts`/event trong app là Unix. **Không đẩy Unix timestamp trực tiếp vào LSL.** Extension lấy cặp `(time.time(), pylsl.local_clock())` gần nhau để ánh xạ `t_lsl = t_unix + offset`; cập nhật offset có kiểm soát, phát hiện bước nhảy đồng hồ hệ thống, và giữ thứ tự timestamp trong từng outlet. Ghi trong metadata/phần hướng dẫn rằng timestamp EEG ban đầu là timestamp BrainFlow, độ chính xác tới thời điểm thu thực tế chưa được xác minh bằng thiết bị đo ngoài. Không mô tả LSL là tự sửa được độ trễ BLE/BrainFlow.

Ưu tiên truyền timestamp riêng cho từng mẫu nếu vector không đều; không suy ngược toàn chunk chỉ từ `fs`. Marker dùng `t` đã được lưu trong `_events.csv`, qua cùng phép ánh xạ, để đối chiếu CSV ↔ XDF. Nếu timestamp không hữu hạn hoặc đi lùi, báo bộ đếm lỗi và quyết định rõ mẫu bị bỏ hay gán timestamp thay thế; không âm thầm phát timestamp sai.

## 6. Luồng thực thi và vòng đời

Hook chạy trên GUI thread, nên chỉ sao chép chunk cần thiết và đưa vào queue có giới hạn. Một thread của extension sở hữu toàn bộ `StreamOutlet` và thực hiện `push`; không đợi mạng/inlet trên GUI thread. Khi queue đầy, bỏ **chunk mới** hoặc cũ theo chính sách cố định, đếm số mẫu bị bỏ theo outlet và hiển thị trạng thái. `on_disconnected`, tắt action, `deactivate()` và đóng app đều dừng thread, xả/huỷ queue có giới hạn thời gian và giải phóng outlet. Lỗi trong thread phải được chuyển về GUI thread để báo/disable extension; `ExtensionManager` hiện chỉ tự cô lập lỗi xảy ra ngay trong hook/action.

## 7. Triển khai và kiểm chứng theo chặng

1. **API v3:** thêm hook và tài liệu; test vector `ts` tới extension giống CSV, hook cũ vẫn nhận float timestamp cuối, extension review không nhận dữ liệu live.
2. **EEG + Markers:** tạo extension, optional dependency, action bật/tắt, queue và clock bridge. Dùng LSL inlet giả lập xác nhận tên kênh, giá trị, số mẫu, thứ tự và marker.
3. **Optics + IMU:** thêm hai outlet với metadata đúng; test rates/channels và ngắt kết nối/reconnect.
4. **LabRecorder/XDF:** thu CSV và XDF cùng phiên giả lập, đối chiếu mẫu và timestamp sau chuyển đổi đồng hồ; kiểm tra sự kiện gần thời điểm EEG dự kiến, không đặt ngưỡng độ trễ chưa đo được.
5. **Athena thật:** thử phiên có vài event, ngắt/reconnect và theo dõi dropped samples/độ lệch; ghi kết quả và giới hạn vào README extension.

Tiêu chí hoàn thành: app chạy bình thường khi không cài LSL; extension không hoạt động ở review; bật LSL không làm UI khựng hoặc mất mẫu CSV; các outlet chỉ phản ánh stream Athena live; sai lệch thời gian và số mẫu trong XDF được đo, không suy đoán.

## Nguồn kỹ thuật

- pylsl cài đặt và thư viện native: https://github.com/labstreaminglayer/pylsl
- Quy tắc đồng bộ clock của LSL: https://github.com/sccn/labstreaminglayer/blob/master/docs/info/time_synchronization.rst

## Các file dự kiến thay đổi

`src/musemonitor/plugins/api.py`, `plugins/manager.py`, `ui/main_window.py`, `extensions/lsl_outlet/` (mới), `pyproject.toml`, `docs/EXTENSIONS.md`, `tests/test_plugins.py`, `tests/test_lsl_outlet.py` (mới). Không cần sửa `device/worker.py`, `storage/recording.py`, `core/store.py`, `ui/review_window.py` hoặc schema CSV.
