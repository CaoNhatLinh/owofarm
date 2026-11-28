"use strict";
const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat("vi-VN").format(value || 0);
const sessionPreferences = new Map();
try { localStorage.removeItem("password"); } catch {}

function getPreference(key) {
    if (sessionPreferences.has(key)) return sessionPreferences.get(key);
    try { return localStorage.getItem(key); } catch { return null; }
}

function setPreference(key, value) {
    sessionPreferences.set(key, value);
    try { localStorage.setItem(key, value); } catch {}
}

let authenticated = false, busy = false, saving = false, dirty = false;
let dashboardOnline = false, stateGeneration = 0;
let saveError = "";
let latest = null, savedSettings = null, logs = [], autoScroll = true, pollBusy = false, metricsBusy = false;
let accountScope = "", switchingScope = false, managedAccounts = [];
const accountDrafts = new Map();
const charts = {};
let saleData = {accounts:[],jobs:[]}, saleSubmitting = false, salesPolling = false;
let pendingSaleRequest = null, lastSaleId = null;
let saleError = "";
let catchesPolling = false;
let resetBusy=false, pendingReset=null;
let riskManual=false;
const palette = ["#287557", "#436fa0", "#956120", "#775898", "#ac4948", "#438286", "#607747"];
const gameLabels = {coinflip: "Tung xu", slots: "Máy quay", blackjack: "Bài 21"};
const sideLabel = side => side === "tails" ? "Sấp" : "Ngửa";
const automationSwitches = {
    prayEnabled: "pray-enabled",
    randomChatEnabled: "random-chat-enabled",
    teamSetupEnabled: "team-setup-enabled",
    huntbotEnabled: "huntbot-enabled",
    huntbotMax: "huntbot-max",
    huntbotUpgradeEnabled: "huntbot-upgrade-enabled",
    huntEmergencySellEnabled: "hunt-emergency-sell-enabled",
    zooSacrificeSurplusEnabled: "zoo-sacrifice-surplus-enabled",
};

function scopedPath(path, account = accountScope) {
    return account ? `${path}?accountId=${encodeURIComponent(account)}` : path;
}

function runtimeFor(account = accountScope) {
    return account ? latest?.accounts.find(item => item.accountId === account) : undefined;
}

function accountName(account = accountScope) {
    return runtimeFor(account)?.name || managedAccounts.find(item => item.accountId === account)?.name || account;
}

function scopedChanges(values = formValues()) {
    return Object.fromEntries(Object.entries(values).filter(([key, value]) =>
        (key !== "channelId" || accountScope) && value !== savedSettings?.[key]));
}

async function selectAccountScope(account) {
    if (account === accountScope || switchingScope || saving || busy) return;
    if (dirty) accountDrafts.set(accountScope, scopedChanges());
    else accountDrafts.delete(accountScope);
    switchingScope = true;
    stateGeneration++;
    renderState();
    try {
        const state = await api(scopedPath("/api/bot", account));
        accountScope = account;
        setPreference("dusk-account-scope", account);
        latest = state;
        saveError = "";
        riskManual = false;
        $("risk-bankroll").value = getPreference(bankrollKey()) || "";
        $("reset-session-status").textContent = "";
        lastSaleId = null;
        saleError = "";
        loadSettings(state.settings, accountDrafts.get(account));
        renderState();
        renderSales();
    } catch (error) {
        toast(error.message, true);
    } finally {
        switchingScope = false;
        renderState();
    }
}

function renderScope() {
    const select = $("account-scope");
    const options = managedAccounts.map(account => [account.accountId, accountName(account.accountId)]);
    const signature = JSON.stringify(options);
    if (select.dataset.options !== signature) {
        select.replaceChildren(new Option("Thiết lập mặc định", ""), ...options.map(([id, name]) => new Option(name, id)));
        select.dataset.options = signature;
    }
    select.value = accountScope;
    select.disabled = !authenticated || switchingScope || busy || saving || resetBusy || saleSubmitting;
    $("channel-settings").hidden = !accountScope;
    $("scope-description").textContent = accountScope
        ? `Đang xem ${accountName()}. Thay đổi chỉ áp dụng cho tài khoản này.`
        : "Thiết lập mặc định áp dụng cho các tài khoản chưa chỉnh riêng.";
    $("scope-status").textContent = switchingScope ? "Đang tải thiết lập…" : accountDrafts.size
        ? `${accountDrafts.size} phạm vi có bản nháp đã giữ` : "";
    if (typeof renderAccountManager === "function") renderAccountManager();
}

function bankrollKey() {
    return accountScope ? `dusk-risk-bankroll:${accountScope}` : "dusk-risk-bankroll";
}

