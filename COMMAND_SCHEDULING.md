# Thuật toán gửi lệnh có cooldown và jitter

Mục tiêu là gửi với khoảng cách thay đổi nhưng luôn tôn trọng thời gian chờ.
Mỗi tài khoản có trạng thái riêng; mọi đường gửi tin nhắn và slash command đều
đi qua cùng bộ điều phối. Bộ điều phối giữ nguyên thứ tự ưu tiên hiện tại.

## Cách tính mốc được gửi

Với lệnh `c`, sau một lần gửi thành công tại thời điểm `s`:

```text
minimum[c] = max(cooldown nền, mức tối thiểu trong cấu hình)
padding[c] = 0.5 + random(0, min(10, minimum[c]))
command_ready[c] = s + minimum[c] + padding[c]

send_at = max(
    command_ready[c],
    lần gửi gần nhất + max(khoảng cách tin nhắn, slowmode kênh) + jitter,
    mốc chờ riêng của game,
    mốc chờ OwO yêu cầu,
    mốc kết thúc nghỉ ngắn
)
```

`jitter` giữa tin nhắn nằm trong 0,4–2 giây. Lệnh có mức tối thiểu 10 giây
được cấp mốc mới sau 10,5–20,5 giây; các điều kiện khác có thể làm nó gửi muộn
hơn. Khoảng lặp rộng hơn trong cấu hình vẫn được các tác vụ đang có áp dụng.
Thỉnh thoảng tài khoản im lặng 2–20 giây; gửi dồn 6–9 lệnh trong 45 giây cũng
kích hoạt nghỉ ngắn.

Mẫu ngẫu nhiên chỉ được lấy sau khi gửi thành công, không lấy lại mỗi lần
kiểm tra lịch. Tăng cooldown khi đang chờ sẽ kéo dài mốc; giảm cấu hình không
rút ngắn mốc đã cấp. Không gửi bù thành một đợt sau khi hết nghỉ.

## Quy tắc bảo toàn

- `h`, `hunt`, `catch` và bí danh cấu hình dùng chung mốc; `pray` và `curse`
  cũng dùng chung một nhóm. Thay tiền cược hoặc tham số không tạo mốc mới.
- Lệnh thường, slash command, lệnh tùy chỉnh và lệnh bán thủ công đều qua
  cùng kiểm tra. Mốc tính từ lúc gửi ra thành công, không tính từ lúc xếp hàng.
- Lệnh thất bại trước khi gửi không tiến lịch. Lệnh đang chờ gửi không bị
  bộ theo dõi xếp thêm bản sao.
- Kiểm tra Chạy/Dừng, CAPTCHA, lịch ngủ và công tắc lệnh trước khi gửi.
- Lịch bán thú định kỳ không được dùng làm cooldown cho từng lượt bán thủ công.
- Đồng hồ `time.monotonic()` giữ phép đo khoảng cách độc lập với việc chỉnh
  giờ hệ thống. Trạng thái thời gian hiện nằm trong bộ nhớ của lần chạy bot.

## Khi OwO yêu cầu chờ

Chỉ nhận thông báo từ đúng OwO, đúng kênh và đúng tài khoản hoặc tham chiếu
lệnh đã gửi. Thông báo có thời gian chờ rõ ràng sẽ kéo dài mốc thêm thời gian
đó cộng 0,5 giây đệm. Không rút ngắn thời gian dài mà server trả về.

`slow down` áp dụng cho toàn tài khoản. Nếu thông báo không nêu thời gian,
backoff tăng 2, 4, 8, 16, 32 rồi tối đa 60 giây. Phản hồi bình thường hợp lệ
đưa bộ đếm về 0. Thông báo không có tham chiếu mà có thể thuộc nhiều lệnh sẽ
áp dụng khoảng nghỉ chung để tránh gán nhầm lệnh.

Cùng một thông báo được Discord gửi lại qua raw event, native event hoặc edit
chỉ được xử lý một lần. Cơ chế này cập nhật lịch, không tự gửi lại thao tác
bán hoặc đặt cược. Bộ xử lý HTTP của thư viện Discord tiếp tục quản lý HTTP
429/`Retry-After`; không thêm một lớp retry HTTP khác.

## Mã và kiểm chứng

- `utils/command_timing.py`: nhận diện lệnh và mức tối thiểu từ cấu hình.
- `utils/command_pacing.py`: mốc monotonic, jitter, nghỉ ngắn và lùi lịch.
- `utils/cooldown_feedback.py`, `utils/response_guard.py`: phản hồi yêu cầu chờ
  và đối chiếu đúng yêu cầu gửi.
- `core/client.py`: kiểm tra tại ranh giới gửi ra Discord.

Kiểm thử dùng đồng hồ giả và mô phỏng gửi, không gửi lệnh Discord thật:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Thiết kế dùng jitter để phân tán thời điểm gọi và backoff khi cần giảm nhịp,
dựa trên [AWS Builders’ Library](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/).
Quy tắc ưu tiên thời gian server trả về phù hợp với
[tài liệu rate limit của Discord](https://github.com/discord/discord-api-docs/blob/main/developers/topics/rate-limits.mdx).
Đặc tính đồng hồ được mô tả trong
[tài liệu Python về monotonic](https://docs.python.org/3.12/library/time.html#time.monotonic).
