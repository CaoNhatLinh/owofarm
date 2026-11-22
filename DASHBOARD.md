# Điều khiển bot trên web

Mở http://127.0.0.1:1200/ để dùng ngay, không cần mật khẩu. Web chỉ cho phép truy cập cục bộ trên máy chạy bot. Vào Điều khiển → Tài khoản Discord để nhập, hiện/ẩn hoặc thay token và ID kênh. Thay tài khoản đang chạy cần khởi động lại bằng start.bat.

- **Chạy/Dừng bot** áp dụng ngay, giữ web và kết nối Discord để chạy lại.
  Lệnh đã gửi trước khi dừng vẫn có thể nhận kết quả.
- **Nghỉ khi mất phản hồi** có công tắc riêng. Mặc định: chờ tối đa 20 giây
  cho mỗi lệnh, 3 lần liên tiếp không nhận được phản hồi thì nghỉ 10 phút.
  Hết thời gian nghỉ, thử lệnh tiếp theo; nếu tiếp tục mất phản hồi thì nghỉ lại.
  Có thể chỉnh số lần, thời gian chờ và thời gian nghỉ trên web.
  Tắt công tắc sẽ huỷ lượt nghỉ hiện tại và xoá số lần mất phản hồi.
- Chỉ đếm lệnh cần OwO trả lời. Tin nhắn chữ `owo` và chat thông thường
  không tính vào ngưỡng. Phản hồi phải thuộc đúng tài khoản và kênh gửi lệnh.
  Bot chờ kết quả trước khi gửi lệnh tiếp theo để không gửi dồn khi OwO im lặng.
- **Khoảng cách tin nhắn**: thanh kéo 3–60 giây, bước 0,5 giây; đây là khoảng
  tối thiểu. Cooldown riêng của lệnh, slowmode kênh và lịch nghỉ vẫn có hiệu lực.
- **Gửi chữ owo** chỉ điều khiển tin nhắn `owo` riêng lẻ, không tắt hunt/battle.
- **Thứ tự dùng gem**: cao xuống thấp hoặc thấp lên cao theo độ hiếm,
  chọn riêng cho từng loại gem còn thiếu. Bỏ qua gem hết số lượng hoặc độ hiếm
  bị tắt. Áp dụng ở lần dùng gem tiếp theo, không thay gem đang có hiệu lực.
- **ID kênh Discord** được lưu dưới dạng chuỗi để giữ chính xác ID dài.
  Kiểm tra quyền xem/gửi trước khi lưu; kênh không truy cập được sẽ bị từ chối.
  Bỏ trống để dùng kênh ban đầu trong cấu hình tài khoản.
- **Prefix** giữ nguyên mọi dấu cách, kể cả ở đầu/cuối. Ví dụ `o` tạo `oh`,
  `owo ` tạo `owo h`. Chỉ đổi cấu hình của ứng dụng; prefix phải khớp OwO
  trong server. Không tự gửi lệnh thay đổi prefix server.

Bấm **Lưu thay đổi** để áp dụng thiết lập. Cấu hình được lưu nguyên tử vào
`config/dashboard.json`, giữ lại sau khi khởi động lại. Kênh/prefix được áp dụng
trên vòng lặp bot; một lệnh đang gửi có thể kết thúc trước khi chuyển cấu hình.
Các trường trên web ưu tiên hơn cấu hình prefix trong `config/settings.json`.

## Bán nhanh

Ba nút **Bán vũ khí ngay**, **Bán thú ngay**, **Hiến tế thú ngay** có ngưỡng độ hiếm độc lập,
mặc định Uncommon trở xuống. Danh sách “Sẽ bán” hiển thị đúng các cấp được
chọn. Đổi lựa chọn không gửi lệnh; chỉ gửi khi bấm nút bán tương ứng.

- Vũ khí: gửi trực tiếp các lệnh bán theo cấp `sell cw`, `sell uw`, `sell rw`,
  v.v. đến ngưỡng đã chọn; không đọc danh sách hoặc bán từng ID.
  OwO giữ đồ đang trang bị, đồ yêu thích và đồ không được phép bán.
  Mỗi cấp chỉ gửi một lệnh theo giới hạn lượt bán của OwO, không tự lặp lại.
  Tuỳ chọn thủ công có thể bán Rare trở lên nếu chọn ngưỡng đó;
  không thay quy tắc tự bán định kỳ.