async function api(path, { method = "GET", data, text = false } = {}) {
    const options = {method, cache:"no-store", headers:{}};
    if (data !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(data); }
    const response = await fetch(path, options);
    if (!response.ok) {
        let detail;
        try { detail = await response.json(); } catch (_) {}
        const error=new Error(detail?.message || "Chưa kết nối được với bot. Vui lòng thử lại."); error.status=response.status; throw error;
    }
    return text ? response.text() : response.json();
}
function toast(message, error = false) {
    const element = $("toast");
    element.textContent = message; element.classList.toggle("error", error); element.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { element.hidden = true; }, 4000);
}
function formValues() {
    return { restEnabled:$("rest-enabled").checked, failureThreshold:Number($("failure-threshold").value),
        restMinutes:Number($("rest-minutes").value), responseTimeout:Number($("response-timeout").value),
        messageInterval:Number($("message-interval").value), owoEnabled:$("owo-enabled").checked,
        huntEnabled:$("hunt-enabled").checked, battleEnabled:$("battle-enabled").checked,
        channelId:$("channel-id").value.trim(), prefix:$("command-prefix").value,
        gemOrder:$("gem-order").value, gemsEnabled:$("gems-enabled").checked,
        gemSkipAtOrAbove:$("gem-skip-rarity").value, gambleGoalEnabled:$("gamble-goal-enabled").checked,
        ...Object.fromEntries(Object.entries(automationSwitches)
            .filter(([key]) => key !== "randomChatEnabled" || randomChatSupported())
            .map(([key, id]) => [key, $(id).checked])),
        gambleGoalAmount:Number($("gamble-goal-amount").value),
        gambleLossEnabled:$("gamble-loss-enabled").checked, gambleLossAmount:Number($("gamble-loss-amount").value), coinflipEnabled:$("coinflip-enabled").checked,
        slotsEnabled:$("slots-enabled").checked, blackjackEnabled:$("blackjack-enabled").checked,
        coinflipSide:$("coinflip-side").value,
        coinflipBonusOnLoss:$("coinflip-bonus").checked,
        coinflipProbeTarget:$("coinflip-probe-target").value,
        coinflipSwitchStart:$("coinflip-switch-start").value,
        coinflipHistoryWindow:Number($("coinflip-history-window").value),
        ...Object.fromEntries(["coinflip","slots","blackjack"].flatMap(game=>[[game+"Bet",Number($(game+"-bet").value)],[game+"DoubleOnLoss",$(game+"-double").checked]])) };
}
function gambleLabel(game) {
    if (game !== "coinflip") return gameLabels[game];
    const mode = $("coinflip-side").value;
    if (mode === "win_switch") return "Tung xu · Thắng đổi, thua giữ";
    if (mode === "probe_loss") return `Tung xu · Thử đến khi thua · ${sideLabel($("coinflip-probe-target").value)}`;
    if (mode === "probe") return "Tung xu · Thử rồi chọn hoặc đảo mặt";
    const history = mode === "auto" ? `${$("coinflip-history-window").value} ván → ` : "";
    return `Tung xu · ${history}${sideLabel(coinflipSelectedSide())}`;
}
function coinflipHistoryState() {
    return runtimeFor()?.coinflipAuto;
}
function coinflipAutoState() {
    const data=coinflipHistoryState();
    return data?.choices?.[$("coinflip-history-window").value] || data;
}
function coinflipSelectedSide() {
    const mode=$("coinflip-side").value;
    if(mode === "win_switch") {
        const start=$("coinflip-switch-start").value;
        return latest?.settings?.coinflipSide==="win_switch" && latest?.settings?.coinflipSwitchStart===start ? coinflipHistoryState()?.probePlan?.side || start : start;
    }
    if(mode === "probe_loss") return coinflipLossProbePlan().side;
    if(mode === "probe") return coinflipHistoryState()?.probePlan?.side || "heads";
    return mode === "auto" ? (coinflipAutoState()?.side || "heads") : mode;
}
function coinflipLossProbePlan() {
    const target=$("coinflip-probe-target").value;
    const current=latest?.settings?.coinflipSide==="probe_loss" && latest?.settings?.coinflipProbeTarget===target;
    return current && coinflipHistoryState()?.probePlan || {phase:"probe",side:target};
}
function renderCoinflipFrequency(data, prefix, windowSize) {
    const total=data?.total || 0;
    const heads=data?.appearances?.heads || 0, tails=data?.appearances?.tails || 0;
    for(const [side,count] of [["heads",heads],["tails",tails]]) {
        const percent=total?100*count/total:0;
        $(prefix+"frequency-"+side).textContent=total?`${count} lần · ${percent.toLocaleString("vi-VN",{maximumFractionDigits:1})}%`:"Chưa có dữ liệu";
        $(prefix+"bar-"+side).style.width=percent+"%";
    }
    $(prefix+"frequency-summary").textContent=!total?`Đã ghi 0/${windowSize} ván · Chưa có dữ liệu.`
        :`Đã ghi ${total}/${windowSize} ván · ${data.mostCommon ? sideLabel(data.mostCommon) + " xuất hiện nhiều hơn." : "Hai mặt bằng nhau."}`;
}
function renderCoinflipSide() {
    const mode=$("coinflip-side").value, data=coinflipAutoState(), history=coinflipHistoryState();
    renderCoinflipFrequency(history?.windows?.["500"] || history,"coinflip-",500);
    renderCoinflipFrequency(history?.windows?.["100"],"coinflip-recent-",100);
    $("coinflip-frequency-note").textContent="Mẫu 100 ván nằm trong mẫu 500 ván. Lịch sử được lưu riêng cho từng tài khoản.";
    $("coinflip-side-preview").textContent=`Lệnh cược ban đầu: ${$("command-prefix").value}cf ${$("coinflip-bet").value} ${coinflipSelectedSide()}`;
    $("coinflip-auto-status").hidden=mode!=="auto";
    $("coinflip-history-field").hidden=mode!=="auto";
    $("coinflip-probe-status").hidden=!["probe","probe_loss","win_switch"].includes(mode);
    $("coinflip-switch-field").hidden=mode!=="win_switch";
    if(mode==="win_switch") {
        $("coinflip-probe-status").textContent=`Mặt tiếp theo · ${sideLabel(coinflipSelectedSide())}`;
        $("coinflip-side-preview").textContent+=". Thắng thì đổi mặt cho ván sau, thua thì giữ mặt.";
    }
    $("coinflip-probe-target-field").hidden=mode!=="probe_loss";
    $("risk-probe-note").hidden=!["probe","probe_loss"].includes(mode) || activeGame!=="coinflip";
    if(mode==="probe_loss") {
        const target=sideLabel($("coinflip-probe-target").value);
        const plan=coinflipLossProbePlan();
        $("coinflip-probe-status").textContent=plan.phase==="wager"
            ? `Cược chính · ${target}` : `Thử 1 cowoncy · ${target}`;
        $("coinflip-side-preview").textContent=`Cược thử 1 cowoncy cho đến khi thua. Sau ván cược chính, bot quay lại thử.`;
    }
    if(mode==="probe") {
        const plan=history?.probePlan;
        $("coinflip-probe-status").textContent=plan?.phase==="wager" ? `Cược chính · ${sideLabel(plan.side)}` : "Thử 1 cowoncy · Ngửa";
        $("coinflip-side-preview").textContent="Sau lượt thử, bot chọn một mặt ngẫu nhiên. Thử thắng thì đảo mặt vừa chọn; thử thua thì giữ để cược chính.";
    }
    if(mode!=="auto") return;
    $("coinflip-side-preview").textContent+=". Bot giữ mặt khi thua và chọn lại sau khi thắng.";
    $("coinflip-auto-status").textContent=!data ? "Ngửa · Chưa có lịch sử"
        : `${sideLabel(data.side)} · ${data.total}/${data.window} ván${data.reason === "locked" ? " · Đang giữ mặt" : ""}`;
}
function randomChatSupported() {
    return Object.prototype.hasOwnProperty.call(latest?.settings || {}, "randomChatEnabled");
}
function renderRandomChatSetting() {
    const supported = randomChatSupported();
    $("random-chat-enabled").disabled = !supported;
    $("random-chat-hint").textContent = supported
        ? "Thử gửi một câu ngắn sau mỗi 2–6 phút khi rảnh, tuân theo khoảng cách tin nhắn, thời gian nghỉ và trạng thái CAPTCHA."
        : "Khởi động lại bot để dùng Chat ngẫu nhiên.";
}
function renderInputs() {
    renderRandomChatSetting();
    const config = formValues();
    $("threshold-value").textContent = `${config.failureThreshold} lần`;
    $("rest-value").textContent = `${config.restMinutes} phút`;
    $("timeout-value").textContent = `${config.responseTimeout} giây`;
    $("interval-value").textContent = String(config.messageInterval).replace(".", ",");
    $("prefix-length").textContent = `${config.prefix.length} ký tự (tính cả dấu cách)`;
    $("prefix-preview").textContent = config.prefix + "h";
    $("hunt-command-preview").textContent=config.prefix+"h";
    $("battle-command-preview").textContent=config.prefix+"b";
    const prayerRecipient = savedSettings?.prayRecipientId;
    $("pray-command-preview").textContent = config.prefix + "pray" + (
        prayerRecipient && prayerRecipient !== accountScope ? ` @${accountName(prayerRecipient)}` : ""
    );
    $("gem-order-hint").textContent = config.gemOrder === "high_to_low"
        ? "Fabled → Legendary → Mythical → Epic → Rare → Uncommon → Common"
        : "Common → Uncommon → Rare → Epic → Mythical → Legendary → Fabled";
    $("gem-order").disabled = !config.gemsEnabled;
    $("gem-skip-rarity").disabled = !config.gemsEnabled;
    $("gem-limit-preview").hidden = !config.gemsEnabled || config.gemSkipAtOrAbove !== "common";
    $("huntbot-max").disabled = !config.huntbotEnabled;
    $("huntbot-upgrade-enabled").disabled = !config.huntbotEnabled;
    for (const id of ["failure-threshold", "rest-minutes", "response-timeout"]) $(id).disabled = !config.restEnabled;
    document.querySelectorAll('input[type="range"]').forEach(input => {
        const fill = 100 * (Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min));
        input.style.setProperty("--fill", `${fill}%`);
    });
    $("coinflip-bonus").disabled = !config.coinflipDoubleOnLoss;
    $("coinflip-bonus-hint").textContent = config.coinflipDoubleOnLoss
        ? "Sau mỗi ván thua chính, nhân cược trước lần lượt với 2,00 → 2,10 → 2,20 → 2,30… và làm tròn xuống."
        : "Bật Nhân đôi khi thua để dùng hệ số tăng dần.";
    for (const game of ["coinflip", "slots", "blackjack"]) {
        const amount = config[game+"Bet"];
        const preview = $(game+"-bet-preview");
        const valid = Number.isInteger(amount) && amount >= 1 && amount <= 250000;
        preview.hidden = valid && !config[game+"DoubleOnLoss"];
        if (!valid) {
            preview.textContent = "Nhập số nguyên từ 1 đến 250.000.";
        } else if (config[game+"DoubleOnLoss"]) {
            const bonus = game === "coinflip" && config.coinflipBonusOnLoss;
            const projection = GambleMath.project(amount, true, bonus ? 3 : 2, null, bonus);
            const sequence = [...projection.rows.map(row => row.stake), projection.next];
            preview.textContent = `${sequence.map(number).join(" → ")}… · Thắng: về ${number(amount)}`;
        }
    }
    $("gamble-loss-amount").disabled = !config.gambleLossEnabled;
    $("gamble-goal-amount").disabled = !config.gambleGoalEnabled;
    renderGambleRisk();
    updateSaveBar(config);
    $("save-settings").disabled = !authenticated || !dirty || saving;
    $("save-status").textContent = saving ? "Đang lưu…" : saveError || (dirty ? "Có thay đổi chưa lưu" : "Đã lưu cấu hình");
    $("save-status").classList.toggle("error", Boolean(saveError));
}
function loadSettings(config, draft = {}) {
    savedSettings = config;
    config = {...config, ...draft};
    $("gamble-loss-enabled").checked = config.gambleLossEnabled;
    $("gamble-loss-amount").value = config.gambleLossAmount;
    $("gamble-goal-enabled").checked = config.gambleGoalEnabled;
    $("gamble-goal-amount").value = config.gambleGoalAmount;
    $("rest-enabled").checked = config.restEnabled;
    $("owo-enabled").checked = config.owoEnabled;
    $("hunt-enabled").checked = config.huntEnabled;
    $("battle-enabled").checked = config.battleEnabled;
    for (const game of ["coinflip", "slots", "blackjack"]) {
        $(game+"-enabled").checked = Boolean(config[game+"Enabled"]);
        $(game+"-bet").value = config[game+"Bet"];
        $(game+"-double").checked = Boolean(config[game+"DoubleOnLoss"]);
    }
    $("failure-threshold").value = config.failureThreshold;
    $("rest-minutes").value = config.restMinutes;
    $("response-timeout").value = config.responseTimeout;
    $("message-interval").value = config.messageInterval;
    $("channel-id").value = config.channelId || "";
    $("command-prefix").value = config.prefix;
    $("gem-order").value = config.gemOrder;
    $("gems-enabled").checked = config.gemsEnabled !== false;
    $("gem-skip-rarity").value = config.gemSkipAtOrAbove || "none";
    for (const [key, id] of Object.entries(automationSwitches)) $(id).checked = Boolean(config[key]);
    $("coinflip-bonus").checked = Boolean(config.coinflipBonusOnLoss);
    $("coinflip-side").value = config.coinflipSide || "heads";
    $("coinflip-probe-target").value = config.coinflipProbeTarget || "heads";
    $("coinflip-switch-start").value = config.coinflipSwitchStart || "heads";
    $("coinflip-history-window").value = config.coinflipHistoryWindow || 500;
    dirty = Object.keys(scopedChanges()).length > 0;
    renderInputs();
}
function formatTime(seconds) {
    seconds = Math.max(0, Math.ceil(seconds));
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
function renderAutomationStatus(config, account, visibleAccounts) {
    const team = account?.teamSetup;
    const teamStatus = $("team-setup-status");
    const teamLabels = {
        checking_team: "Đang kiểm tra đội hình", checking_zoo: "Đang kiểm tra sở thú",
        equipping: "Đang chọn và gắn vũ khí", ready: "Đội hình đã sẵn sàng",
        waiting_confirmation: "Đang chờ OwO xác nhận đội", waiting_pet: "Chờ bắt được thú để thêm vào đội",
    };
    teamStatus.hidden = !account || !config.teamSetupEnabled;
    teamStatus.textContent = team?.message || teamLabels[team?.state || team] || "Chờ kiểm tra đội hình";

    const huntbot = account?.huntbotStatus;
    const huntbotStatus = $("huntbot-status");
    const huntbotLabels = {
        "waiting-team": "Chờ chuẩn bị xong đội hình", paused: "Đang tạm dừng",
        checking: "Đang kiểm tra HuntBot", balance: "Đang chờ đủ cowoncy",
        upgrading: "Đang nâng cấp", captcha: "Đang chờ xác minh",
        hunting: "Đang săn", ready: "Sẵn sàng", unavailable: "Chưa có thông tin từ OwO",
    };
    huntbotStatus.hidden = !account || !config.huntbotEnabled;
    huntbotStatus.textContent = huntbotLabels[huntbot?.state] || "Chờ kiểm tra HuntBot";

    const alert = visibleAccounts.find(item => item.huntbotCaptcha);
    const captcha = alert?.huntbotCaptcha;
    const link = $("huntbot-captcha-link");
    const ids = captcha ? [captcha.guildId, captcha.channelId, captcha.messageId] : [];
    const canOpen = ids.length === 3 && ids.every(id => /^\d{17,20}$/.test(String(id)));
    link.hidden = !canOpen;
    if (canOpen) {
        link.href = `https://discord.com/channels/${ids.join("/")}`;
        link.textContent = accountScope ? "Xác minh HuntBot" : `Xác minh HuntBot · ${alert.name}`;
    } else {
        link.removeAttribute("href");
    }
}

function renderState() {
    if (!latest) return;
    const config = latest.settings;
    const selected = runtimeFor();
    const accounts = accountScope ? [selected].filter(Boolean) : latest.accounts;
    const connected = accounts.filter(account => account.accountId && account.connected !== false);
    const now = Date.now() / 1000;
    const resting = selected?.restUntil > now ? selected : null;
    const captcha = Boolean(selected?.captchaBlocked);
    const sleeping = Boolean(selected?.scheduledSleep);
    const resuming = Boolean(selected && latest.running && selected.resumeGeneration < latest.resumeRequest);
    const channelError = selected?.channelError;
    const account = managedAccounts.find(item => item.accountId === accountScope);
    const channel = selected?.channelId || account?.channelId;

    renderScope();
    renderAutomationStatus(config, selected, accounts);
    renderGambleSession(accounts);
    const profit = selected?.gambleProfit ?? 0;
    const loss = Math.max(0, -profit);
    const lossStopped = config.gambleLossEnabled && (selected?.gambleLossStopped || loss >= config.gambleLossAmount);
    const profitReached = config.gambleGoalEnabled && profit >= config.gambleGoalAmount;
    $("gamble-loss-status").textContent = selected
        ? `Đã lỗ ${number(loss)}${lossStopped ? " · Chạm giới hạn" : ""}`
        : "Đã lỗ —";
    $("gamble-profit-status").textContent = selected
        ? `Lãi/lỗ ${profit > 0 ? "+" : ""}${number(profit)}${profitReached ? " · Đạt mục tiêu" : ""}`
        : "Lãi/lỗ —";
    $("gamble-loss-status").classList.toggle("reached", Boolean(selected && lossStopped));
    $("gamble-profit-status").classList.toggle("reached", Boolean(selected && profitReached));
    $("channel-state").textContent = channelError || (channel
        ? `Kênh hiện tại: ${channel}. Bỏ trống để dùng kênh đã lưu của tài khoản.`
        : "Chưa có kênh đang kết nối.");
    $("channel-state").classList.toggle("error", Boolean(channelError));
    $("channel-id").placeholder = channel || "ID kênh Discord";

    $("account-name").textContent = accountScope ? accountName() : `${connected.length}/${managedAccounts.length} tài khoản kết nối`;
    $("bot-toggle").textContent = accountScope
        ? (latest.running ? "Dừng tài khoản" : "Chạy tài khoản")
        : (latest.running ? "Dừng tất cả" : "Chạy tất cả");
    $("bot-toggle").dataset.running = String(latest.running);
    $("bot-toggle").disabled = !dashboardOnline || busy || switchingScope || resuming || Boolean(accountScope && !latest.allRunning);
    $("master-toggle").hidden = !accountScope;
    $("master-toggle").textContent = latest.allRunning ? "Dừng tất cả" : "Chạy tất cả";
    $("master-toggle").disabled = !dashboardOnline || busy || switchingScope;
    $("resume-bot").hidden = !latest.running || !(captcha || resting || resuming);
    $("resume-bot").disabled = !dashboardOnline || busy || switchingScope || resuming;
    $("resume-bot").textContent = resuming ? "Đang tiếp tục…" : captcha ? "Đã xác minh · Tiếp tục" : "Tiếp tục ngay";
    const status = !latest.running ? "Đã dừng tự động"
        : channelError ? "Không truy cập được kênh"
        : !connected.length ? "Chưa kết nối Discord"
        : resuming ? "Đang tiếp tục…"
        : captcha ? "Đang chờ xác minh"
        : resting && config.restEnabled ? "Đang nghỉ do mất phản hồi"
        : sleeping ? "Đang nghỉ theo lịch" : "Đang hoạt động";
    const attention = !connected.length || !latest.running || Boolean(channelError || resting) || captcha || sleeping;
    $("bot-status").textContent = status;
    $("header-status").textContent = status;
    $("header-status").classList.toggle("attention", attention);
    $("status-dot").classList.toggle("paused", attention);
    $("status-detail").textContent = !latest.running ? "Đã tạm ngừng gửi lệnh tự động."
        : channelError || (!connected.length ? "Mở Tài khoản Discord để xem hoặc chỉnh kết nối."
        : resuming ? "Bot đang chuẩn bị gửi lại lệnh theo thiết lập."
        : captcha ? "Sau khi xác minh trong Discord, chọn Đã xác minh để tiếp tục."
        : resting && config.restEnabled ? "Bot sẽ thử gửi lại lệnh khi hết thời gian nghỉ."
        : accountScope ? `Khoảng cách tối thiểu giữa hai tin nhắn là ${number(config.messageInterval)} giây.`
        : "Chọn một tài khoản để xem trạng thái và thiết lập riêng.");

    const timer = $("rest-timer");
    $("rest-caption").textContent = accountScope ? (resting ? "Thời gian nghỉ còn lại" : "Theo dõi phản hồi") : "Trạng thái kết nối";
    timer.textContent = !accountScope ? `${connected.length}/${managedAccounts.length}` : !config.restEnabled ? "Đã tắt"
        : resting ? formatTime(resting.restUntil - now) : `${selected?.misses || 0}/${config.failureThreshold}`;
    const progress = !accountScope ? 100 * connected.length / Math.max(1, managedAccounts.length)
        : !config.restEnabled ? 0 : resting ? 100 * (resting.restUntil - now) / (config.restMinutes * 60)
        : 100 * (selected?.misses || 0) / config.failureThreshold;
    $("rest-progress").style.width = `${Math.max(0, Math.min(100, progress))}%`;
    $("misses-caption").textContent = !accountScope ? "Tài khoản đã kết nối Discord."
        : !config.restEnabled ? "Chế độ tự nghỉ khi mất phản hồi đang tắt."
        : selected?.waitingForReply ? "Đang chờ OwO trả lời."
        : `Thời gian nghỉ khi mất phản hồi: ${number(config.restMinutes)} phút.`;
}

async function login() {
    try {
        await refreshAccountDirectory();
        const previous = getPreference("dusk-account-scope");
        accountScope = previous === "" || managedAccounts.some(account => account.accountId === previous)
            ? previous : managedAccounts[0]?.accountId || "";
        latest = await api(scopedPath("/api/bot"));
        authenticated = true;
        dashboardOnline = true;
        $("settings-fields").disabled = false;
        $("risk-bankroll").value = getPreference(bankrollKey()) || "";
        loadSettings(latest.settings, accountDrafts.get(accountScope));
        renderState();
        $("connection").textContent = "Đã kết nối bảng điều khiển";
        $("connection").classList.remove("offline");
        await Promise.allSettled([poll(), updateMetrics(), pollSales(), pollCatches()]);
    } catch (error) {
        $("connection").textContent = "Chưa kết nối bảng điều khiển";
        $("connection").classList.add("offline");
        toast(error.message, true);
    }
}

async function poll() {
    if (!authenticated) { await login(); return; }
    if (pollBusy || busy || saving || switchingScope) return;
    pollBusy = true;
    const scope = accountScope;
    const generation = stateGeneration;
    try {
        const state = await api(scopedPath("/api/bot", scope));
        if (generation === stateGeneration && scope === accountScope) {
            dashboardOnline = true;
            latest = state;
            if (!dirty && !saving) loadSettings(state.settings);
            $("connection").textContent = "Đã kết nối bảng điều khiển";
            $("connection").classList.remove("offline");
            renderState();
        }
        const html = await api("/api/console", {text:true}).catch(() => null);
        if (html !== null) {
            const parsed = new DOMParser().parseFromString(html, "text/html");
            logs = Array.from(parsed.body.children).map(node => node.textContent.trim());
            if (!logs.length && parsed.body.textContent.trim()) logs = parsed.body.textContent.trim().split("\n");
            renderLogs();
        }
    } catch (error) {
        if (generation !== stateGeneration || scope !== accountScope) return;
        dashboardOnline = false;
        $("connection").textContent = "Mất kết nối bảng điều khiển";
        $("connection").classList.add("offline");
        renderState();
    } finally {
        pollBusy = false;
    }
}
function renderLogs() {
    const filter = $("log-filter").value.toLocaleLowerCase("vi");
    const lines = logs.filter(line => line.toLocaleLowerCase("vi").includes(filter)).slice(-150);
    const fragment = document.createDocumentFragment();
    for (const line of lines) {
        const row = document.createElement("div"); row.className = "log-row";
        if (/error|failed|lỗi|captcha/i.test(line)) row.classList.add("error");
        const match = line.match(/^\[([^\]]+)\]\s*(.*)$/s);
        const time = document.createElement("time"); time.textContent = match ? match[1] : "—";
        const text = document.createElement("span"); text.className = "log-text"; text.textContent = match ? match[2] : line;
        row.append(time,text); fragment.append(row);
    }
    if (!lines.length) { const empty = document.createElement("p"); empty.className="empty-state"; empty.textContent=filter ? "Không có hoạt động khớp từ khoá." : "Chưa có hoạt động trong phiên này."; fragment.append(empty); }
    const panel = $("messages"), previousScroll = panel.scrollTop;
    panel.replaceChildren(fragment);
    panel.scrollTop = autoScroll ? panel.scrollHeight : previousScroll;
}

