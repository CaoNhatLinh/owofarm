# Owofarm

Bản tuỳ chỉnh dựa trên [owo-dusk/owo-dusk](https://github.com/owo-dusk/owo-dusk), có bảng điều khiển web tiếng Việt, các tab cấu hình, thống kê và mô phỏng.

## Chạy trên Windows

1. Cài **Python 3.12 hoặc 3.13 bản 64-bit** và **Git for Windows**.
2. Tải ZIP của repository, giải nén rồi bấm đúp `install.bat` một lần để cài thư viện.
3. Bấm đúp `start.bat` để mở bot và web.
4. Mở http://127.0.0.1:1200, vào **Điều khiển → Tài khoản Discord**.
5. Nhập token và ID kênh, bấm **Lưu tài khoản**. Web không yêu cầu mật khẩu; chỉ mở trên máy đang chạy bot.

Đọc [hướng dẫn Windows chi tiết](HUONG_DAN_WINDOWS.md). Không cần cài Node.js, Docker hay máy chủ cơ sở dữ liệu. Internet cần thiết khi cài thư viện và kết nối Discord.

`install.bat` chỉ cài trong thư mục hiện tại, không tải đè mã nguồn từ repository khác và không khởi chạy tài khoản. Cấu hình được tạo từ `config/examples` khi chưa tồn tại. Cài lại giữ nguyên token và cấu hình đang có. Muốn đổi máy, cài lại thư viện thay vì sao chép `.venv`.

## Tài liệu

- [Bảng điều khiển](DASHBOARD.md)
- [Trang bị vũ khí](AUTO_WEAPONS.md)
- Cấu hình riêng, token, SQLite và lịch sử phiên được bỏ qua bằng `.gitignore`.

## Nguồn gốc và giấy phép

Dựa trên OwO-Dusk của EchoQuill và các tác giả đóng góp. Mã nguồn được phân phối theo **GPL-3.0 hoặc mới hơn**; xem [LICENSE](LICENSE) và thông báo bản quyền trong từng file. Việc tạo lịch sử Git mới không thay đổi tác giả hay giấy phép của mã nguồn gốc.

Ghi nhận từ dự án gốc: [autocord-org/dmg](https://github.com/autocord-org/dmg) về cấu trúc cogs; [scriptlabs-cc/slashy](https://github.com/scriptlabs-cc/slashy) về bảng điều khiển web.
