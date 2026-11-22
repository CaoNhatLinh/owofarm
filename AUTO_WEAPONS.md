# Tự tạo team và quản lý vũ khí

Cấu hình nằm trong `config/settings.json`, mục `autoWeapons`.

- `bootstrapFirstPet: true`: nếu OwO xác nhận chưa có team hoặc cả ba ô đều trống,
  đọc zoo và thêm đúng pet đầu tiên còn số lượng vào ô 1. Team đã có pet được giữ nguyên.
  Zoo trống thì đợi lần kiểm tra sau. Không tự thêm đủ ba pet.
- `strategy: "roles"`: chọn tổ hợp vũ khí theo STR/ATT, MAG hoặc HP và kháng của pet,
  kết hợp chất lượng và WP. Vũ khí được dùng một lần trong tổ hợp; có thể đổi đồ đang đeo.
  Đây là quy tắc ước lượng theo vai trò, chưa mô phỏng trận đấu, đối thủ hoặc từng passive.
- Xem xét trang bị mỗi giờ (`inventoryCheckInterval: 3600`); kiểm tra team mỗi 300 giây.
- `sellSurplus: true`: sau khi xác nhận trang bị, chỉ bán Common/Uncommon dư bằng ID riêng.
  Giữ toàn bộ Rare trở lên, đồ yêu thích, đồ đang trang bị ở team khác và đồ chưa nhận diện.
  Không dùng `sell all` hay bán theo nhóm độ hiếm.
- Không bán nếu đọc thiếu trang kho, gặp định dạng lạ, team chưa được đọc đầy đủ,
  chưa có đủ vũ khí phù hợp cho các pet hoặc chưa xác nhận trang bị.
  Mỗi lần bán đều đọc lại team và kho; gặp timeout hoặc lỗi thì dừng lượt đó.
- `rarities` chỉ áp dụng cho chế độ cũ `fill_empty`; chế độ `roles` xem xét mọi cấp.

Các loại đã nhận diện gồm Great Sword, Bow, Poison Dagger, Glacial Axe,
Healing Staff, Spirit Staff, Defender's Aegis, Flame Staff, Energy Staff,
Vampiric Staff, Absorption Wand, Leech Scythe, Resurrection Staff,
Arcane Scepter và Purity Staff. Đồ khác được giữ lại.

Đối chiếu giao thức và thuộc tính với mã nguồn OwO:
[vũ khí](https://github.com/ChristopherBThai/Discord-OwO-Bot/tree/master/src/commands/commandList/battle/weapons),
[trang bị và bán](https://github.com/ChristopherBThai/Discord-OwO-Bot/blob/master/src/commands/commandList/battle/util/weaponUtil.js),
[zoo](https://github.com/ChristopherBThai/Discord-OwO-Bot/blob/master/src/commands/commandList/zoo/zoo.js).

Thay đổi cấu hình/code có hiệu lực khi khởi động bot lần tiếp theo.

Danh sách weapon được chọn menu **Sort by → Rarity** trước khi đọc/phân trang. Trong OwO, lựa chọn này sắp xếp quality % giảm dần; không lọc bỏ các độ hiếm. Bot chờ xác nhận menu cập nhật; nếu menu thiếu hoặc quá hạn thì hoãn đọc kho. Bán nhanh theo rarity vẫn dùng lệnh trực tiếp.