function salePreview(selectId, outputId, verb="Sẽ bán") {
    const select=$(selectId);
    $(outputId).textContent=verb+": " + Array.from(select.options).slice(0,select.selectedIndex+1).map(option=>option.textContent.trim()).join(" + ");
}
function renderSales() {
    salePreview("weapon-sale-rarity","weapon-sale-preview");
    salePreview("animal-sale-rarity","animal-sale-preview");
    salePreview("sacrifice-rarity","sacrifice-preview","Sẽ hiến tế");
    const accountId = accountScope;
    const runtime = runtimeFor();
    const active=saleData.jobs.find(job=>job.accountId===accountId && ["queued","running"].includes(job.state));
    const foreignPending = pendingSaleRequest && pendingSaleRequest.accountId !== accountId;
    const blocked = !authenticated || !accountId || !runtime?.connected || runtime.captchaBlocked || runtime.scheduledSleep || runtime.restUntil > Date.now() / 1000;
    for(const [kind,buttonId,selectId] of [["weapons","sell-weapons","weapon-sale-rarity"],["animals","sell-animals","animal-sale-rarity"],["sacrifice","sacrifice-animals","sacrifice-rarity"]]) {
        const button=$(buttonId);
        button.disabled=Boolean(blocked || saleSubmitting || active || foreignPending || (pendingSaleRequest && pendingSaleRequest.kind!==kind));
        button.textContent=saleSubmitting || active?.kind===kind ? "Đang xử lý…" : pendingSaleRequest?.kind===kind ? "Kiểm tra lại yêu cầu" : kind==="weapons" ? "Bán vũ khí ngay ↗" : kind==="sacrifice" ? "Hiến tế thú ngay ↗" : "Bán thú ngay ↗";
        $(selectId).disabled=Boolean(saleSubmitting || active || pendingSaleRequest);
    }
    const jobs = saleData.jobs.filter(item => item.accountId === accountId);
    const job = jobs.find(item => item.id === lastSaleId) || jobs.at(-1);
    if (foreignPending) {
        $("quick-sale-status").textContent = `Chuyển về ${accountName(pendingSaleRequest.accountId)} để kiểm tra giao dịch còn chờ.`;
        $("quick-sale-status").classList.remove("error");
    } else if(saleError) {
        $("quick-sale-status").textContent=saleError;$("quick-sale-status").classList.add("error");
    } else if(job) {
        $("quick-sale-status").textContent=`${job.accountName} · ${job.kind==="weapons"?"Bán vũ khí":job.kind==="sacrifice"?"Hiến tế thú":"Bán thú"} (${job.maxRarity} trở xuống): ${job.message}`;
        $("quick-sale-status").classList.toggle("error",["failed","partial","cancelled"].includes(job.state));
    } else {
        $("quick-sale-status").textContent=!accountId ? "Chọn tài khoản ở đầu trang để bán hoặc hiến tế."
            : blocked
            ? "Bot chưa sẵn sàng hoặc đang chờ CAPTCHA/nghỉ. Chờ bot tiếp tục rồi thực hiện."
            : !latest?.running ? "Farm đang dừng. Các nút bán và hiến tế vẫn dùng được; thao tác không bật lại farm."
            : "Chọn độ hiếm rồi bấm nút tương ứng. Đổi lựa chọn không tự bán/hiến tế.";
        $("quick-sale-status").classList.remove("error");
    }
}
async function pollSales() {
    if(!authenticated || salesPolling)return;
    salesPolling=true;
    try {
        saleData=await api("/api/sales");
        if(pendingSaleRequest && saleData.jobs.some(job=>job.id===pendingSaleRequest.requestId)) {
            lastSaleId=pendingSaleRequest.requestId;pendingSaleRequest=null;saleError="";
        }
        renderSales();
    } catch(error) {
        $("quick-sale-status").textContent=error.message;
        $("quick-sale-status").classList.add("error");
        $("sell-weapons").disabled=true;$("sell-animals").disabled=true;$("sacrifice-animals").disabled=true;
    } finally {salesPolling=false;}
}
async function submitSale(kind) {
    if(!accountScope || saleSubmitting || (pendingSaleRequest && (pendingSaleRequest.kind!==kind || pendingSaleRequest.accountId!==accountScope)))return;
    const data=pendingSaleRequest || {kind,maxRarity:$(kind==="weapons"?"weapon-sale-rarity":kind==="sacrifice"?"sacrifice-rarity":"animal-sale-rarity").value,accountId:accountScope,requestId:crypto.randomUUID()};
    pendingSaleRequest=data;saleSubmitting=true;saleError="";renderSales();renderScope();
    try {
        const result=await api("/api/sales",{method:"POST",data});
        lastSaleId=result.job.id;pendingSaleRequest=null;
        saleData.jobs=saleData.jobs.filter(job=>job.id!==result.job.id).concat(result.job);
        toast("Đã nhận yêu cầu. Kết quả sẽ hiện bên dưới và trong nhật ký.");
    } catch(error) {
        if([400,401,409].includes(error.status))pendingSaleRequest=null;
        saleError=error.status ? error.message : "Chưa rõ bot đã nhận yêu cầu hay chưa. Bấm Kiểm tra lại yêu cầu; hệ thống giữ cùng mã để tránh bán trùng.";
        $("quick-sale-status").textContent=saleError;
        $("quick-sale-status").classList.add("error");
        toast(error.message,true);
    } finally {saleSubmitting=false;renderSales();renderScope();}
}
function drawChart(id, type, labels, datasets) {
    const canvas = $(id);
    if (!window.Chart) {
        if (!canvas.parentNode.querySelector(".chart-empty")) {
            const empty = document.createElement("p"); empty.className="chart-empty"; empty.textContent="Biểu đồ chưa tải được · điều khiển vẫn hoạt động"; canvas.parentNode.append(empty);
        }
        return;
    }
    canvas.parentNode.querySelector(".chart-empty")?.remove();
    if (charts[id]) charts[id].destroy();
    const circular = type === "doughnut";
    const style = getComputedStyle(document.documentElement);
    const axis = style.getPropertyValue("--chart-axis").trim() || "#51645a";
    const grid = style.getPropertyValue("--chart-grid").trim() || "#dce4dc";
    charts[id] = new Chart(canvas, {type, data:{labels,datasets}, options:{responsive:true,maintainAspectRatio:false,animation:false,cutout:circular?"76%":undefined,
        plugins:{legend:{display:circular || datasets.length>1,position:"bottom",labels:{color:axis,usePointStyle:true,pointStyle:"circle",boxWidth:5,boxHeight:5,padding:13,font:{size:11}}},tooltip:{backgroundColor:"#25342b",titleColor:"#f0f8e8",bodyColor:"#d5e4d5",padding:10}},
        scales:circular?{}:{x:{grid:{display:false},ticks:{color:axis,maxTicksLimit:8,font:{size:11}},border:{display:false}},y:{beginAtZero:true,grid:{color:grid},ticks:{color:axis,maxTicksLimit:5,font:{size:11}},border:{display:false}}}}});
}
async function updateMetrics() {
    if (!authenticated || metricsBusy) return;
    metricsBusy = true;
    try {
        await Promise.allSettled([
            (async () => {
                const {total_cash, total_captchas, data} = await api("/api/fetch_cowoncy_data");
                $("total_cash_card").textContent = number(total_cash);
                $("total_captchas_card").textContent = number(total_captchas);
                drawChart("cowoncy_earnings", "line", data.labels.map((_, i) => `${i}h`),
                    data.datasets.map((dataset, i) => ({
                        ...dataset, borderColor: palette[i % palette.length], backgroundColor: "#28755714",
                        borderWidth: 2, fill: true, pointRadius: 0, tension: .35,
                    })));
            })(),
            (async()=>{ const data=await api("/api/fetch_cmd_data"); $("total_commands_card").textContent=number(data.count.reduce((a,b)=>a+b,0)); drawChart("total_commands","doughnut",data.command_names,[{data:data.count,backgroundColor:data.count.map((_,i)=>palette[i%palette.length]),borderWidth:0,spacing:3}]); })(),
            (async()=>{ const data=await api("/api/fetch_weekly_runtime"); const seconds=Math.max(0,data.current_uptime[1]-data.current_uptime[0]); $("total_uptime_card").textContent=`${String(Math.floor(seconds/3600)).padStart(2,"0")}:${String(Math.floor(seconds/60)%60).padStart(2,"0")}`; drawChart("weekly_runtimes","bar",["T2","T3","T4","T5","T6","T7","CN"],[{label:"Phút hoạt động",data:data.runtime_data.map(n=>Math.max(0,n)),backgroundColor:"#718e5d",hoverBackgroundColor:"#bcf36b",borderRadius:4,maxBarThickness:30}]); })(),
            (async()=>{ const data=await api("/api/fetch_gamble_data"); drawChart("gamble_earnings","line",Array.from({length:24},(_,i)=>`${i}h`),[{label:"Thắng",data:data.win_data,borderColor:palette[0],borderWidth:2,pointRadius:0,tension:.3},{label:"Thua",data:data.lose_data,borderColor:palette[4],borderWidth:2,pointRadius:0,tension:.3}]); })()
        ]);
    } finally { metricsBusy = false; }
}

