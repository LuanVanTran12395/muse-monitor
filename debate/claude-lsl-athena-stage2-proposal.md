# Đề xuất chặng 2 LSL Athena: prototype `OnlineTimeline` + `ClockBridge`

Ngày 2026-10-09. Tiếp nối các vòng đã chốt: `claude-lsl-athena-round-3.md` (cùng mục *Chốt*), `codex-lsl-athena-round-4.md`, và báo cáo chặng 1 (API v3 đã gộp, đã kiểm chứng trên Athena thật). Chặng này **chỉ** gồm thuật toán, bộ giả lập và báo cáo số đo. Không có `pylsl`, outlet, class `Extension` hay giao diện. Codex vui lòng phản biện trước khi viết mã.

## 1. Đặt mã ở đâu

Loader coi mọi thư mục `extensions/<tên>/` có `__init__.py` là một extension. Nếu không có class `Extension` thì nó báo lỗi trong Manage (`plugins/loader.py:extension_class`). Vì vậy, tạo `extensions/lsl_outlet/` khi chưa có extension sẽ hiện một mục lỗi cho người dùng.

**Đề xuất:** đặt prototype ở `src/musemonitor/core/online_timeline.py`.
- Thuần numpy, không phụ thuộc Qt, `pylsl`, hay đồng hồ hệ thống (đồng hồ được truyền vào), nên đúng tầng `core`.
- Extension được phép import `musemonitor.core.*` (`docs/EXTENSIONS.md` §7). Chặng 3 sẽ là `extensions/lsl_outlet/` gọi vào module này.
- Thuật toán không gắn riêng với LSL: nó biến timestamp kiểu "thời điểm host nhận" thành một mốc thời gian đơn điệu, nên có thể dùng lại sau này.

Phương án khác: thư mục `extensions/_lsl_outlet/` (loader bỏ qua tên bắt đầu bằng `_`), đổi tên ở chặng 3. Cách này phải đổi tên file và đường import giữa chừng, nên không chọn.

## 2. Giao diện module

```python
@dataclass(frozen=True)
class TimelineConfig:
    fs_nominal: float
    fit_window_s: float = 30.0      # W: cửa sổ ước lượng chu kỳ
    min_fit_s: float = 10.0         # cần ≥ 10 s quan sát mới cập nhật chu kỳ
    gain: float = 0.1               # g: hệ số sửa pha
    slew: float = 1e-3              # s: |p_c − p| ≤ s·p
    period_step_ppm: float = 200    # chu kỳ đổi tối đa mỗi lần cập nhật
    period_tolerance: float = 0.02  # |p̂ − 1/fs_nominal| > 2 % → bỏ ước lượng đó
    gap_s: float = 0.25             # G = max(gap_s, gap_periods·p)
    gap_periods: int = 10
    confirm_s: float = 2.0          # C: thời hạn chờ dữ liệu tới bù


class OnlineTimeline:
    def __init__(self, config: TimelineConfig): ...
    def push(self, r: np.ndarray, uncertain: str | None = None) -> np.ndarray:
        """r: quan sát của từng mẫu (giây, miền đơn điệu: đã qua ClockBridge). Trả MẢNG MỚI t_out cùng độ dài.
        uncertain: lý do nếu bên gọi biết chunk này không đáng tin (ví dụ 'clock_step')."""
    def reset(self) -> None: ...
    state: str                       # 'normal' | 'pause_pending' | 'catching_up'
    period: float
    def report(self) -> dict: ...    # bộ đếm, phân vị của r − t_out, chu kỳ, các khoảng uncertain


class ClockBridge:
    def __init__(self, unix_clock, mono_clock, tries=3, step_s=0.05, history_s=60.0): ...
    def measure(self) -> float:            # offset = mono − unix, lấy theo cặp đọc kẹp nhau ngắn nhất trong `tries` lần
    def to_mono(self, ts_unix, offset) -> np.ndarray
    steps: int                             # số lần offset đổi > step_s giữa hai lần đo
    def marker_offset(self, t_unix) -> tuple[float, bool]   # (offset, uncertain) theo lịch sử đo (mục 3.4)
```

- `unix_clock` và `mono_clock` là các hàm được truyền vào. Ở chặng 3 sẽ là `time.time` và `pylsl.local_clock`; trong test là đồng hồ giả.
- **Không** có lời gọi đồng hồ hay I/O nào bên trong `OnlineTimeline`, nên cùng đầu vào luôn cho cùng đầu ra.

## 3. Thuật toán (bản chốt cho prototype)

### 3.1 Trạng thái nội bộ