- Thú: gửi đúng danh sách mã độ hiếm đến ngưỡng đã chọn. Không dùng `sell all`.
  Việc bán không lấy pet ra khỏi team battle, theo cơ chế của OwO.
- Hiến tế: gửi `sac` với đúng danh sách mã độ hiếm như bán thú, nhận essence
  thay vì cowoncy; không tự động bật HuntBot hoặc thay đổi lịch hiến tế tự động.
- Mỗi tài khoản chỉ có một lượt bán đang xử lý. Cùng mã yêu cầu không được
  gửi lại thành lượt bán mới, kể cả khi kết nối web bị gián đoạn.
- Có thể bán/hiến tế thủ công ngay cả khi farm đang dừng, không bật lại farm.
  Lệnh thủ công vẫn giữ khoảng cách gửi và chờ phản hồi, không chạy qua hàng
  đợi farm đang dừng. Dừng khi gặp CAPTCHA, nghỉ theo lịch, đổi kênh/prefix
  hoặc thiếu xác nhận.
  Không tự gửi lại lệnh bán khi không nhận được phản hồi. Nếu kết quả chưa rõ,
  kiểm tra kho/zoo và nhật ký trước khi chủ động bán thêm.
- Kết quả/progress hiện ngay dưới ba nút, đồng thời được ghi trong nhật ký.
  Lượt bán thủ công không tự tiếp tục sau khi khởi động lại ứng dụng.

Bấm **Chạy** sau khi dừng sẽ xoá trạng thái chờ CAPTCHA/phản hồi cũ.
Khi đang chờ CAPTCHA còn có nút **Đã xác minh · Tiếp tục**; chỉ dùng sau khi
đã tự xác minh. Thao tác này huỷ bộ đếm dừng của lần CAPTCHA trước, không ghi
nhận giả một lượt giải CAPTCHA. Lịch nghỉ vẫn giữ nguyên; CAPTCHA mới vẫn
làm bot dừng lại. Hết thời gian nghỉ tự động không tự xoá CAPTCHA.

## Thống kê thú hiếm

Mục “Thú hiếm đã bắt” đếm riêng từng loài Legendary, Gem, Distorted, Fabled và Hidden trên các tài khoản. Cập nhật mỗi 3 giây, chỉ tính kết quả hunt quan sát được từ lúc cài tính năng, không nhập lại zoo trước đây. Số đếm không giảm khi bán/hiến tế và được lưu qua lần khởi động lại trong `utils/data/rare_catches.sqlite`. Tin nhắn trùng hoặc bản chỉnh sửa được gộp theo tài khoản, ID tin nhắn và loài; dòng nhận XP của team không được tính.

## Tự chơi gamble

Ba công tắc Coinflip, Slots và Blackjack nằm trong phần điều khiển. Chọn trạng thái rồi bấm Lưu thay đổi. Cấu hình lưu trong dashboard.json, áp dụng trong khoảng một giây và giữ qua khởi động lại. Mặc định cả ba tắt. Khi tắt, các lệnh chờ và tác vụ khởi động của trò tương ứng được dọn; lệnh đã gửi tới OwO có thể tiếp tục trả kết quả. Nút Dừng bot và cơ chế CAPTCHA/nghỉ vẫn áp dụng. Tiền cược ban đầu và nhân đôi khi thua được chỉnh riêng từng trò trên web, lưu trong dashboard.json. Mặc định 200 và bật nhân đôi để khớp cấu hình cũ. Giới hạn ngân sách/mục tiêu vẫn theo settings.json. Đổi tiền cược hoặc chế độ nhân đôi sẽ reset chuỗi thua về 0 và dùng mức mới từ lệnh cược kế tiếp, kể cả lệnh đã xếp hàng nhưng chưa gửi.

## Điều hướng dashboard