async function setDashboardRunning(action, account = accountScope) {
    if (!dashboardOnline || busy || switchingScope || !latest) return;
    busy = true;
    stateGeneration++;
    renderState();
    try {
        const state = await api(scopedPath("/api/bot", account), {method: "POST", data: {action}});
        latest = account === accountScope ? state : await api(scopedPath("/api/bot"));
        toast(action === "start" ? "Đã yêu cầu tiếp tục gửi lệnh." : "Đã dừng gửi lệnh tự động.");
    } catch (error) {
        toast(error.message, true);
    } finally {
        busy = false;
        renderState();
    }
}

function acceptSavedSettings(data) {
    accountDrafts.delete(accountScope);
    latest.settings = data.settings;
    latest.overrides = data.overrides;
    loadSettings(data.settings);
    renderState();
}

async function restoreDefaultSettings() {
    if (!accountScope || saving || switchingScope) return;
    if (!window.confirm(`Dùng lại thiết lập mặc định cho ${accountName()}? Các giá trị chỉnh riêng sẽ được bỏ.`)) return;
    saving = true;
    stateGeneration++;
    renderState();
    try {
        acceptSavedSettings(await api(scopedPath("/api/settings"), {method: "DELETE"}));
        toast("Đã dùng lại thiết lập mặc định.");
    } catch (error) {
        toast(error.message, true);
    } finally {
        saving = false;
        renderState();
        renderInputs();
    }
}

