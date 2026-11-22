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
4. Vào **Điều khiển → Tài khoản Discord**, nhập token và ID kênh, bấm **Lưu tài khoản**. Khi chưa có tài khoản, bot tự kết nối sau khi lưu. Có nút **Hiện token / Ẩn token**, cho phép xem lại và sửa token đã lưu.
5. Nếu giữ nguyên token và chỉ đổi ID kênh khi đã kết nối, Lưu tài khoản sẽ kiểm tra quyền rồi chuyển kênh ngay. Nếu thay token khi bot đang kết nối tài khoản cũ, lưu xong hãy nhấn Ctrl+C trong CMD rồi chạy `start.bat` lại. Lưu không tự ngắt ván đang chơi.
6. Kiểm tra prefix ở tab Điều khiển cho đúng server: `o` gửi `oh`; `owo ` có dấu cách cuối gửi `owo h`. ID kênh cho tài khoản được dùng khi kết nối; ô đổi kênh của bot dùng để chuyển kênh trong lúc chạy.

Token chỉ lưu ở `tokens.txt` trên máy, không gửi vào chat hay GitHub. Bạn cũng có thể sửa file trực tiếp theo dạng `TOKEN ID_KENH`, mỗi tài khoản một dòng. Form web hỗ trợ một tài khoản; nếu file có nhiều tài khoản thì sửa file trực tiếp để giữ đủ các tài khoản.

Web luôn chỉ lắng nghe 127.0.0.1, kể cả cấu hình cũ có bật enableHost. Các trường mật khẩu web cũ không còn được dùng.

Lần đầu mặc định tắt ba trò cá cược, tự bán và tự trang bị vũ khí. Kiểm tra các công tắc trước khi bật. Cấu hình cũ có sẵn sẽ giữ lựa chọn trước đó.

## Những lần sau

Bấm đúp `start.bat`. Hoặc mở CMD và gõ (thay đường dẫn cho đúng máy):

```bat
cd /d "D:\Workspace\Source Code\owofarm"
start.bat
```

Nút Dừng trên web tạm dừng tự động; **Ctrl+C trong cửa sổ CMD** đóng tiến trình và web. Không mở nhiều cửa sổ bot cùng lúc vì web dùng cổng 1200. Máy cần bật và tiến trình cần chạy để tự động thực hiện tác vụ.

## Nếu gặp lỗi

- **Không tìm thấy Python/Git:** cài chúng, đóng CMD rồi mở lại.
- **.venv không dùng được sau đổi máy/nâng cấp Python:** dừng bot, đổi tên thư mục `.venv` thành `.venv-old`, chạy `install.bat` lại. Không cần xoá token hoặc cấu hình.
- **Không cài được thư viện:** xem lỗi ngay phía trên trong CMD, kiểm tra Internet, Git và phiên bản Python; chạy lại `install.bat`.
- **Web không mở:** kiểm tra cửa sổ CMD còn chạy và không báo lỗi cổng đang dùng.
- **Đăng nhập thất bại:** sửa token ở Điều khiển → Tài khoản Discord hoặc kiểm tra `tokens.txt`; không đăng thông tin đó lên GitHub để nhờ sửa.
- **Bật image solver riêng:** thư viện ONNX là tuỳ chọn, không được cài trong bộ Windows mặc định. Cấu hình mẫu để chức năng này tắt.

## Đẩy mã nguồn lên GitHub

Repository mới trỏ tới `https://github.com/CaoNhatLinh/owofarm.git`. Sau khi có commit ban đầu và đăng nhập GitHub trên máy:

```bat
git push -u origin main
```

Không thêm `--force` nếu repository trên GitHub đã có lịch sử riêng. Token, cấu hình thật trong `config/`, `.venv`, cơ sở dữ liệu và lịch sử phiên không được đẩy lên; mẫu công khai nằm ở `config/examples/`. Cần giữ LICENSE và thông báo tác giả gốc khi chia sẻ.