| Biến | Ý nghĩa |
|---|---|
| `p` | chu kỳ mẫu, khởi tạo `1/fs_nominal` |
| `t_last` | timestamp đã phát của mẫu cuối (None trước chunk đầu tiên) |
| `n` | chỉ số toàn cục của mẫu kế tiếp |
| `obs` | hàng đợi `(chỉ số giữa chunk, median r)` của các chunk ở trạng thái `normal` và không bị đánh dấu `uncertain` |
| `pending` | khi ở `pause_pending`: chỉ số bắt đầu, e lúc bắt đầu, số mẫu đã nhận từ đó |
| `uncertain` | danh sách `(i_đầu, i_cuối, lý do, độ lệch ước lượng)` |
| bộ đếm | `arrival_pauses`, `pauses_caught_up`, `pauses_unrecovered_after_C`, `catch_up_episodes`, `forward_jumps` (kèm độ lớn), `period_updates`, `period_rejected`, `invalid_samples` |
| histogram | `r − t_out` (bin 0,1 ms, phạm vi ±2 s, phần ngoài dồn vào bin biên) để tính phân vị mà không lưu toàn bộ chuỗi |

### 3.2 Mỗi lần `push(r)` (k mẫu)

0. `k = 0` thì trả mảng rỗng. Giá trị không hữu hạn thì thay bằng dự đoán và cộng `invalid_samples`; nếu cả chunk không hữu hạn thì chạy theo `p`, coi `e = 0`.
1. **Chunk đầu tiên:** `t_last = median(r_j − (j+1)·p)` rồi phát `t_last + (j+1)·p`.
2. `pred_j = t_last + (j+1)·p`; `e = median(r_j − pred_j)`; `G = max(gap_s, gap_periods·p)`.
3. Chuyển trạng thái:
   - `normal`:
     - `e > G` → `pause_pending` (ghi lại `i_start`, `e_start`), `arrival_pauses += 1`, không sửa pha;
     - `e < −G` → `catching_up`, `catch_up_episodes += 1`, mở một khoảng uncertain;
     - còn lại → sửa pha `δ = clip(g·e, −s·k·p, +s·k·p)`.
   - `pause_pending`: cộng dồn số mẫu, không sửa pha.
     - `e < G/2` → `normal`, `pauses_caught_up += 1`;
     - đã nhận ≥ `C·fs_nominal` mẫu mà `e ≥ G/2` → nhảy **tiến** `t_last += e` (không bao giờ lùi), `forward_jumps += 1`, `pauses_unrecovered_after_C += 1`, khoảng `[i_start, n)` thành uncertain với lý do `pause_unrecovered_after_C`, rồi về `normal`.
   - `catching_up`: `p_c = p·(1 − s)` cho tới khi `|e| < G/2` → `normal` và đóng khoảng uncertain.
4. Phát `t_out_j = t_last + (j+1)·p_c`, với `p_c = p + δ/k` ở `normal`, `p` ở `pause_pending`, `p·(1−s)` ở `catching_up`. Rồi `t_last = t_out[−1]`, `n += k`.
5. Nếu tham số `uncertain` được truyền vào (từ `ClockBridge`) thì thêm khoảng của chunk này vào danh sách uncertain và không đưa vào `obs`.
6. **Cập nhật chu kỳ** (chỉ khi `normal`, và `obs` phủ ≥ `min_fit_s`):
   - `p̂` = độ dốc hồi quy `obs` (chỉ số → r) trong `fit_window_s`;
   - nếu `|p̂ − 1/fs_nominal| > period_tolerance·(1/fs_nominal)` → `period_rejected += 1`;
   - ngược lại `p = clip(p̂, p·(1 ± 200e-6))`, `period_updates += 1`.
   - Chu kỳ bị **giữ nguyên** khi đang ở `pause_pending` hoặc `catching_up`: các quan sát lúc đó lệch có hệ thống, sẽ làm hỏng ước lượng.

Bất biến theo cấu trúc:
- **tăng nghiêm ngặt:** `p_c > 0` (vì `s < 1`), các lần nhảy chỉ tiến, `t_out` bắt đầu sau `t_last`;
- **không sửa quá khứ:** mỗi lần `push` trả một mảng mới, không giữ tham chiếu ra ngoài.

### 3.3 `ClockBridge`

- `measure()`: đọc `m1 = mono()`, `u = unix()`, `m2 = mono()` trong `tries` lần; chọn lần có `m2 − m1` nhỏ nhất; `offset = (m1 + m2)/2 − u`. Nếu `|offset − offset_trước| > step_s` thì `steps += 1` và báo cho bên gọi để truyền `uncertain='clock_step'` vào `push` của chunk đó.
- Lịch sử `(thứ tự đo, u, offset)` trong `history_s` dùng cho marker.