document.addEventListener("DOMContentLoaded", () => {
    $("today").textContent = new Intl.DateTimeFormat("vi-VN",{timeZone:"Asia/Ho_Chi_Minh",day:"2-digit",month:"long"}).format(new Date());
    $("settings-form").addEventListener("input",()=>{saveError="";dirty=Object.keys(scopedChanges()).length>0;renderInputs();});
    $("settings-form").addEventListener("submit",async event=>{
        event.preventDefault();if(saving||switchingScope||!dirty)return;
        const invalid = Array.from($("settings-form").elements).find(input=>input.willValidate && !input.checkValidity());
        if (invalid) {
            activatePage(invalid.closest(".tab-page").id.replace("page-",""));
            if (invalid.closest(".game-page")) activateGame(invalid.closest(".game-page").dataset.game);
            invalid.focus(); invalid.reportValidity(); return;
        }
        const changes = scopedChanges();
        saving=true;stateGeneration++;saveError="";$("settings-fields").disabled=true;renderInputs();renderScope();
        try {
            const data = await api(scopedPath("/api/settings"), {method:"PATCH", data:changes});
            acceptSavedSettings(data);
            toast(accountScope ? `Đã lưu thiết lập của ${accountName()}.` : "Đã lưu thiết lập mặc định.");
        }
        catch(error){saveError=error.message;toast(error.message,true);}
        finally{saving=false;$("settings-fields").disabled=!authenticated;renderInputs();renderScope();}
    });
    $("account-scope").addEventListener("change",event=>selectAccountScope(event.target.value));
    $("bot-toggle").addEventListener("click",()=>setDashboardRunning(latest?.running ? "stop" : "start"));
    $("resume-bot").addEventListener("click",()=>setDashboardRunning("start"));
    $("master-toggle").addEventListener("click",()=>setDashboardRunning(latest?.allRunning ? "stop" : "start", ""));
    $("inherit-settings").addEventListener("click", restoreDefaultSettings);
    $("reset-gamble-session").addEventListener("click",resetGambleSession);
    $("risk-bankroll").addEventListener("input",()=>{setPreference(bankrollKey(),$("risk-bankroll").value);renderGambleRisk();});
    $("risk-apply-bet").addEventListener("click",applyBankrollBet);
    $("risk-losses").addEventListener("input",()=>{riskManual=true;renderGambleRisk();});
    $("risk-use-record").addEventListener("click",()=>{riskManual=false;renderGambleRisk();});
    $("gamble-risk-form").addEventListener("submit",event=>event.preventDefault());
    $("log-filter").addEventListener("input",renderLogs);
    $("sell-weapons").addEventListener("click",()=>submitSale("weapons"));
    $("sell-animals").addEventListener("click",()=>submitSale("animals"));
    $("sacrifice-animals").addEventListener("click",()=>submitSale("sacrifice"));
    $("weapon-sale-rarity").addEventListener("change",()=>renderSales());
    $("animal-sale-rarity").addEventListener("change",()=>renderSales());
    $("sacrifice-rarity").addEventListener("change",()=>renderSales());
    $("autoscroll").addEventListener("click",()=>{autoScroll=!autoScroll;$("autoscroll").setAttribute("aria-pressed",String(autoScroll));if(autoScroll)renderLogs();});
    initNavigation();
    $("discard-settings").addEventListener("click",()=>{
        if (!savedSettings) return;
        accountDrafts.delete(accountScope); saveError=""; loadSettings(savedSettings); renderScope();
        toast("Đã hoàn tác các thay đổi chưa lưu.");
    });
    renderInputs();login();
    setInterval(pollCatches,3000);setInterval(poll,3000);setInterval(pollSales,3000);setInterval(renderState,1000);setInterval(updateMetrics,30000);
});

