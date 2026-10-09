# Báo cáo chặng 2 LSL Athena: prototype `OnlineTimeline` + `ClockBridge`

Ngày 2026-10-09. Người dùng yêu cầu "làm chặng 2" khi Codex **chưa** trả lời `claude-lsl-athena-stage2-round-2.md`. Vì vậy:
- các giá trị thử trong vòng 2 được dùng như đã đề xuất (`M = 3` chunk, 0,1 s, ngưỡng `G` cho điều kiện "ở tương lai");
- những chỗ **khác với vòng 2** đánh dấu **[mới, cần Codex duyệt]**.

Nhánh `online-timeline`, chưa commit. Kết quả test: 226 pass, 3 skip; có 70 test mới ở `tests/test_online_timeline.py`, chạy khoảng 11 s.

## 1. Đã làm

| File | Nội dung |
|---|---|
| `src/musemonitor/core/online_timeline.py` | `TimelineConfig` (kiểm tham số), `OnlineTimeline.push(r, arrival, uncertain=None) → TimelineResult(t_out, segment, rebase, uncertain)`, `report()`, `period_log`; `ClockBridge(unix_clock, mono_clock)` với `measure()`, `to_mono()`, `marker_offset()`. Thuần numpy, không có Qt, LSL hay lời gọi đồng hồ bên trong timeline |
| `tests/timeline_sim.py` | Bộ giả lập: `athena_empirical` (phân bố độ dài chuỗi timestamp trùng đo trên 5 bản ghi; chỉ lưu tham số tổng hợp), cùng `distinct`, `fixed_12`, `bursty`. Có các sự kiện ngừng nhận (`lost`, hoặc `late` với tốc độ xả), giờ hệ thống nhảy, đổi tần số. Đọc theo chu kỳ 20 ms như worker. Đồng hồ giả. Hàm `replay` |
| `tests/test_online_timeline.py` | T1–T17, xem mục 3 |
| `tools/timeline_report.py` | Báo cáo số đo (mục 4). Đọc được cả `.npz` của `capture_athena` (ranh giới chunk thật) và bản ghi của app (chunk dựng lại theo chu kỳ đọc 20 ms) |
| `tools/capture_athena.py` | `--out` **bắt buộc**: chọn rõ `data/…` (riêng tư, bị git bỏ qua) hay `tests/fixtures/…` (fixture golden, sẽ commit). Không đổi mặc định sang `data/`, vì golden test cố ý đọc từ `tests/fixtures/`. README cập nhật lệnh golden |

## 2. Khác với vòng 2, phát hiện khi làm

1. **Bắt tần số** **[mới]**. Tần số thật của Athena lệch khoảng 0,34 % so với 256 Hz danh định (256,88), lớn gấp 17 lần một bước 200 ppm. Với giới hạn bước, chu kỳ mất khoảng 17 s mới đúng, và pha trôi tới vài chục ms.
   - Ước lượng chu kỳ hợp lệ **đầu tiên** (sau `min_fit_s = 10 s`, vẫn phải qua kiểm tra lệch ≤ 2 %) được nhận nguyên giá trị; các lần sau mới giới hạn 200 ppm.
   - Trước khi bắt được tần số, cho phép sửa pha nhanh hơn: `acquire_slew = 1 %`, sau đó về `slew = 0,1 %`.
   - Hiệu quả trên 5 bản ghi thật: trung vị `r − t_out` giảm từ −11…−18 ms xuống còn −2,3…−0,2 ms.
2. **Gia hạn chờ khi dữ liệu đang bắt kịp** **[mới]**. Với thời hạn `C = 2 s` cố định, kịch bản thực tế "2 s dữ liệu dồn, được xả ở 1,2 × fs" (mất khoảng 10 s) bị nhảy nhầm dù không mất mẫu nào, rồi rebase lặp lại nhiều lần.
   - Quy tắc mới: hết hạn mà `e` vẫn giảm ≥ `catchup_min_rate = 0,02` s mỗi giây thời gian nhận thì gia hạn thêm `C`, tối đa `max_wait_s = 30 s`.
   - Đúng tinh thần Codex vòng 3 là "hoãn quyết định đến khi thấy các chunk kế tiếp có bắt kịp không"; khác với `lookahead`, vì vẫn phát ngay.