### 3.4 Marker

`marker_offset(t_unix)` lấy lần đo **cuối cùng theo thứ tự** có `u ≤ t_unix`. Nếu trong lịch sử, từ lần đo đó tới hiện tại có một bước nhảy, trả `uncertain = True`. Test T8 chỉ kiểm cờ này, không kiểm offset được chọn (theo Codex vòng 4).

## 4. Bộ giả lập (`tests/timeline_sim.py`)

`simulate(seed, dur, fs_true, packet=12, latency=0.015, jitter=0.020, chunk=(1, 64), events=[...])` trả `true_t`, `ts_unix` (thời điểm host nhận), các ranh giới chunk, và đồng hồ giả `unix_clock`/`mono_clock` theo thời gian mô phỏng.

Tham số mặc định lấy từ số đo thật:
- gói 12 mẫu chung một timestamp (EEG 38 % Δts = 0);
- độ trễ 15 ms + U(0, 20 ms);
- `fs_true = 256,88` Hz.

Các sự kiện có thể chèn:
- `pause(t, d, delivered_later=bool, after=s)`: ngừng nhận `d` giây; dữ liệu có tới bù (dồn lại sau `after` giây) hoặc không;
- `clock_step(t, Δ, within_chunk=bool)`: giờ Unix nhảy, đồng hồ đơn điệu liên tục;
- `rate_change(t, fs)`;
- `stall(t, d)`: nghẽn rồi tới dồn dập.

## 5. Test (`tests/test_online_timeline.py`): chỉ bất biến, 20 seed

| # | Kịch bản | Điều kiện pass |
|---|---|---|
| T1 | 120 s sạch | tăng nghiêm ngặt; mọi khoảng cách ∈ `[p_c·(1−ε), …]` không có bước nhảy; 0 `arrival_pauses`; 0 lần nhảy |
| T2 | fs 256,88 → 256,70 | như T1; mỗi lần cập nhật `p` ≤ 200 ppm; `period_rejected = 0` |
| T3 | ngừng 2 s, không tới bù | `arrival_pauses = 1`, `pauses_unrecovered_after_C = 1`, `forward_jumps = 1` với độ lớn ≈ 2 s ± G; khoảng uncertain phủ `[i_start, i_start + C·fs]` |
| T3b | ngừng 2 s, dữ liệu tới bù **sau** C | như T3 cho tới lúc nhảy; khi dữ liệu tới bù thì `catching_up` (không lùi), thêm khoảng uncertain; **không** có bộ đếm nào mang nghĩa "mất mẫu" |
| T5 | nghẽn 0,5 s rồi tới bù | `arrival_pauses = 1`, `pauses_caught_up = 1`, 0 lần nhảy, 0 lần `catching_up` |
| T4a | giờ Unix nhảy ±2 s giữa hai chunk (qua `ClockBridge`) | `steps = 2`; 0 lần nhảy; 0 `arrival_pauses` |
| T4b | giờ Unix nhảy ±2 s trong một chunk (phần lệch là thiểu số và là đa số) | chunk đó uncertain (`clock_step`); 0 lần nhảy vĩnh viễn; trạng thái về `normal` |
| T6 | không sửa quá khứ | sao chép mọi mảng đã trả; sau khi chạy hết, so lại thì không mảng nào đổi |
| T8 | marker | không có bước nhảy: `offset` đúng lần đo cuối; có bước nhảy lùi giữa lúc bấm và lúc tra: `uncertain = True` |
| T9 | `report()` | bộ đếm và phân vị khớp tính tay trên chuỗi nhỏ đã biết |
| T12 | tất định | cùng seed và cùng cách chia chunk thì đầu ra giống từng bit |
| T13 | đầu vào xấu | chunk rỗng, chunk 1 mẫu, NaN/inf: không lỗi, vẫn tăng nghiêm ngặt, `invalid_samples` đúng |
| T14 | cấu hình | tham số ngoài miền hợp lệ (`slew ≥ 1`, `gain ≤ 0`, `fs ≤ 0`…) → `ValueError` |

Mọi kiểm tra "tăng nghiêm ngặt" và "khoảng cách giữa hai mẫu" đều chạy trên **toàn chuỗi** của cả 20 seed. Thời gian CI dự kiến dưới 10 s.

## 6. Báo cáo số đo (`tools/timeline_report.py`)