Giao diện gồm sáu tab: Tổng quan (trạng thái và số liệu), Điều khiển (nhịp gửi/nghỉ/gem/kênh/prefix), Gamble (chọn từng trò và chỉnh cược), Kho đồ (bán và hiến tế), Thú đã bắt (bộ đếm từng loài), Nhật ký (tìm/lọc hoạt động). Chỉ một tab chính hiển thị tại một thời điểm. Thanh chạy/dừng ở đầu trang; thanh lưu/hoàn tác cố định khi chỉnh thiết lập hoặc có thay đổi chưa lưu. Chuyển tab giữ nguyên bản nháp, dấu chấm chỉ tab có chỉnh sửa. Lưu áp dụng tất cả chỉnh sửa; Hoàn tác trả về cấu hình đã lưu. Nhập sai ở tab khác sẽ tự mở đúng tab và ô cần sửa. Các link cũ #gambling-controls, #rare-catches, #quick-sales được chuyển tới tab tương ứng.

### Khoảng chờ gamble

Mỗi tài khoản có chốt tối thiểu 10 giây cho từng trò, tính từ lần gửi cược và từ kết quả ván gần nhất. Cả lệnh bình thường và thử lại đều đi qua chốt này. Khi nhận kết quả, lệnh chờ/check thử lại cũ được dọn ngay trước khi nghỉ lượt sau; kết quả trùng ID không cập nhật tiền hoặc chuỗi thua lần nữa. Blackjack trả kết quả ngay trong tin nhắn mới cũng được xử lý. Lệnh cược không dùng misspell để tránh một lần sửa chữ trở thành cược lặp. Cooldown riêng hiện có vẫn áp dụng.

### Mục tiêu lợi nhuận gamble

Tab Gamble có công tắc dừng khi đạt mục tiêu và ô số cowoncy muốn kiếm được. Mặc định giữ 30.000 cowoncy và bật giới hạn. Mục tiêu dùng lãi gamble trong phiên, cộng chung Coinflip/Slots/Blackjack trên từng tài khoản; không dùng số dư hoặc tiền hunt/battle. Đạt đúng mục tiêu là dừng cược mới. Tăng mục tiêu hoặc tắt giới hạn giải phóng trạng thái chờ mà không cần khởi động lại; khoảng chờ cược và giới hạn vốn vẫn áp dụng. Phiên được tính lại khi khởi động ứng dụng. Blackjack tính tiền trả thưởng trừ tiền cược để tránh tính vốn hoàn lại thành lãi.

### Giới hạn lỗ gamble

Trong tab Gamble, công tắc Giới hạn lỗ và ô số cowoncy thua tối đa thay thế giới hạn vốn ẩn cũ. Mặc định bật, 10.000 cowoncy. Dùng lỗ ròng trong phiên, cộng chung cả ba trò trên mỗi tài khoản. Đạt mức lỗ thì chặn mọi cược mới và giữ trạng thái dừng cho đến khi người dùng đổi giới hạn hoặc tắt công tắc. Lệnh chờ/thử lại cũng được kiểm tra ngay trước khi gửi; lượt cược vượt phần vốn lỗ còn lại bị chặn trước. Ván đã gửi vẫn có thể trả kết quả, nên không hoàn tác hoặc đảm bảo trần cho các ván đã mở đồng thời. Hunt/battle và các chức năng ngoài gamble tiếp tục bình thường.

### Reset phiên và chuỗi thua

Nút Reset lãi/lỗ & chơi lại trong Gamble đưa lãi/lỗ phiên về 0, gỡ chặn mục tiêu/giới hạn lỗ và reset chuỗi tăng cược về mức ban đầu. Không đổi cấu hình, số dư thực, trạng thái chạy/dừng farm, CAPTCHA hoặc cooldown. Ván đang mở được tính vào phiên mới khi kết thúc. Nếu có nhiều tài khoản, chọn đúng tài khoản trước khi reset. Yêu cầu có mã idempotency để tránh reset hai lần khi lỗi mạng.

Thống kê Coinflip/Slots/Blackjack hiển thị chuỗi thua hiện tại và kỷ lục từng trò. Thắng reset chuỗi hiện tại, hoà không thay đổi chuỗi. Reset phiên chỉ xóa chuỗi hiện tại; kỷ lục lưu trong utils/data/gamble_streaks.sqlite và giữ qua khởi động lại. Chỉ ghi nhận kết quả từ khi tính năng được cài, không suy ngược các ván cũ.

### Bảng tính vốn và trí nhớ chuỗi thua

