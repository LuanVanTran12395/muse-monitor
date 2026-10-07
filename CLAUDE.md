# Quy tắc sửa đổi Muse Monitor cho Claude

Áp dụng cho mọi lần sửa hoặc cập nhật dự án này về sau. Ưu tiên yêu cầu mới nhất của người dùng nếu họ chỉ định khác.

## Giữ cấu trúc hiện tại

- Giữ nguyên các thư mục chính `src/musemonitor/core`, `device`, `storage`, `plugins`, `ui`, cùng `tests`, `extensions`, `docs`, `data`. Không di chuyển, đổi tên hoặc xoá chúng khi sửa một tính năng.
- Giữ luồng phụ thuộc hiện tại: `ui / plugins → device / storage → core → config`; `core`, `storage` và `config` không phụ thuộc Qt.
- Giữ các entry point và giao diện công khai đang dùng: lệnh chạy app, `DeviceSpec`, `SignalStore`, định dạng CSV hiện có và extension API. Khi cần mở rộng, ưu tiên thêm module, adapter hoặc trường tuỳ chọn với lớp tương thích.
- Không sửa toàn bộ kiến trúc trong một thay đổi tính năng. Phạm vi thay đổi phải gắn với vấn đề cụ thể, giữ Muse S Athena và extension hiện có hoạt động.

## Khi thấy cần đổi cấu trúc

Trước khi di chuyển thư mục, thay giao diện công khai, đổi schema CSV hoặc thay vòng đời UI/session, hãy viết đề xuất vào `debate/` gồm: lý do, file bị ảnh hưởng, cách tương thích và cách kiểm chứng. Chờ người dùng cho phép thay đổi cấu trúc đó rồi mới thực hiện. Không diễn giải sự đồng ý với một tính năng mới thành phép thay đổi kiến trúc rộng.

## Kiểm chứng

Sau mỗi thay đổi, chạy các test liên quan và kiểm tra rõ hành vi Muse S Athena, dữ liệu ghi và extension liên quan. Báo lại các giới hạn chưa kiểm chứng với thiết bị thật.