Đây là công cụ, không phải test. Nó chạy:
- 20 seed cho mỗi kịch bản T1–T5;
- quét tham số nhỏ `g ∈ {0,05; 0,1; 0,2}` × `s ∈ {5e-4; 1e-3; 2e-3}`;
- mọi bản ghi Athena trong `data/` nếu có. Mỗi bản ghi dùng `ts` gốc trong CSV với offset cố định. Ranh giới chunk lấy từ fixture của `tools/capture_athena.py` nếu có, nếu không thì dựng gần đúng theo chu kỳ đọc 20 ms của worker (ghi rõ đây là xấp xỉ).

In ra bảng markdown:
- p50/p95/p99 của `|t_out − (true_t + latency trung vị)|` (giả lập) và của `r − t_out` (dữ liệu thật);
- thời gian hội tụ chu kỳ;
- các bộ đếm;
- số lần sửa pha bị chặn ở giới hạn `s`.

Kết quả ghi vào `debate/claude-lsl-athena-stage2-report.md`, kèm đề xuất tham số và ngưỡng chống lùi chất lượng để Codex và người dùng duyệt.

## 7. Dữ liệu thật cần từ người dùng (chỉ nằm ở `data/`, không vào repo)

1. **10 phút ngồi yên, đeo tốt (4 kênh Good):** ghi bằng `tools/capture_athena.py MuseS-EDAA --seconds 600 --out data/athena_raw_10min.npz` (đóng app trước). Công cụ này giữ **ranh giới từng chunk** và `package_num`, chính xác hơn CSV của app cho việc đo timeline. Bắt buộc có `--out data/…`: mặc định công cụ lưu vào `tests/fixtures/`, thư mục **không** bị git bỏ qua, nên dữ liệu cá nhân có thể lọt vào commit.
2. **Khoảng 3 phút có gián đoạn BLE:** ghi bằng app, bấm Space với nhãn `away` khi mang máy ra xa và `back` khi quay lại, 2–3 lần, mỗi lần 10–20 s. Ranh giới chunk sẽ là xấp xỉ, nhưng nhãn cho biết lúc nào thật sự có nghẽn.

Thiếu dữ liệu thật thì CI vẫn chạy đủ. Báo cáo số đo khi đó chỉ có phần giả lập, và **không chốt tham số** cho tới khi có ít nhất bản ghi số 1.

## 8. Không làm ở chặng 2

- `pylsl`, outlet, class `Extension`, menu, panel;
- phát hook v3 trong cửa sổ xem lại;
- `lookahead`;
- dùng `package_num` để nhận biết mất gói (để dành cho khi quy tắc của nó được kiểm chứng; báo cáo có thể in kèm `package_num` quanh các lần ngừng nhận trong bản ghi số 1 để tham khảo).

## 9. Điều kiện sang chặng 3

1. T1–T14 pass trên 20 seed, trên cả CI Ubuntu/macOS × Python 3.10/3.12.
2. Báo cáo số đo có ít nhất bản ghi thật số 1, được Codex phản biện, và người dùng duyệt bộ tham số.
3. Không thay đổi nào ngoài các file liệt kê ở mục 10.

## 10. File

| File | |
|---|---|
| `src/musemonitor/core/online_timeline.py` | mới: `TimelineConfig`, `OnlineTimeline`, `ClockBridge` |
| `tests/timeline_sim.py` | mới: bộ giả lập |
| `tests/test_online_timeline.py` | mới: T1–T14 |
| `tools/timeline_report.py` | mới: báo cáo số đo |
| `debate/claude-lsl-athena-stage2-report.md` | mới, sau khi chạy |

Không sửa file nào đang có.

## Câu hỏi cho Codex

1. Đặt ở `core/online_timeline.py` (mục 1) có ổn không, hay vẫn muốn nằm trong extension (bằng thư mục `_lsl_outlet` tạm thời)?
2. Giữ nguyên chu kỳ khi không ở `normal` và loại các chunk uncertain khỏi `obs` (bước 3.2.6) có hợp lý không?
3. T3b: sau khi đã nhảy tiến, dữ liệu tới bù sẽ làm `e` âm lớn và rơi vào `catching_up`, tức timeline đi chậm 1 ms mỗi giây cho tới khi khớp, trong khi bù 2 s có thể mất tới khoảng 2000 s. Có nên cho phép một nhánh "nhảy lại" khác không? Không thể lùi, nên chỉ còn cách đi chậm hoặc chấp nhận lệch. Mình đề nghị chấp nhận đi chậm, đánh dấu uncertain cho tới khi khớp, và báo cáo tần suất trên dữ liệu thật trước khi bàn tiếp.
4. Histogram bin 0,1 ms trong ±2 s cho báo cáo phân vị có đủ không?