async function pollCatches() {
    if (!authenticated || catchesPolling) return;
    catchesPolling = true;
    try {
        const data = await api("/api/catches");
        $("catch-total").textContent = number(data.total);
        const groups = document.createDocumentFragment();
        for (const group of data.groups) {
            const card = document.createElement("article"); card.className = "catch-rank";
            card.dataset.rank = group.rank;
            const heading = document.createElement("h3"); heading.textContent = group.label;
            const total = document.createElement("strong"); total.textContent = number(group.total);
            heading.append(total); card.append(heading);
            const list = document.createElement("ul");
            for (const animal of group.animals) {
                const row = document.createElement("li");
                const name = document.createElement("span"); name.textContent = animal.name;
                const count = document.createElement("b"); count.textContent = number(animal.count);
                row.classList.toggle("caught", animal.count > 0);
                row.append(name, count); list.append(row);
            }
            card.append(list); groups.append(card);
        }
        $("catch-groups").replaceChildren(groups);
        $("catch-status").textContent = "Tự cập nhật mỗi 3 giây · Tổng trên các tài khoản · Không tính ngược thú trong zoo trước đây.";
    } catch (error) {
        $("catch-status").textContent = "Chưa tải được thống kê. Đang giữ dữ liệu gần nhất và sẽ thử lại.";
    } finally { catchesPolling = false; }
}

