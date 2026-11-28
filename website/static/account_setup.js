"use strict";

let editingAccount = null;
let accountSaving = false;
let accountListSignature = "";
let directoryRequest = 0;
let directoryPolling = false;

async function refreshAccountDirectory({background = false} = {}) {
    const request = ++directoryRequest;
    try {
        const data = await api("/api/accounts");
        if (request !== directoryRequest || (background && !$("account-editor").hidden)) return;
        managedAccounts = data.accounts;
        if (!authenticated) return;
        renderScope();
        if (accountScope && !managedAccounts.some(account => account.accountId === accountScope)
                && !resetBusy && !saleSubmitting) {
            await selectAccountScope("");
        }
    } catch (error) {
        if (background || request !== directoryRequest) return;
        $("account-status").textContent = error.message;
        $("account-status").classList.add("error");
    }
}

async function pollAccountDirectory() {
    if (!authenticated || directoryPolling || accountSaving || !$("account-editor").hidden) return;
    directoryPolling = true;
    try {
        await refreshAccountDirectory({background: true});
    } finally {
        directoryPolling = false;
    }
}

function accountConnection(account) {
    const live = runtimeFor(account.accountId);
    if (account.restartRequired) return "Cần khởi động lại";
    if (live?.channelError) return "Không truy cập được kênh";
    if (!live?.connected) return "Chưa kết nối";
    if (live.captchaBlocked) return "Đang chờ xác minh";
    if (!live.running) return "Đã dừng tự động";
    return "Đã kết nối";
}

function accountButton(label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button secondary";
    button.textContent = label;
    button.addEventListener("click", action);
    return button;
}

function renderAccountManager() {
    const entries = managedAccounts.map(account => ({
        id: account.accountId,
        name: accountName(account.accountId),
        channel: runtimeFor(account.accountId)?.channelId || account.channelId,
        status: accountConnection(account),
    }));
    const signature = JSON.stringify([accountScope, entries]);
    if (signature === accountListSignature) return;
    accountListSignature = signature;
    const list = $("account-list");
    if (!entries.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = "Chưa có tài khoản. Chọn Thêm tài khoản để bắt đầu.";
        list.replaceChildren(empty);
        return;
    }
    list.replaceChildren(...entries.map(account => {
        const row = document.createElement("article");
        row.className = "account-row";
        row.classList.toggle("selected", account.id === accountScope);
        const identity = document.createElement("div");
        const name = document.createElement("strong");
        name.textContent = account.name;
        const channel = document.createElement("p");
        channel.textContent = `Kênh ${account.channel}`;
        identity.append(name, channel);
        const status = document.createElement("span");
        status.className = account.status === "Đã kết nối" ? "badge connected" : "badge";
        status.textContent = account.status;
        const actions = document.createElement("div");
        actions.className = "account-row-actions";
        actions.append(
            accountButton("Thiết lập", async () => {
                await selectAccountScope(account.id);
                if (accountScope === account.id) activatePage("controls");
            }),
            accountButton("Đổi token", () => openAccountEditor(account.id)),
        );
        row.append(identity, status, actions);
        return row;
    }));
}

function hideAccountSecret() {
    $("account-token").type = "password";
    $("account-saved-token").value = "";
    $("account-saved-token").hidden = true;
    $("account-reveal").textContent = editingAccount ? "Xem token đang lưu" : "Hiện token";
    $("account-reveal").setAttribute("aria-pressed", "false");
}

function openAccountEditor(accountId = null) {
    if (accountSaving) return;
    editingAccount = accountId;
    hideAccountSecret();
    $("account-token").value = "";
    $("account-channel").value = "";
    $("account-channel").required = !accountId;
    $("account-channel").disabled = Boolean(accountId);
    $("account-channel-field").hidden = Boolean(accountId);
    $("account-editor-title").textContent = accountId ? `Đổi token · ${accountName(accountId)}` : "Thêm tài khoản";
    $("account-editor-description").textContent = accountId
        ? "Nhập token mới của tài khoản này. Bot sẽ dùng token mới sau khi khởi động lại."
        : "Nhập token và ID kênh Discord dành cho tài khoản mới.";
    $("account-save").textContent = accountId ? "Lưu token mới" : "Thêm tài khoản";
    $("account-editor").hidden = false;
    $("account-status").textContent = "";
    $("account-token").focus();
}

function closeAccountEditor() {
    if (accountSaving) return;
    editingAccount = null;
    hideAccountSecret();
    $("account-token").value = "";
    $("account-channel").value = "";
    $("account-editor").hidden = true;
}

async function revealAccountSecret() {
    const button = $("account-reveal");
    if (button.getAttribute("aria-pressed") === "true") {
        hideAccountSecret();
        return;
    }
    const account = editingAccount;
    button.disabled = true;
    try {
        if (account) {
            const data = await api(`/api/accounts/${encodeURIComponent(account)}?reveal=1`);
            if (editingAccount !== account || $("account-editor").hidden) return;
            $("account-saved-token").value = data.account.token;
            $("account-saved-token").hidden = false;
        } else {
            $("account-token").type = "text";
        }
        button.setAttribute("aria-pressed", "true");
        button.textContent = "Ẩn token";
    } catch (error) {
        toast(error.message, true);
    } finally {
        button.disabled = false;
    }
}

async function saveAccount(event) {
    event.preventDefault();
    if (accountSaving) return;
    accountSaving = true;
    $("account-save").disabled = true;
    const account = editingAccount;
    const data = {token: $("account-token").value.trim()};
    if (!account) data.channelId = $("account-channel").value.trim();
    try {
        const result = await api(account ? `/api/accounts/${encodeURIComponent(account)}` : "/api/accounts", {
            method: account ? "PATCH" : "POST", data,
        });
        await refreshAccountDirectory();
        accountSaving = false;
        closeAccountEditor();
        $("account-status").textContent = "";
        $("account-status").classList.remove("error");
        toast(result.account.restartRequired
            ? "Đã lưu. Khởi động lại bot để dùng cấu hình mới."
            : "Đã lưu thông tin tài khoản.");
    } catch (error) {
        $("account-status").textContent = error.message;
        $("account-status").classList.add("error");
    } finally {
        accountSaving = false;
        $("account-save").disabled = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    $("account-add").addEventListener("click", () => openAccountEditor());
    $("account-close").addEventListener("click", closeAccountEditor);
    $("account-reveal").addEventListener("click", revealAccountSecret);
    $("account-credentials-form").addEventListener("submit", saveAccount);
    setInterval(pollAccountDirectory, 5000);
});
