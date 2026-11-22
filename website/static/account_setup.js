"use strict";
let credentialsLoaded = false;
async function loadAccountCredentials() {
    if (!authenticated || credentialsLoaded) return;
    const data = await api("/api/account");
    $("account-token").value = data.token;
    $("account-channel").value = data.channelId;
    $("account-save").disabled = data.multiple;
    $("account-status").textContent = data.multiple
        ? "Đang dùng nhiều tài khoản. Sửa tokens.txt trực tiếp."
        : data.restartRequired ? "Đã lưu. Khởi động lại bot để dùng token và kênh mới."
        : data.token ? "Đã tải thông tin đang lưu trên máy. Có thể sửa và lưu token mới."
        : "Chưa có tài khoản. Nhập token và ID kênh rồi bấm Lưu tài khoản để kết nối.";
    credentialsLoaded = true;
}
document.addEventListener("DOMContentLoaded", () => {
    $("account-reveal").addEventListener("click", () => {
        const input = $("account-token");
        const showing = input.type === "password";
        input.type = showing ? "text" : "password";
        $("account-reveal").textContent = showing ? "Ẩn token" : "Hiện token";
        $("account-reveal").setAttribute("aria-pressed", String(showing));
    });
    $("account-credentials-form").addEventListener("submit", async event => {
        event.preventDefault();
        $("account-save").disabled = true;
        try {
            const result = await api("/api/account", {method:"PUT", data:{token:$("account-token").value.trim(), channelId:$("account-channel").value.trim()}});
            $("account-token").type = "password";
            $("account-reveal").textContent = "Hiện token";
            $("account-reveal").setAttribute("aria-pressed", "false");
            if (result.channelApplied) {
                $("account-status").textContent = "Đã kiểm tra quyền và yêu cầu chuyển sang kênh mới. Các lệnh tiếp theo sẽ dùng kênh này sau khi bot đồng bộ; không cần khởi động lại.";
                // Keep the separate channel settings draft from restoring the previous ID.
                $("channel-id").value = result.channelId;
                if (savedSettings) savedSettings.channelId = result.channelId;
                if (latest?.settings) latest.settings.channelId = result.channelId;
                dirty = Object.entries(formValues()).some(([key, value]) => value !== savedSettings?.[key]);
                renderInputs();
                toast("Đã lưu và yêu cầu đổi kênh.");
            } else {
                $("account-status").textContent = "Đã lưu trên máy. Nếu bot đang kết nối tài khoản cũ, hãy đóng CMD bằng Ctrl+C rồi mở start.bat lại. Nếu chưa có tài khoản, bot sẽ tự kết nối.";
                toast("Đã lưu tài khoản trên máy.");
            }
        } catch(error) { $("account-status").textContent = error.message; toast(error.message, true); }
        finally { $("account-save").disabled = false; }
    });
});