const PAGES = {
    overview:["Tổng quan","Theo dõi"],
    activity:["Nhật ký hoạt động","Theo dõi","Sự kiện từ mọi tài khoản"],
    controls:["Tự động hóa","Điều khiển"],
    gambling:["Cá cược","Điều khiển"],
    simulation:["Mô phỏng cược","Điều khiển"],
    inventory:["Kho và giao dịch","Quản lý"],
    collection:["Bộ sưu tập thú","Quản lý","Số liệu cộng dồn từ mọi tài khoản"],
    accounts:["Tài khoản Discord","Quản lý"]
};
let activePage = "overview", activeGame = "coinflip";
function settingsArea(key) {
    if (key === "huntEmergencySellEnabled" || key === "zooSacrificeSurplusEnabled") return "inventory";
    return /^(coinflip|slots|blackjack|gambleGoal|gambleLoss)/.test(key) ? "gambling" : "controls";
}
function updateSaveBar(config = formValues()) {
    const changes = savedSettings ? Object.keys(scopedChanges(config)) : [];
    for (const page of ["controls","gambling","inventory"]) {
        $("tab-"+page).querySelector(".tab-dirty").hidden = !changes.some(key=>settingsArea(key)===page);
    }
    const hasOverrides = accountScope && Object.keys(latest?.overrides || {}).some(key => key !== "channelId");
    $("settings-savebar").hidden = !["controls","gambling","inventory"].includes(activePage) && !dirty;
    $("inherit-settings").hidden = !hasOverrides;
    $("inherit-settings").disabled = saving || switchingScope;
    $("discard-settings").disabled = !dirty || saving || !authenticated;
    $("save-context").textContent = accountScope ? `Thiết lập của ${accountName()}` : "Thiết lập mặc định";
}
function activatePage(page, updateHash = true) {
    if (!PAGES[page]) page="overview";
    if (activePage === "accounts" && page !== "accounts") closeAccountEditor();
    activePage=page;
    for (const key of Object.keys(PAGES)) {
        $("page-"+key).hidden=key!==page;
        $("tab-"+key).setAttribute("aria-selected",String(key===page));
        $("tab-"+key).tabIndex=key===page?0:-1;
        $("tab-"+key).classList.toggle("active",key===page);
    }
    $("page-title").textContent=PAGES[page][0];
    $("page-eyebrow").textContent=PAGES[page][1];
    $("page-description").textContent=PAGES[page][2] || "";
    $("page-description").hidden=!PAGES[page][2];
    $("activity-shortcut").hidden=page!=="overview";
    $("header-status").hidden=page==="overview";
    document.title=`${PAGES[page][0]} · Dusk`;
    setPreference("dusk-tab",page);
    if(updateHash && location.hash!=="#"+page) history.pushState(null,"","#"+page);
    updateSaveBar();
    window.scrollTo({top:0,behavior:"instant"});
    requestAnimationFrame(()=>Object.values(charts).forEach(chart=>chart.resize()));
}
function activateGame(game) {
    activeGame=game;
    for(const key of ["coinflip","slots","blackjack"]) {
        $("game-"+key).hidden=key!==game;
        $("game-tab-"+key).setAttribute("aria-selected",String(key===game));
        $("game-tab-"+key).tabIndex=key===game?0:-1;
    }
    renderGambleRisk();
}
function routeFromHash() {
    const aliases={"gambling-controls":"gambling","rare-catches":"collection","quick-sales":"inventory"};
    const key=location.hash.slice(1);
    const page=aliases[key] || key || getPreference("dusk-tab") || "overview";
    if(aliases[key]) history.replaceState(null,"","#"+page);
    activatePage(page,false);
}
function wireTabs(selector, activate, attribute) {
    const tabs=Array.from(document.querySelectorAll(selector));
    tabs.forEach((tab,index)=>{
        tab.addEventListener("click",()=>activate(tab.dataset[attribute]));
        tab.addEventListener("keydown",event=>{
            let next;
            if(["ArrowRight","ArrowDown"].includes(event.key)) next=(index+1)%tabs.length;
            if(["ArrowLeft","ArrowUp"].includes(event.key)) next=(index+tabs.length-1)%tabs.length;
            if(event.key==="Home") next=0;
            if(event.key==="End") next=tabs.length-1;
            if(next!==undefined) {event.preventDefault();activate(tabs[next].dataset[attribute]);tabs[next].focus();}
        });
    });
}
function initNavigation() {
    wireTabs("[data-page]",activatePage,"page");
    wireTabs("[data-game-tab]",activateGame,"gameTab");
    window.addEventListener("hashchange",routeFromHash);
    window.addEventListener("popstate",routeFromHash);
    document.querySelector(".gamble-history").addEventListener("toggle",()=>Object.values(charts).forEach(chart=>chart.resize()));
    routeFromHash();activateGame("coinflip");
}

function renderGambleSession(accounts) {
    if (typeof renderSimulationAccounts === "function") renderSimulationAccounts();
    const account = accountScope && accounts.find(item => item.accountId === accountScope && item.connected);
    const foreignPending = pendingReset && pendingReset.accountId !== accountScope;
    const resetButton = $("reset-gamble-session");
    resetButton.disabled = !authenticated || resetBusy || !account || Boolean(foreignPending);
    resetButton.textContent = resetBusy ? "Đang đặt lại…" : pendingReset && !foreignPending ? "Kiểm tra yêu cầu" : "Đặt lại phiên";
    if (foreignPending) $("reset-session-status").textContent = `Chuyển về ${accountName(pendingReset.accountId)} để kiểm tra yêu cầu đặt lại.`;
    const fragment = document.createDocumentFragment();
    if (account) {
        for (const [game, label] of Object.entries(gameLabels)) {
            const data = account.gambleStreaks?.[game];
            const row = document.createElement("tr");
            const title = document.createElement("th");
            title.scope = "row";
            title.textContent = label;
            const current = document.createElement("td");
            current.textContent = number(data?.current);
            const best = document.createElement("td");
            best.textContent = number(data?.best);
            row.append(title, current, best);
            fragment.append(row);
        }
    } else {
        const row = document.createElement("tr");
        const empty = document.createElement("td");
        empty.colSpan = 3;
        empty.className = "hint";
        empty.textContent = accountScope ? "Tài khoản chưa kết nối." : "Chọn tài khoản để xem chuỗi thua.";
        row.append(empty);
        fragment.append(row);
    }
    $("gamble-streaks").replaceChildren(fragment);
    renderGambleRisk();
}
async function resetGambleSession() {
    if(resetBusy || !authenticated || !runtimeFor()?.connected || (pendingReset && pendingReset.accountId !== accountScope)) return;
    const data=pendingReset || {accountId:accountScope,requestId:crypto.randomUUID()};
    pendingReset=data;resetBusy=true;renderState();
    try {
        const result=await api("/api/gamble/reset",{method:"POST",data});
        const account=latest?.accounts.find(a=>a.accountId===data.accountId);
        if(account) {account.gambleProfit=0;account.gambleLossStopped=false;account.gambleStreaks=result.streaks;}
        pendingReset=null;
        $("reset-session-status").textContent="Đã đặt lại lãi/lỗ và chuỗi thua hiện tại.";
        toast("Đã bắt đầu phiên lãi/lỗ mới.");
        renderState();
    } catch(error) {
        if([400,401].includes(error.status)) pendingReset=null;
        $("reset-session-status").textContent=error.message;
        toast(error.message,true);
    } finally {
        resetBusy=false;renderState();
    }
}