Mục Vốn cho chuỗi thua dùng tiền cược ban đầu/chế độ nhân đôi của trò đang chọn và kỷ lục của tài khoản. Có thể nhập số lần thua để mô phỏng, hoặc bấm Dùng chuỗi dài nhất. Với mức đầu b và N lần thua: tổng mất b*(2^N-1), cược tiếp b*2^N, vốn để còn cược tiếp b*(2^(N+1)-1). Tắt nhân đôi: tổng mất b*N, cược tiếp b. Bảng ghi riêng số tiền từng lượt, tổng đã mất và cảnh báo trần cược/giới hạn lỗ. Công thức dùng BigInt để giữ số tiền nguyên chính xác. Đây là phép tính cho một chuỗi thua mới, không phải dự đoán kết quả.

File utils/data/gamble_streaks.sqlite hiện lưu cả current và best của từng tài khoản/từng trò sau mỗi kết quả, tự khôi phục khi mở lại ứng dụng. File cũ chỉ có best được nâng cấp và giữ nguyên kỷ lục. Reset phiên ghi current=0 vào file và giữ best. Lưu file không có nghĩa tự khôi phục mức cược tăng dần cũ sau khởi động.

### Tính mức cược ban đầu theo vốn

Ô Vốn bạn có trong Vốn cho chuỗi thua lưu giá trị tính toán ở trình duyệt. Tự tính mức đầu tối đa để đủ N lần thua và lượt tiếp theo, theo chế độ nhân đôi/cố định của trò được chọn; mặc định N là kỷ lục. Tôn trọng cả giới hạn lỗ đang bật và trần 250.000 của lượt tiếp. Nút Điền mức cược đề xuất chỉ điền bản nháp; cần Lưu thay đổi mới cập nhật bot. Với gấp đôi: b <= floor(vốn/(2^(N+1)-1)); đồng thời b*2^N <= 250000. Tắt gấp đôi: b <= floor(vốn/(N+1)). Đây là vốn cho một trò và một chuỗi mới, không gồm các cược khác đang mở.

### Chọn mặt Coinflip

Tab Gamble → Coinflip có lựa chọn Heads hoặc Tails, mặc định Heads như cấu hình cũ. Lưu để áp dụng cho lượt chưa gửi, kể cả lệnh chờ/thử lại. Ván đã mở giữ mặt cũ. Đổi mặt không reset chuỗi tăng cược hoặc kỷ lục. Bảng vốn hiển thị mặt đang chọn; công thức vốn cho N lần thua và lượt tiếp theo giống nhau với hai mặt, không dự đoán thắng/thua.

### Tự chọn mặt theo lịch sử

Chọn Tự chọn theo lịch sử rồi lưu. Dùng tối đa 500 ván gần nhất có đọc được mặt đã chọn trong kết quả OwO. Khi mỗi mặt chưa đủ 5 ván, ưu tiên mặt ít mẫu; sau đó ưu tiên tỷ lệ thắng làm trơn (wins+1)/(samples+2), bằng nhau ưu tiên mặt ít mẫu rồi Heads. Chốt lại mặt ngay trước lúc gửi để lệnh chờ cũng dùng lịch sử mới. Không thay tiền cược, chuỗi tăng cược, cooldown hoặc giới hạn lỗ.

Lịch sử ghi cả ván chọn mặt cố định và tự chọn, lưu riêng từng tài khoản trong utils/data/coinflip_history.sqlite, chống ghi trùng ID kết quả và chỉ giữ 500 ván. Đọc mặt từ kết quả thực tế, không dùng cấu hình hiện tại nên đổi lựa chọn giữa ván không làm sai dữ liệu. Không suy ngược từ bộ đếm thắng/thua cũ; bắt đầu ghi từ bản cập nhật này. Reset phiên giữ lịch sử mặt. Đây là quy tắc chọn theo thống kê mô tả, không dự đoán hay bảo đảm tăng cơ hội thắng.

Khi tự chọn, nếu ván gần nhất thua thì giữ mặt thực tế của ván đó cho đến khi thắng; chỉ đánh giá lại ở đầu chuỗi sau thắng. Khóa mặt khôi phục từ kết quả đã lưu khi mở lại ứng dụng. Đổi về Heads/Tails cố định là ghi đè thủ công. Reset lãi/lỗ không xóa lịch sử hoặc khóa mặt. Không có tăng cược đặc biệt ở kỷ lục+1: vẫn dùng tiền cược/nhân đôi/giới hạn đã đặt. Kỷ lục lịch sử không giới hạn chuỗi thua tương lai.

