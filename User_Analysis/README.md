# User Analysis — Muse Monitor

Phân tích người dùng cho Muse Monitor: persona, Hierarchical Task Analysis (HTA) và Information Architecture (IA).
Dựng từ mã nguồn (`src/musemonitor/ui`, `plugins/api.py`, `storage/session.py`, `extensions/`) và ảnh
chụp trong `docs/screenshots/` — trạng thái nhánh `lsl-outlet`, 2026-10-18. Chưa kiểm chứng bằng phỏng vấn
hay usability test với người dùng thật.

| File | Nội dung |
|---|---|
| [HTA.md](HTA.md) | Cây nhiệm vụ 0 → 9, plan cho từng nhiệm vụ, điểm đau UX gắn với từng bước |
| [IA.md](IA.md) | Cấu trúc cửa sổ / màn hình / menu / hộp thoại, luồng điều hướng, cấu trúc dữ liệu và extension |
| [IA.png](IA.png) | Sơ đồ IA dạng cây (sitemap) của toàn app — nguồn: [diagrams/ia.mmd](diagrams/ia.mmd) |
| [Navigation_map.png](Navigation_map.png) | Bản đồ điều hướng: trang, hộp thoại, cửa sổ Review, dữ liệu và thao tác chuyển giữa chúng — nguồn: [diagrams/navigation.mmd](diagrams/navigation.mmd) |

Sơ đồ viết bằng [Mermaid](https://mermaid.js.org): hiển thị trực tiếp trên GitHub; trong VSCode cần extension
*Markdown Preview Mermaid Support*, hoặc dán khối mã vào <https://mermaid.live>.

## Persona

**Nhà nghiên cứu BCI (R&D)** — kỹ sư / nghiên cứu sinh / nhà khoa học trong phòng lab HCI–BCI.

| | |
|---|---|
| **Mục tiêu** | (1) xem tín hiệu Muse trực tiếp, nhanh và tin cậy; (2) ghi dữ liệu có event và timestamp dùng được cho phân tích; (3) tự viết và nhúng extension (thuật toán, giao diện BCI, cầu nối LSL) mà không phải sửa lõi app |
| **Bối cảnh** | Vừa vận hành máy vừa hướng dẫn người tham gia → chú ý bị chia đôi; phiên ghi dài, lặp lại; dữ liệu phải tái lập được |
| **Năng lực** | Biết Python, hiểu EEG cơ bản (kênh, nhiễu, PSD); không muốn mất thời gian với BLE, định dạng file, Qt boilerplate |
| **Thiết bị** | Muse S Athena (EEG 256 Hz, optics/PPG 64 Hz, IMU 52 Hz); có thể thêm thiết bị khác qua device profile |
| **Nỗi lo** | Mất/hỏng dữ liệu giữa phiên; không biết app có đang ghi; timestamp lệch; extension lỗi làm sập app |
| **Thước đo thành công** | Thời gian từ mở app → bắt đầu ghi; 0 phiên bị mất; thời gian từ ý tưởng → extension chạy trong app |

Hai "vai" của cùng persona được tách trong HTA:
- **Vai vận hành** (nhiệm vụ 1–7, 9): kết nối, kiểm tra, xem, ghi, xem lại, xuất LSL.
- **Vai phát triển** (nhiệm vụ 8): tạo, nạp, gỡ lỗi, chia sẻ extension.