function renderGambleRisk() {
    if(!window.GambleMath || !$("risk-losses")) return;
    renderCoinflipSide();
    const game=activeGame;
    const label=gambleLabel(game);
    const account=runtimeFor();
    const hasRecord=Boolean(account?.accountId);
    const best=account?.gambleStreaks?.[game]?.best || 0;
    $("risk-use-record").disabled=!hasRecord;
    if(!riskManual) $("risk-losses").value=Math.min(60,best);
    const n=Number($("risk-losses").value),base=Number($(game+"-bet").value);
    const doubling=$(game+"-double").checked;
    const bonus=game==="coinflip" && doubling && $("coinflip-bonus").checked;
    const budget=$("gamble-loss-enabled").checked?Number($("gamble-loss-amount").value):null;
    renderBankrollBet(game,n,doubling,budget,bonus);
    $("risk-heading").textContent=`Vốn cho chuỗi thua · ${label}`;
    $("risk-source").textContent=!hasRecord?"Chưa tải được kỷ lục tài khoản. Nhập số lần thua để mô phỏng.":`${account?.name || "Tài khoản"} · Kỷ lục ${number(best)} lần · ${riskManual?"Đang xem giả lập":"Đang dùng kỷ lục"}${best>60 && !riskManual?" (xem tối đa 60 lượt)":""}`;
    try {
        if($("risk-losses").value==="") throw new Error("Nhập số lần thua từ 0 đến 60.");
        const data=GambleMath.project(base,doubling,n,budget,bonus);
        $("risk-error").textContent="";$("risk-results").hidden=false;
        $("risk-total").textContent=number(data.total);
        $("risk-next").textContent=number(data.next);
        $("risk-capital").textContent=number(data.capital);
        $("risk-budget").textContent=budget===null
            ? "Bật giới hạn lỗ để tính mức cược khởi đầu phù hợp với phần vốn đó."
            : `Với vốn ${number(budget)} cowoncy, cược khởi đầu tối đa ${number(data.maxBase)} để đủ ${n} lần thua và còn cược lượt ${n+1}.${data.maxBase===0n?" Vốn chưa đủ cho mức tối thiểu 1 cowoncy.":""}`;
        const warnings=[];
        if(data.firstBlocked) warnings.push(`Theo giới hạn lỗ và trần cược 250.000, mô phỏng có lượt đầu bị chặn là lượt ${data.firstBlocked}.`);
        else if(data.nextAboveCap || data.nextAboveBudget) warnings.push(`Lượt tiếp theo (${n+1}) sẽ vượt ${data.nextAboveCap?"trần cược 250.000":"phần vốn giới hạn lỗ"}.`);
        $("risk-warning").hidden=!warnings.length;$("risk-warning").textContent=warnings.join(" ");
        const rows=data.rows.length>12?[...data.rows.slice(0,11),data.rows[data.rows.length-1]]:data.rows;
        const fragment=document.createDocumentFragment();
        for(const row of rows) {
            const tr=document.createElement("tr");tr.classList.toggle("risk-blocked",row.aboveCap || row.aboveBudget);
            for(const value of [row.round,row.stake,row.total]) {const td=document.createElement("td");td.textContent=number(value);tr.append(td);}
            fragment.append(tr);
        }
        $("risk-rows").replaceChildren(fragment);
        $("risk-row-note").textContent=n===0?"Chưa thua lượt nào: tổng mất bằng 0.":n>12?`Hiện 11 lượt đầu và lượt ${n}; tổng vẫn tính đủ ${n} lượt.`:"Đơn vị: cowoncy. Dòng màu cam vượt giới hạn mô phỏng.";
        $("risk-formula").textContent=bonus
            ? "Nhân cược trước với 2,00 → 2,10 → 2,20 → 2,30… Làm tròn xuống sau mỗi lượt."
            : doubling
            ? `Cược lượt k = ${number(base)} × 2^(k−1). Tổng thua N lượt = ${number(base)} × (2^N−1).`
            : `Cược cố định ${number(base)} mỗi lượt. Tổng thua N lượt = ${number(base)} × N.`;
    } catch(error) {
        $("risk-error").textContent=error.message;$("risk-results").hidden=true;
    }
}

function bankrollRecommendation() {
    const n=Number($("risk-losses").value);
    if($("risk-bankroll").value==="" || $("risk-losses").value==="") return null;
    const limit=$("gamble-loss-enabled").checked?Number($("gamble-loss-amount").value):null;
    const doubling=$(activeGame+"-double").checked;
    const bonus=activeGame==="coinflip" && doubling && $("coinflip-bonus").checked;
    return GambleMath.recommend(Number($("risk-bankroll").value),doubling,n,limit,bonus);
}
function renderBankrollBet(game,n,doubling,limit,bonus) {
    $("risk-apply-bet").disabled=true;
    $("bankroll-result").hidden=true;
    $("bankroll-error").textContent="";
    if($("risk-bankroll").value==="") return;
    try {
        const result=bankrollRecommendation();
        if(!result) return;
        $("bankroll-result").hidden=false;
        $("bankroll-bet").textContent=number(result.base);
        $("bankroll-game").textContent=gambleLabel(game)+` · ${n} lần thua`;
        $("risk-apply-bet").disabled=!authenticated || saving || result.base<1n;
        $("bankroll-proof").textContent=result.calculation
            ? `Nếu cược đầu ${number(result.base)}: thua ${n} lần mất ${number(result.calculation.total)}, cược tiếp ${number(result.calculation.next)}; tổng vốn cần ${number(result.calculation.capital)}. Còn dư ${number(result.leftover)} cowoncy từ vốn đã nhập.`
            : result.capImpossible?"Không có mức cược hợp lệ: ngay cả mức đầu 1 cowoncy cũng khiến lượt tiếp vượt trần 250.000."
            : `Vốn tính toán chưa đủ. Cần ít nhất ${number(result.minimumCapital)} cowoncy cho mức đầu 1 và lượt tiếp theo.`;
        const rule = bonus
            ? "Chọn mức cược đầu cao nhất đủ vốn theo hệ số tăng dần và mức cược đã làm tròn từng lượt."
            : doubling ? "Chia vốn cho 2^(N+1)−1 và làm tròn xuống."
            : "Chia vốn cho N+1 và làm tròn xuống.";
        const budget = limit===null ? "" : ` Vốn dùng cho chuỗi mới tối đa ${number(result.usable)} theo số dư và giới hạn lỗ.`;
        $("bankroll-constraints").textContent=`Đã tính trần 250.000 mỗi lượt.${budget} ${rule}`;
    } catch(error) {$("bankroll-error").textContent=error.message;}
}
function applyBankrollBet() {
    try {
        const result=bankrollRecommendation();
        if(!result || result.base<1n || !authenticated || saving) return;
        $(activeGame+"-bet").value=String(result.base);
        $(activeGame+"-bet").dispatchEvent(new Event("input",{bubbles:true}));
        toast(`Đã điền ${number(result.base)}. Bấm Lưu thay đổi để áp dụng.`);
    } catch(error) {toast(error.message,true);}
}