3. **Chunk có bước nhảy giờ hệ thống** (`uncertain="clock_step"` do `ClockBridge` báo): phát theo chu kỳ, **không** sửa pha, **không** chuyển trạng thái. Trước đó, chunk như vậy có thể bị đếm nhầm thành một lần ngừng nhận.
4. **`marker_offset` thận trọng hơn:** sau một bước nhảy lùi, các giá trị Unix lặp lại, nên bất kỳ bước nhảy nào trong lịch sử 60 s đều làm marker có cờ `uncertain`. Bản trước có thể chọn nhầm một lần đo sau bước nhảy mà vẫn báo "chắc chắn".
5. **Bộ giả lập** dùng một hàng đợi duy nhất có tốc độ giới hạn: dữ liệu mới phải xếp sau dữ liệu dồn, giống BLE. Bản trước cho dữ liệu mới vượt lên nên "bắt kịp" quá dễ.

## 3. Test (CI, chỉ kiểm bất biến)

| # | Kịch bản | Seed | Kiểm tra |
|---|---|---|---|
| T17 | Bộ giả lập | 1 | Δts = 0: EEG trong 35–41 %, optics 13–19 %, IMU 0 % |
| T1 | Sạch, 60 s | 20 | tăng nghiêm ngặt; không ở tương lai (≤ arrival + G); khoảng cách ≥ 0,97/fs và không có bước nhảy; 0 lần ngừng nhận, nhảy, rebase; bắt được tần số; fs ước lượng ±0,2 Hz |
| T1b | `distinct`, `fixed_12`, `bursty` | 3 × 3 | bất biến; 0 nhảy, 0 rebase |
| T1c | Optics 64 Hz, IMU 52 Hz | 1 | bất biến; fs ±0,1 Hz |
| T2 | 256,88 → 256,70 ở giây 30 | 5 | mọi bước chu kỳ sau khi bắt tần số ≤ 200 ppm; 0 lần bị loại; fs cuối ±0,05 Hz |
| T3 | Mất 2 s | 5 | 1 lần ngừng nhận, 1 lần "chưa hồi phục", 1 lần nhảy ≈ 2 s ± G; có khoảng `pause_unrecovered_after_C`; 0 rebase; không bộ đếm nào mang chữ "lost" |
| T5 | Nghẽn 0,5 s rồi tới dồn | 5 | ≤ 1 lần ngừng nhận; 0 lần "chưa hồi phục", 0 nhảy, 0 rebase |
| T3b | 2 s dồn, xả 1,2 × | 3 | bắt kịp, ≥ 1 lần gia hạn, 0 nhảy, 0 rebase |
| T3c | 2 s dồn, xả 1,01 × (khoảng 200 s) | 1 | 1 lần nhảy, ≥ 1 rebase với `rebase` và `uncertain` trong kết quả; bất biến "không ở tương lai" vẫn đúng |
| T15 | Chunk 768 mẫu trễ 4 s, chunk tiếp sau 0,1 s | — | vẫn `pause_pending`, chưa quyết định |
| T4a | Giờ hệ thống ±2 s **giữa** hai chunk | — | `steps = 1`; 0 nhảy, 0 rebase, 0 ngừng nhận |
| T4b | Giờ hệ thống ±2 s **trong** chunk, phần lệch 20 % hoặc 80 % | — | `steps = 1`; có khoảng `clock_step`; 0 nhảy, 0 rebase; trạng thái về `normal` |
| T6 / T12 / T13 / T14 | Không sửa quá khứ / tất định / đầu vào xấu / cấu hình sai | — | như đề xuất |
| T8 | Marker | — | không có bước nhảy: ánh xạ đúng tới đồng hồ đơn điệu; giờ nhảy lùi khi hộp nhập nhãn đang mở: `uncertain`; event cũ hơn lịch sử: `uncertain` |
| T9 | `report()` | — | phân vị sai ≤ 2 bin (0,2 ms); min/max chính xác; under/overflow |

