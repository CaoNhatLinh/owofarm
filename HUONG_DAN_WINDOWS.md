# Cài và chạy bằng CMD trên Windows

## Cần có

- Windows 10/11, máy 64-bit, Internet và trình duyệt web.
- [Python 3.12 hoặc 3.13 bản 64-bit](https://www.python.org/downloads/windows/). Khi cài chọn **Add Python to PATH**.
- [Git for Windows](https://git-scm.com/download/win). Git còn cần để pip tải thư viện discord.py-self được ghim theo commit, ngay cả khi bạn tải dự án bằng ZIP.
- Thông tin tài khoản của bạn và ID kênh mà tài khoản truy cập/gửi tin được.

Không cần Node.js, Docker, Visual Studio Code hay cài MySQL. Dữ liệu dùng SQLite có sẵn trong Python. Cài đặt thông thường không cần mở CMD bằng quyền Administrator.

## Lần đầu

1. Tải ZIP từ https://github.com/CaoNhatLinh/owofarm rồi giải nén. Không chạy trực tiếp trong file ZIP.
2. Trong thư mục vừa giải nén, bấm đúp **install.bat**. Đợi thông báo Installed. Trình cài tạo `.venv`, cài thư viện, sao chép cấu hình mẫu còn thiếu; không tự chạy bot.
3. Bấm đúp **start.bat**. Giữ cửa sổ CMD mở, vào http://127.0.0.1:1200. Không cần mật khẩu web.
4. Vào **Tài khoản Discord → Thêm tài khoản**, nhập token và ID kênh. Khi thêm tài khoản đầu tiên, bot tự kết nối sau khi lưu. Thêm tài khoản tiếp theo hoặc thay token thì khởi động lại `start.bat`.
5. Chọn tài khoản ở đầu trang rồi vào **Tự động hóa** để chỉnh ID kênh, lệnh tự động và tiền tố riêng. `o` gửi `oh`, còn `owo ` có dấu cách cuối gửi `owo h`.
6. Trong **Tài khoản Discord**, chọn **Đổi token** để cập nhật tài khoản. Nút **Xem token đang lưu** chỉ hiện token của tài khoản đang chỉnh.

Token chỉ lưu ở `tokens.txt` trên máy. Bạn cũng có thể sửa file trực tiếp theo dạng `TOKEN ID_KENH`, mỗi tài khoản một dòng.

Web luôn chỉ lắng nghe 127.0.0.1, kể cả cấu hình cũ có bật enableHost. Các trường mật khẩu web cũ không còn được dùng.

Lần đầu mặc định tắt ba trò cá cược, tự bán và tự trang bị vũ khí. Kiểm tra các công tắc trước khi bật. Cấu hình cũ có sẵn sẽ giữ lựa chọn trước đó.

## Những lần sau

Bấm đúp `start.bat`. Hoặc mở CMD và gõ (thay đường dẫn cho đúng máy):

```bat
cd /d "D:\Workspace\Source Code\owofarm"
start.bat
```

Nút **Dừng tài khoản** tạm dừng tài khoản đang xem, còn **Dừng tất cả** tạm dừng mọi tài khoản. **Ctrl+C trong cửa sổ CMD** đóng bot và bảng điều khiển. Chạy một cửa sổ `start.bat` cho mọi tài khoản dùng cùng bảng điều khiển.

## Nếu gặp lỗi

- **Không tìm thấy Python/Git:** cài chúng, đóng CMD rồi mở lại.
- **.venv không dùng được sau đổi máy/nâng cấp Python:** dừng bot, đổi tên thư mục `.venv` thành `.venv-old`, chạy `install.bat` lại. Không cần xoá token hoặc cấu hình.
- **Không cài được thư viện:** xem lỗi ngay phía trên trong CMD, kiểm tra Internet, Git và phiên bản Python; chạy lại `install.bat`.
- **Web không mở:** kiểm tra cửa sổ CMD còn chạy và không báo lỗi cổng đang dùng.
- **Đăng nhập thất bại:** vào **Tài khoản Discord → Đổi token** hoặc kiểm tra `tokens.txt` trên máy.
- **Bật image solver riêng:** thư viện ONNX là tuỳ chọn, không được cài trong bộ Windows mặc định. Cấu hình mẫu để chức năng này tắt.

## Đẩy mã nguồn lên GitHub

Repository mới trỏ tới `https://github.com/CaoNhatLinh/owofarm.git`. Sau khi có commit ban đầu và đăng nhập GitHub trên máy:

```bat
git push -u origin main
```

Không thêm `--force` nếu repository trên GitHub đã có lịch sử riêng. Token, cấu hình thật trong `config/`, `.venv`, cơ sở dữ liệu và lịch sử phiên không được đẩy lên; mẫu công khai nằm ở `config/examples/`. Cần giữ LICENSE và thông báo tác giả gốc khi chia sẻ.