### Tần suất xuất hiện Heads/Tails

Bảng Mặt đồng xu xuất hiện luôn hiện trong Coinflip, kể cả chọn mặt thủ công: số lần, phần trăm và mặt nhiều hơn trong tối đa 500 kết quả gần nhất. Thắng nghĩa mặt xuất hiện trùng mặt chọn; thua nghĩa mặt đối diện. Đây là tần suất kết quả đồng xu, không phải tỷ lệ thắng của các cược vào mặt đó. Không có dữ liệu thì không hiển thị tỷ lệ giả. Chọn Heads/Tails ở ô bên dưới và lưu để áp dụng.

Bảng tần suất có hai biểu đồ riêng 100 và 500 ván gần nhất, hiển thị số mẫu thực tế trên từng giới hạn. Biểu đồ 100 tính từ 100 ván mới nhất trong cùng lịch sử tối đa 500 ván; khi đủ mẫu thì tự trượt. Không lấy mẫu ngẫu nhiên. Chế độ tự chọn dùng mẫu 100 hoặc 500 ván theo ô Mẫu lịch sử tự chọn (mặc định 500), giữ quy tắc khóa mặt trong chuỗi thua. Lưu để áp dụng; đổi mẫu không reset tiền cược hoặc đổi mặt đang khóa.

### Mô phỏng Coinflip trước khi áp dụng

Tab Mô phỏng đọc tối đa 500 kết quả đã lưu của tài khoản đang kết nối, so sánh 12 tổ hợp: Heads, Tails, auto100, auto500 × cược cố định hoặc nhân đôi khi thua. Nhập vốn giả lập, cược đầu, phần lấy mẫu ban đầu (0/20/50/80%), mục tiêu và giới hạn lỗ. Dùng cùng chuỗi mặt đồng xu thực tế cho mọi tổ hợp. Phần đầu không tính lãi, phần sau kiểm tra theo thứ tự; mỗi lượt chọn mặt trước khi biết kết quả, dùng cùng History._selection như bot thật. Auto giữ mặt qua chuỗi thua. Mỗi tổ hợp cập nhật lịch sử lựa chọn/thắng thua giả lập riêng.

Mô phỏng dừng khi vượt vốn, trần cược 250.000, giới hạn lỗ hoặc đạt mục tiêu. Bảng ghi lãi/lỗ, sụt vốn từ đỉnh, số ván đã chơi/thắng/thua, cược lớn nhất, chuỗi thua và lý do dừng; đồ thị kết thúc khi tổ hợp dừng. Không mô phỏng thời gian, hunt hoặc game khác. Xếp theo lãi trên tập này không chứng minh lợi thế tương lai; việc chọn tổ hợp sau khi xem bảng cũng có thể khớp may mắn.

API POST /api/gamble/simulate chỉ nhận truy cập cục bộ, chỉ đọc lịch sử của tài khoản kết nối và tính toán, không gửi lệnh hay sửa cấu hình. Xem cấu hình chỉ hiện bản xem trước; Điền vào bản nháp sao chép tiền cược, nhân đôi, mặt/mẫu, mục tiêu và giới hạn lỗ chung vào Gamble. Không bật game. Người dùng cần Lưu thay đổi mới áp dụng. Đổi thông số giả lập làm mất hiệu lực kết quả cũ.

### Hai mẹo cộng đồng trong mô phỏng và cược thật

Bảng thêm 2 tổ hợp cược thử 1 + chọn/đảo ngẫu nhiên (cố định/gấp đôi), và 2 tổ hợp Generator theo bậc vốn (Heads/Tails, gấp đôi), thành 12 tổ hợp. Cược thử: mỗi lượt chính có một cược thử 1 vào Heads; sau khi biết kết quả thử, chọn ngẫu nhiên h/t, thử thắng thì đảo lựa chọn ngẫu nhiên, thử thua thì giữ. Sau lượt chính lại bắt đầu cược thử. Thử được tính vào lãi/lỗ và thống kê, nhưng không tăng/reset bậc tiền cược chính. Mô phỏng seed42 lặp lại được; cược thật dùng secrets.choice mới, tương đương lựa chọn của ochoose, không gửi thêm ochoose. Chốt thông tin lượt đã gửi để đổi UI giữa ván không làm nhầm phí thử thành cược chính. Cooldown, CAPTCHA, nghỉ và các giới hạn vẫn áp dụng. Khởi động lại đặt trạng thái về thử mới. Chọn mode probe ở ô Mặt Coinflip để áp dụng trực tiếp sau khi lưu.