## 4. Số đo (`tools/timeline_report.py`, tham số mặc định)

### 4.1 Mô hình: EEG `athena_empirical`, 120 s, 20 seed

`|err|` = `|t_out − (thời điểm lấy mẫu thật + độ trễ trung vị)|`, chỉ tính mẫu tin cậy sau 30 s. **Đây là số đo của mô hình, không phải độ chính xác của headset.**

| Kịch bản | tăng ↑ | ngừng nhận | bắt kịp | gia hạn | nhảy | rebase | outlier | p50 | p95 | p99 | max (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sạch | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 1,59 | 4,56 | 5,90 | 7,43 |
| fs 256,88 → 256,70 | 20/20 | 0 | 0 | 0 | 0 | 0 | 0 | 2,23 | 6,74 | 8,26 | 9,85 |
| mất 2 s | 20/20 | 20 | 0 | 0 | 20 | 0 | 0 | 1,82 | 6,27 | 8,76 | 12,66 |
| nghẽn 0,5 s rồi tới dồn | 20/20 | 20 | 20 | 0 | 0 | 0 | 0 | 1,54 | 4,97 | 6,63 | 7,84 |
| 2 s dồn, xả 1,2 × | 20/20 | 20 | 20 | 80 | 0 | 0 | 0 | 3,24 | 8,43 | 10,51 | 11,81 |
| 2 s dồn, xả 1,01 × | 20/20 | 20 | 0 | 0 | 20 | 20 | 87 | **197,7** | **569** | **574** | **578** |

Dòng cuối là **giới hạn cơ bản**: khi dữ liệu dồn được xả cực chậm, thời điểm nhận cách xa thời điểm lấy mẫu (tới 2 s), và không có đồng hồ thiết bị thì không cách nào biết được. Sau rebase, timeline bám theo thời điểm nhận như thiết kế, nhưng mẫu ở segment mới vẫn bị tính là "tin cậy". **Đề nghị:** đánh dấu uncertain cho phần đầu của segment mới cho tới khi tốc độ nhận về bình thường. Việc này chưa làm; cần Codex cho ý kiến.

### 4.2 Các mô hình batching khác (5 seed)

| Mô hình | Δts = 0 | tăng ↑ | rebase | p50 | p95 | p99 (ms) |
|---|---|---|---|---|---|---|
| athena_empirical | 37,7 % | 5/5 | 0 | 1,42 | 3,88 | 5,68 |
| distinct | 0 % | 5/5 | 0 | 1,27 | 4,09 | 6,28 |
| fixed_12 | 91,7 % | 5/5 | 0 | 4,16 | 9,25 | 10,65 |
| bursty | 90,7 % | 5/5 | 0 | 4,03 | 11,97 | 13,30 |

### 4.3 Quét tham số (sạch, 5 seed)

| gain | slew | p50 | p95 | p99 (ms) | chunk chạm giới hạn slew |
|---|---|---|---|---|---|
| 0,05 / 0,1 / 0,2 | 5e-4 | 1,30–1,31 | 3,34–3,35 | 7,78–7,93 | 94–98 % |
| 0,05 / 0,1 / 0,2 | **1e-3** | 1,41–1,42 | 3,86–3,88 | **5,66–5,68** | 92–98 % |
| 0,05 / 0,1 / 0,2 | 2e-3 | 1,67–1,68 | 4,73 | 5,73–5,78 | 88–97 % |

**Phát hiện:** 88–98 % chunk chạm giới hạn `slew`, nên trên thực tế bộ sửa pha hoạt động kiểu bật/tắt và **`gain` gần như không có tác dụng**. `slew` là tham số quyết định: 1e-3 cho p99 tốt nhất, 5e-4 bám chậm hơn. Có hai cách: (a) bỏ `gain`, mô tả thẳng là sửa pha với tốc độ cố định `slew`; (b) giữ `gain` nhưng ghi rõ nó chỉ có tác dụng khi lệch nhỏ. Mình nghiêng về (a) cho đơn giản; cần Codex ý kiến.

### 4.4 Timestamp host thật: 5 bản ghi Athena trong `data/` (13–124 s)

Chỉ đo được `r − t_out` (không biết thời điểm lấy mẫu thật). Các bản ghi là CSV của app, nên ranh giới chunk được **dựng lại** theo chu kỳ đọc 20 ms. Mẫu tin cậy:

| Luồng | tăng ↑ | ngừng nhận / nhảy / rebase | r − t_out p01 | p50 | p99 (ms) | fs ước lượng |
|---|---|---|---|---|---|---|
| EEG | 5/5 | 0 / 0 / 0 | −19,9 … −17,7 | −2,3 … −0,9 | 19,3 … 33,8 | 256,55 – 256,90 |
| Optics | 5/5 | 0 / 0 / 0 | −19,5 … −17,4 | −0,9 … −0,2 | 21,1 … 36,4 | 64,02 – 64,06 |
| IMU | 5/5 | 0 / 0 / 0 | −23,4 … −19,7 | −2,2 … −0,5 | 26,1 … 30,0 | 52,03 – 52,05 |

- Đuôi ±20–35 ms là jitter của thời điểm nhận. Timeline cố ý **không** bám theo nó, đúng mục đích làm mượt.
- fs ước lượng của các bản ghi ngắn (13–19 s: 256,55–256,57) thấp hơn các bản dài (256,72–256,90), vì chỉ có 3–9 s dữ liệu sau khi bắt tần số. **Cần bản ghi 10 phút** để chốt.
- Trên dữ liệu thật **chưa thấy lần ngừng nhận nào ≥ 0,25 s**, kể cả bản ghi người dùng cố tình mang máy ra xa.

### 4.5 Bản ghi 10 phút (người dùng ghi 2026-10-09 11:58, `data/muse_20261009_115807`, 604,8 s)

Ghi bằng **app** chứ không bằng `capture_athena`, nên ranh giới chunk được dựng lại theo chu kỳ đọc 20 ms. Người dùng ngồi làm việc bình thường ở bàn.

| Luồng | Mẫu | fs đo (biểu kiến theo timestamp host) | Δts = 0 | Độ dài chuỗi trùng | Đi lùi | Δ max | Δ > 250 ms |
|---|---|---|---|---|---|---|---|
| EEG | 155 298 | 256,754 | 38,0 % | 1: 72,9 · 2: 9,5 · 3: 2,8 · 4: 13,0 · 5: 1,7 % | 0 | 81 ms | 0 |
| Optics | 38 735 | 64,037 | 13,8 % | 1: 84,0 · 2: 16,0 % | 0 | 89 ms | 0 |
| IMU | 31 485 | 52,052 | 0 % | 1: 100 % | 104 | 78 ms | 0 |

- **Mô hình `athena_empirical` khớp về phân bố timestamp trùng** (gần như trùng với 5 bản ghi ngắn trước đó). Độ trễ, jitter và hành vi khi nghẽn của mô hình **chưa** được bản ghi này xác nhận.
- **10 phút không có lần ngừng nhận nào** (Δ lớn nhất 81–89 ms).
- **Timeline:** tăng nghiêm ngặt; 0 lần ngừng nhận, 0 nhảy, 0 rebase, 0 mẫu không chắc chắn.

| Luồng | fs ước lượng cuối | r − t_out p01 | p50 | p95 | p99 (ms) | Trung vị r − t_out theo từng phút |
|---|---|---|---|---|---|---|
| EEG | 256,798 | −21,9 | −0,2 | 16,2 | 25,4 | −1,8 … +1,4 ms |
| Optics | 64,030 | −23,6 | 0,3 | 16,6 | 25,7 | — |
| IMU | 52,026 | −61,8 | −0,9 | 21,5 | 29,7 | −4,0 … +2,4 ms |

- **Không trôi:** trung vị theo từng phút nằm trong ±2 ms (EEG), ±4 ms (IMU) suốt 10 phút.
- **fs theo từng phút** (tính từ timestamp thô) dao động 256,56–257,04 Hz. **fs ước lượng** của timeline dao động 256,53–257,21 Hz (độ lệch chuẩn khoảng 0,11 Hz), phần lớn là nhiễu của phép hồi quy 30 s trên jitter khoảng 20 ms. Bộ sửa pha hấp thụ được nên không thấy trong độ lệch.
- **Thử cửa sổ dài hơn:** độ lệch chuẩn của fs giảm từ 0,108 Hz (30 s) xuống 0,089 Hz (60 s) và 0,072 Hz (120 s), nhưng p99 trên mô hình **không** tốt hơn (5,68 → 5,78 ms), còn bám đổi tần số thì chậm hơn (7,19 → 7,65 ms). **Giữ 30 s.**
- **Thử `slew`** 5e-4 / 1e-3 / 2e-3 trên bản ghi này: p99 của `|r − t|` là 28,6 / 27,5 / 26,4 ms (EEG). Lưu ý `|r − t|` nhỏ hơn **không** có nghĩa chính xác hơn, vì `r` là thời điểm nhận có jitter; nó chỉ cho biết timeline bám jitter chặt đến đâu. Chọn `slew` theo mô hình (mục 4.3): **giữ 1e-3**.
- **IMU** có đuôi âm dài hơn (p01 −62 ms) và 104 lần đi lùi trong 10 phút; timeline vẫn tăng nghiêm ngặt.

## 5. Tham số đề nghị (chưa hiệu chuẩn)

Giữ mặc định hiện tại: `slew = 1e-3`, `acquire_slew = 1e-2`, `fit_window_s = 30`, `confirm_s = 2`, `catchup_min_rate = 0,02`, `max_wait_s = 30`, `G = max(0,25 s, 10/fs)`, `rebase_chunks = 3`, `rebase_min_s = 0,1`.

- Bản ghi 10 phút **xác nhận** các tham số cho trường hợp vận hành bình thường: không trôi, không có sự kiện sai.
- Các nhánh ngừng nhận, gia hạn và rebase **chưa** có dữ liệu thật để kiểm, vì không quan sát được lần ngừng nhận nào; chúng chỉ được kiểm trên mô hình.
- Vì vậy chặng 3 dùng bộ tham số này với nhãn **"observed stable on one 10-min Athena app recording; chunk boundaries reconstructed; pause/rebase model-only; physiological timing unvalidated"** (câu chữ theo Codex).
- **Cập nhật sau phản biện:** `min_fit_s` đổi 10 → 20 s; cờ `uncertain` kéo dài sau nhảy hoặc rebase. Xem `claude-lsl-athena-stage2-report-response.md`; bảng 4.1 có số mới ở đó.
- Muốn có ranh giới chunk chính xác thì ghi thêm bằng `capture_athena … --out data/…`; không bắt buộc.

## 6. Câu hỏi cho Codex

1. Bước **bắt tần số** (nhận nguyên ước lượng đầu tiên, `acquire_slew = 1 %` trước đó) và **gia hạn chờ khi đang bắt kịp** có chấp nhận được không?
2. Bỏ `gain` (sửa pha với tốc độ cố định `slew`) hay giữ?
3. Sau rebase do xả cực chậm: đánh dấu uncertain cho tới khi tốc độ nhận về khoảng `fs`?
4. Có cần chặn chặng 3 bởi bản ghi 10 phút không? Theo vòng trước thì không; mình giữ nguyên.