Generator sao chép detectTier(balance) và base=100*2^tier từ mingo-raven/owo-strategy-generator; không dùng phần trăm 65–75 tạo ngẫu nhiên. Bậc vốn lớn có thể cho cược đầu vượt 250.000: kết quả mô phỏng báo trần, không được điền áp dụng. Bậc hợp lệ được áp dụng như preset tiền cược đầu + nhân đôi + mặt Heads/Tails; không tự đổi bậc theo số dư trong lúc chạy. Mọi cách đều có thể lỗ; không có xác nhận thắng80%.

### Cược thử 1 đến khi thua

Chọn Mặt Coinflip = Cược thử 1 đến khi thua, rồi chọn mặt cược chính (coinflipProbeTarget: heads/tails). Ví dụ mặt chính Heads: thử Heads 1 liên tục; thử thắng vẫn Heads 1, thử thua chuyển sang cược chính Heads ở mức đã đặt. Sau mỗi lượt chính, quay về thử Heads 1. Chỉ kết quả lượt chính tăng/reset bậc gấp đôi; mọi lượt thử vẫn cập nhật tiền và thống kê. Đổi mặt chính hoặc chế độ reset vòng thử; phiên bản kế hoạch chặn kết quả cũ làm chuyển pha kế hoạch mới. Restart bắt đầu thử lại. Không tự chọn mặt theo tần suất và không có bảo đảm tỷ lệ thắng.

Mô phỏng thêm hai hướng Heads/Tails × cố định/gấp đôi, tổng 16 tổ hợp, dùng cùng ProbePlan với bot thật. Tính cả mọi lượt thử thắng và thua. Bảng vốn hình học trong Gamble vẫn chỉ tính các cược chính; giao diện nhắc dùng Mô phỏng để gồm cả tiền thử. Các bảo vệ giới hạn lỗ, vốn, trần cược, cooldown và CAPTCHA vẫn áp dụng.

### Thắng đổi mặt, thua giữ mặt

Chọn coinflipSide=win_switch và coinflipSwitchStart=heads/tails trên web. Mỗi lượt là cược chính, không có thử 1: Heads thắng đổi Tails, Heads thua giữ Heads; Tails thắng đổi Heads, Tails thua giữ Tails. Thắng đưa mức cược về cơ bản, thua gấp đôi nếu bật công tắc. Đổi mặt khởi đầu/đổi chế độ reset mặt; pause/resume giữ mặt trong tiến trình, khởi động lại bắt đầu từ mặt đã cấu hình. Kế hoạch có phiên bản để kết quả đã gửi trước khi đổi cấu hình không làm đổi mặt mới.

Mô phỏng thêm switchHeads/switchTails × cố định/gấp đôi, tổng 20 tổ hợp; cùng quy tắc trạng thái với bot thật, không có tiền cược thử. Nút điền cấu hình sao chép đúng mode và mặt khởi đầu vào bản nháp, cần Lưu thay đổi.

Đã sửa chế độ Cược thử 1 đến khi thua theo mô tả mới: cược thử và cược chính cùng mặt. Chọn Heads thì thử Heads 1; chọn Tails thì thử Tails 1. Bản mô phỏng cũ cần chạy lại để có kết quả đúng quy tắc mới.

### Bật/tắt hunt và battle riêng

Tab Điều khiển có hai công tắc huntEnabled và battleEnabled (mặc định bật, như cấu hình hiện có). Lưu để áp dụng, giữ qua khởi động lại. Nhãn lệnh theo prefix đang nhập, mặc định oh/ob. Tắt dọn queue/check thử lại và chặn ở hàng đợi, trước khi gửi tin nhắn và trước lệnh slash. Kết quả của lệnh đã gửi vẫn được xử lý. Bật lại tạo lịch cho đúng lệnh, giữ cơ chế Dừng/CAPTCHA/nghỉ và khoảng chờ hiện tại. Không điều khiển HuntBot. Hai công tắc áp dụng chung tài khoản trên dashboard.
