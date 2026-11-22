"use strict";
const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat("vi-VN").format(value || 0);
localStorage.removeItem("password");
let authenticated = false, busy = false, saving = false, dirty = false;
let saveError = "";
let latest = null, savedSettings = null, logs = [], autoScroll = true, pollBusy = false, metricsBusy = false;
const charts = {};
let saleData = {accounts:[],jobs:[]}, saleSubmitting = false, salesPolling = false;
let pendingSaleRequest = null, lastSaleId = null;
let saleError = "";
let catchesPolling = false;
let resetBusy=false, pendingReset=null, resetAccountsKey="";
let riskManual=false;
const palette = ["#bcf36b", "#6ed6c8", "#809ce8", "#e5bb78", "#b493d6", "#e69383", "#779d85"];

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
        gemOrder:$("gem-order").value, gambleGoalEnabled:$("gamble-goal-enabled").checked,
        gambleGoalAmount:Number($("gamble-goal-amount").value),
        gambleLossEnabled:$("gamble-loss-enabled").checked, gambleLossAmount:Number($("gamble-loss-amount").value), coinflipEnabled:$("coinflip-enabled").checked,
        slotsEnabled:$("slots-enabled").checked, blackjackEnabled:$("blackjack-enabled").checked,
        coinflipSide:$("coinflip-side").value,
        coinflipProbeTarget:$("coinflip-probe-target").value,
        coinflipSwitchStart:$("coinflip-switch-start").value,
        coinflipHistoryWindow:Number($("coinflip-history-window").value),
        ...Object.fromEntries(["coinflip","slots","blackjack"].flatMap(game=>[[game+"Bet",Number($(game+"-bet").value)],[game+"DoubleOnLoss",$(game+"-double").checked]])) };
}
function gambleLabel(game) {
    if(game === "coinflip" && $("coinflip-side").value === "win_switch") return "Coinflip · Thắng đổi, thua giữ";
    if(game === "coinflip" && $("coinflip-side").value === "probe_loss") return "Coinflip · Thử đến khi thua → "+($("coinflip-probe-target").value==="heads"?"Heads":"Tails");
    if(game === "coinflip" && $("coinflip-side").value === "probe") return "Coinflip · Thử 1 + chọn/đảo ngẫu nhiên";
    return game === "coinflip"
        ? `Coinflip · ${$("coinflip-side").value === "auto" ? "Tự chọn "+$("coinflip-history-window").value+" → " : ""}${coinflipSelectedSide() === "tails" ? "Tails" : "Heads"}`
        : {slots:"Slots",blackjack:"Blackjack"}[game];
}
function coinflipHistoryState() {
    const accounts=latest?.accounts || [];
    const account=accounts.find(a=>a.accountId===$("reset-session-account").value) || accounts[0];
    return account?.coinflipAuto;
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
        :`Đã ghi ${total}/${windowSize} ván · ${data.mostCommon?(data.mostCommon === "heads" ? "Heads" : "Tails")+" xuất hiện nhiều hơn.":"Hai mặt bằng nhau."}`;
}
function renderCoinflipSide() {
    const mode=$("coinflip-side").value, data=coinflipAutoState(), history=coinflipHistoryState();
    renderCoinflipFrequency(history?.windows?.["500"] || history,"coinflip-",500);
    renderCoinflipFrequency(history?.windows?.["100"],"coinflip-recent-",100);
    $("coinflip-frequency-note").textContent="Hai biểu đồ dùng cùng lịch sử thực tế: 100 ván gần nhất nằm trong mẫu 500 ván. Chưa đủ mẫu thì dùng số ván hiện có; dữ liệu giữ qua khởi động lại. Khi tự chọn, bạn có thể chọn mẫu 100 hoặc 500 bên dưới rồi lưu. Tần suất quá khứ không dự đoán kết quả lượt sau.";
    $("coinflip-side-preview").textContent=`Lệnh cược ban đầu: ${$("command-prefix").value}cf ${$("coinflip-bet").value} ${coinflipSelectedSide()}. Áp dụng sau khi lưu; ván đã gửi giữ lựa chọn cũ.`;
    $("coinflip-auto-status").hidden=mode!=="auto";
    $("coinflip-history-field").hidden=mode!=="auto";
    $("coinflip-probe-status").hidden=!["probe","probe_loss","win_switch"].includes(mode);
    $("coinflip-switch-field").hidden=mode!=="win_switch";
    if(mode==="win_switch") {
        $("coinflip-probe-status").textContent=`Mặt tiếp theo: ${coinflipSelectedSide()==="heads"?"Ngửa (Heads)":"Sấp (Tails)"}. Ngửa thắng → Sấp; Ngửa thua → Ngửa. Sấp thắng → Ngửa; Sấp thua → Sấp. Mỗi lượt dùng mức cược chính; không cược thử 1, không chọn ngẫu nhiên. Công tắc nhân đôi khi thua vẫn áp dụng riêng cho số tiền. Đổi mặt khởi đầu hoặc khởi động lại sẽ bắt đầu từ mặt đó; ván đã gửi vẫn hoàn tất.`;
    }
    $("coinflip-probe-target-field").hidden=mode!=="probe_loss";
    $("risk-probe-note").hidden=!["probe","probe_loss"].includes(mode) || activeGame!=="coinflip";
    if(mode==="probe_loss") {
        const target=$("coinflip-probe-target").value==="heads"?"Ngửa (Heads)":"Sấp (Tails)";
        const trial=target;
        const plan=coinflipLossProbePlan();
        $("coinflip-probe-status").textContent=`${plan.phase==="wager"?"Lượt thử đã thua; tiếp theo là cược chính "+target+".":"Đang cược thử "+trial+" 1 cowoncy."} Thử thắng: tiếp tục thử ${trial} 1. Thử thua: cược chính ${target} bằng mức đã đặt. Sau lượt chính quay lại vòng thử. Chỉ lượt chính áp dụng gấp đôi khi thua; thử thắng không reset mức cược chính. Tiền thử vẫn tính vào lãi/lỗ. Đổi mặt chính sẽ bắt đầu vòng thử mới; ván đã gửi vẫn hoàn tất. Cách này không bảo đảm tăng tỷ lệ thắng.`;
        $("coinflip-side-preview").textContent=`Thử ${trial} 1 → đến khi thua → cược chính ${target}. Mức chính ban đầu: ${$("coinflip-bet").value}. Áp dụng sau khi lưu.`;
    }
    if(mode==="probe") {
        const plan=history?.probePlan;
        $("coinflip-probe-status").textContent=`${plan?.phase==="wager"?"Đã cược thử; lượt chính sẽ chọn "+(plan.side==="heads"?"Heads":"Tails")+".":"Lượt tiếp là cược thử 1 cowoncy vào Heads."} Sau cược thử, chọn ngẫu nhiên nội bộ tương đương ochoose; thử thắng thì đảo mặt ngẫu nhiên, thử thua thì giữ. Sau lượt chính lại cược thử 1. Chỉ lượt chính tăng tiền khi thua và reset khi thắng; cược thử vẫn tính vào lãi/lỗ và thống kê. Không có bằng chứng thắng 80%. Khoảng chờ và giới hạn vốn vẫn áp dụng. Khởi động lại bắt đầu một lượt thử mới.`;
        $("coinflip-side-preview").textContent="Mẹo cược thử 1 · Mức cược chính ban đầu: "+$("coinflip-bet").value+" cowoncy. Áp dụng sau khi lưu; không gửi lệnh ochoose riêng.";
    }
    if(mode!=="auto") return;
    $("coinflip-auto-status").textContent=!data
        ? "Đang chờ lịch sử tài khoản; nếu chưa có dữ liệu sẽ bắt đầu bằng Heads."
        : `Mặt tự chọn: ${data.side === "heads" ? "Heads" : "Tails"} · ${data.reason === "locked" ? "Giữ mặt của ván thua trước; chỉ chọn lại sau khi thắng." : data.reason === "sampling" ? "Đầu chuỗi: lấy mẫu mặt ít ván hơn cho đến khi mỗi mặt đủ 5 ván." : "Đầu chuỗi: so tỷ lệ thắng làm trơn (thắng + 1) / (số ván + 2); bằng nhau ưu tiên mặt ít ván hơn."} Heads: ${data.sides.heads.wins} thắng / ${data.sides.heads.losses} thua; Tails: ${data.sides.tails.wins} thắng / ${data.sides.tails.losses} thua. Dùng ${data.total}/${data.window} ván gần nhất, lưu riêng từng tài khoản qua khởi động lại. Giữ mặt qua chuỗi thua; chọn Heads/Tails cố định vẫn cho phép đổi thủ công. Lịch sử không phải xác suất thắng lượt sau; không tăng thêm cược ở lượt sau kỷ lục.`;
}
function renderInputs() {
    const config = formValues();
    $("threshold-value").textContent = `${config.failureThreshold} lần`;
    $("rest-value").textContent = `${config.restMinutes} phút`;
    $("timeout-value").textContent = `${config.responseTimeout} giây`;
    $("interval-value").textContent = String(config.messageInterval).replace(".", ",");
    $("prefix-length").textContent = `${config.prefix.length} ký tự (tính cả dấu cách)`;
    $("prefix-preview").textContent = config.prefix + "h";
    $("hunt-command-preview").textContent=config.prefix+"h";
    $("battle-command-preview").textContent=config.prefix+"b";
    $("gem-order-hint").textContent = config.gemOrder === "high_to_low"
        ? "Fabled → Legendary → Mythical → Epic → Rare → Uncommon → Common"
        : "Common → Uncommon → Rare → Epic → Mythical → Legendary → Fabled";
    $("guard-summary").textContent = config.restEnabled
        ? `${config.failureThreshold} lần không trả lời → nghỉ ${config.restMinutes} phút`
        : "Đã tắt chế độ nghỉ khi mất phản hồi.";
    for (const id of ["failure-threshold", "rest-minutes", "response-timeout"]) $(id).disabled = !config.restEnabled;
    document.querySelectorAll('input[type="range"]').forEach(input => {
        const fill = 100 * (Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min));
        input.style.setProperty("--fill", `${fill}%`);
    });
    for (const game of ["coinflip", "slots", "blackjack"]) {
        const amount = config[game+"Bet"];
        $(game+"-bet-preview").textContent = !Number.isInteger(amount) || amount < 1 || amount > 250000
            ? "Nhập số nguyên từ 1 đến 250.000."
            : config[game+"DoubleOnLoss"] ? `${number(amount)} → ${number(amount*2)} → ${number(amount*4)}… · Thắng: về ${number(amount)}`
            : `Cược cố định ${number(amount)} mỗi lượt, kể cả khi thua.`;
    }
    $("gamble-loss-amount").disabled = !config.gambleLossEnabled;
    $("gamble-loss-preview").textContent = config.gambleLossEnabled
        ? `Dừng khi lỗ ròng đạt ${number(config.gambleLossAmount)} cowoncy; lượt cược mới cũng phải nằm trong phần giới hạn còn lại.`
        : "Đã tắt giới hạn lỗ. Các giới hạn tiền cược và số dư vẫn áp dụng.";
    $("gamble-goal-amount").disabled = !config.gambleGoalEnabled;
    $("gamble-goal-preview").textContent = config.gambleGoalEnabled
        ? `Dừng khi lãi đạt ${number(config.gambleGoalAmount)} cowoncy.`
        : "Không dừng theo mục tiêu lợi nhuận. Giới hạn vốn cược hiện có vẫn áp dụng.";
    renderGambleRisk();
    updateSaveBar(config);
    $("save-settings").disabled = !authenticated || !dirty || saving;
    $("save-status").textContent = saving ? "Đang lưu…" : saveError || (dirty ? "Có thay đổi chưa lưu" : "Đã lưu cấu hình");
    $("save-status").classList.toggle("error", Boolean(saveError));
}
function loadSettings(config) {
    savedSettings = config;
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
    $("coinflip-side").value = config.coinflipSide || "heads";
    $("coinflip-probe-target").value = config.coinflipProbeTarget || "heads";
    $("coinflip-switch-start").value = config.coinflipSwitchStart || "heads";
    $("coinflip-history-window").value = config.coinflipHistoryWindow || 500;
    dirty = false; renderInputs();
}
function formatTime(seconds) {
    seconds = Math.max(0, Math.ceil(seconds));
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
function renderState() {
    if (!latest) return;
    const config = latest.settings;
    const accounts = latest.accounts || [];
    const connected=accounts.some(account=>account.accountId);
    renderGambleSession(accounts);
    $("gamble-loss-status").textContent = accounts.map(account=>{
        const loss=Math.max(0,-(account.gambleProfit || 0));
        const stopped=latest.settings.gambleLossEnabled && (account.gambleLossStopped || loss>=latest.settings.gambleLossAmount);
        return `${account.name}: lỗ ròng ${number(loss)} cowoncy${stopped?" · Đã chạm giới hạn, chờ bạn điều chỉnh":""}`;
    }).join(" · ") || "Đang đọc lỗ trong phiên…";
    $("gamble-profit-status").textContent = accounts.map(account=>{
        const profit=account.gambleProfit || 0;
        const reached=latest.settings.gambleGoalEnabled && profit>=latest.settings.gambleGoalAmount;
        return `${account.name}: ${profit>=0?"+":""}${number(profit)} cowoncy${reached?" · Đã đạt mục tiêu, chờ bạn điều chỉnh":" · Lãi trong phiên"}`;
    }).join(" · ") || "Đang đọc lợi nhuận trong phiên…";
    const now = Date.now() / 1000;
    const resting = accounts.filter(a => a.restUntil > now).sort((a,b) => b.restUntil - a.restUntil)[0];
    const captcha = accounts.some(a => a.captchaBlocked);
    const sleeping = accounts.some(a => a.scheduledSleep);
    const resuming = latest.running && accounts.some(a => a.resumeGeneration < latest.resumeRequest);
    const misses = Math.max(0, ...accounts.map(a => a.misses));
    const channelError = accounts.find(a => a.channelError)?.channelError;
    const channel = accounts[0]?.channelId;
    $("channel-state").textContent = channelError || (channel ? `Kênh đang dùng: ${channel}. Bỏ trống để dùng kênh ban đầu.` : "Bỏ trống để dùng kênh ban đầu.");
    $("channel-state").classList.toggle("error", Boolean(channelError));
    if (channel) $("channel-id").placeholder = channel;
    $("account-name").textContent = accounts.map(a => a.name).join(" · ") || "Đang kết nối tài khoản…";
    $("bot-toggle").textContent = latest.running ? "Dừng bot" : "Chạy bot";
    $("bot-toggle").dataset.running = String(latest.running);
    $("bot-toggle").disabled = busy || resuming;
    $("resume-bot").hidden = !latest.running || !(captcha || resting || resuming);
    $("resume-bot").disabled = busy || resuming;
    $("resume-bot").textContent = resuming ? "Đang tiếp tục…" : captcha ? "Đã xác minh · Tiếp tục" : "Tiếp tục ngay";
    const status = !latest.running ? "Đã dừng tự động" : !connected ? "Chưa kết nối Discord" : resuming ? "Đang tiếp tục…" : captcha ? "Đang chờ CAPTCHA" : resting && config.restEnabled ? "Đang nghỉ" : sleeping ? "Đang nghỉ theo lịch" : "Đang chạy";
    $("bot-status").textContent = status;
    $("header-status").textContent = status;
    $("header-status").classList.toggle("attention", !connected || captcha || Boolean(resting) || !latest.running);
    $("status-dot").classList.toggle("paused", !connected || !latest.running || Boolean(resting) || captcha || sleeping);
    $("status-detail").textContent = !latest.running ? "Không gửi lệnh tự động. Web vẫn sẵn sàng để chạy lại."
        : !connected ? "Dashboard đang mở. Chưa có tài khoản Discord đăng nhập thành công."
        : resuming ? "Đang xoá trạng thái chờ cũ theo yêu cầu trên web."
        : captcha ? "Sau khi tự xác minh, bấm Đã xác minh · Tiếp tục. CAPTCHA mới vẫn sẽ làm bot dừng lại."
        : resting && config.restEnabled ? "OwO chưa phản hồi. Bot sẽ thử lại khi hết thời gian nghỉ."
        : `Khoảng cách tối thiểu ${config.messageInterval} giây · vẫn tuân theo CAPTCHA và lịch nghỉ.`;
    $("rest-caption").textContent = resting && config.restEnabled ? "THỜI GIAN NGHỈ CÒN LẠI" : "BẢO VỆ KHI MẤT PHẢN HỒI";
    const timer = $("rest-timer"); timer.replaceChildren();
    if (!config.restEnabled) {
        timer.textContent = "Đã tắt";
    } else if (resting) {
        timer.textContent = formatTime(resting.restUntil - now);
    } else {
        timer.append(document.createTextNode(String(config.failureThreshold).padStart(2,"0") + " "));
        const times = document.createElement("span"); times.textContent = "lần";
        const arrow = document.createElement("i"); arrow.textContent = "→";
        const minutes = document.createElement("span"); minutes.textContent = "phút";
        timer.append(times, arrow, document.createTextNode(config.restMinutes + " "), minutes);
    }
    $("rest-progress").style.width = `${!config.restEnabled ? 0 : resting ? Math.max(0,Math.min(100,100*(resting.restUntil-now)/(config.restMinutes*60))) : Math.min(100,100*misses/config.failureThreshold)}%`;
    $("misses-caption").textContent = !config.restEnabled ? "Không tự nghỉ khi OwO không phản hồi."
        : `${misses}/${config.failureThreshold} lần chưa phản hồi${accounts.some(a=>a.waitingForReply) ? " · đang chờ trả lời" : " · tự thử lại sau khi nghỉ"}`;
}
async function login() {
    try {
        const state = await api("/api/bot");
        authenticated = true;
        $("settings-fields").disabled = false;
        latest = state; loadSettings(state.settings); renderState();
        $("connection").textContent = "Web đã kết nối"; $("connection").classList.remove("offline");
        await Promise.allSettled([poll(), updateMetrics(), pollSales(), pollCatches(), loadAccountCredentials()]);
    } catch (error) {
        toast(error.message, true);
    }
}
async function poll() {
    if (!authenticated) { await login(); return; }
    if (pollBusy || busy) return;
    pollBusy = true;
    try {
        const state = await api("/api/bot");
        if (!busy) {
            latest = state;
            if (!dirty && !saving) loadSettings(state.settings);
            renderState();
        }
        $("connection").textContent = "Web đã kết nối"; $("connection").classList.remove("offline");
        const html = await api("/api/console", {text:true});
        const parsed = new DOMParser().parseFromString(html, "text/html");
        logs = Array.from(parsed.body.children).map(node => node.textContent.trim());
        if (!logs.length && parsed.body.textContent.trim()) logs = parsed.body.textContent.trim().split("\n");
        renderLogs();
    } catch (error) {
        $("connection").textContent = "Mất kết nối"; $("connection").classList.add("offline");
        $("bot-toggle").disabled = true;
    } finally { pollBusy = false; }
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
    const accountId=$("sale-account").value;
    const active=saleData.jobs.find(job=>job.accountId===accountId && ["queued","running"].includes(job.state));
    const blocked=!authenticated || !accountId || latest?.accounts?.some(a=>a.captchaBlocked || a.scheduledSleep || a.restUntil>Date.now()/1000);
    for(const [kind,buttonId,selectId] of [["weapons","sell-weapons","weapon-sale-rarity"],["animals","sell-animals","animal-sale-rarity"],["sacrifice","sacrifice-animals","sacrifice-rarity"]]) {
        const button=$(buttonId);
        button.disabled=Boolean(blocked || saleSubmitting || active || (pendingSaleRequest && pendingSaleRequest.kind!==kind));
        button.textContent=saleSubmitting || active?.kind===kind ? "Đang xử lý…" : pendingSaleRequest?.kind===kind ? "Kiểm tra lại yêu cầu" : kind==="weapons" ? "Bán vũ khí ngay ↗" : kind==="sacrifice" ? "Hiến tế thú ngay ↗" : "Bán thú ngay ↗";
        $(selectId).disabled=Boolean(saleSubmitting || active || pendingSaleRequest);
    }
    $("sale-account").disabled=Boolean(saleSubmitting || active || pendingSaleRequest);
    const job=saleData.jobs.find(item=>item.id===lastSaleId) || saleData.jobs.filter(item=>item.accountId===accountId).at(-1);
    if(saleError) {
        $("quick-sale-status").textContent=saleError;$("quick-sale-status").classList.add("error");
    } else if(job) {
        $("quick-sale-status").textContent=`${job.accountName} · ${job.kind==="weapons"?"Bán vũ khí":job.kind==="sacrifice"?"Hiến tế thú":"Bán thú"} (${job.maxRarity} trở xuống): ${job.message}`;
        $("quick-sale-status").classList.toggle("error",["failed","partial","cancelled"].includes(job.state));
    } else {
        $("quick-sale-status").textContent=blocked
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
        const select=$("sale-account"), selected=select.value;
        const signature=JSON.stringify(saleData.accounts);
        if(select.dataset.accounts!==signature) {
            select.replaceChildren(...saleData.accounts.map(account=>{const option=document.createElement("option");option.value=account.id;option.textContent=account.name;return option;}));
            if(saleData.accounts.some(account=>account.id===selected))select.value=selected;
            select.dataset.accounts=signature;
        }
        $("sale-account-field").hidden=saleData.accounts.length<2;
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
    if(saleSubmitting || (pendingSaleRequest && pendingSaleRequest.kind!==kind))return;
    const data=pendingSaleRequest || {kind,maxRarity:$(kind==="weapons"?"weapon-sale-rarity":kind==="sacrifice"?"sacrifice-rarity":"animal-sale-rarity").value,accountId:$("sale-account").value,requestId:crypto.randomUUID()};
    pendingSaleRequest=data;saleSubmitting=true;saleError="";renderSales();
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
    } finally {saleSubmitting=false;renderSales();}
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
    charts[id] = new Chart(canvas, {type, data:{labels,datasets}, options:{responsive:true,maintainAspectRatio:false,animation:false,cutout:circular?"76%":undefined,
        plugins:{legend:{display:circular || datasets.length>1,position:"bottom",labels:{color:"#9aaea2",usePointStyle:true,pointStyle:"circle",boxWidth:5,boxHeight:5,padding:13,font:{size:9}}},tooltip:{backgroundColor:"#25342b",titleColor:"#d9edcf",bodyColor:"#bdd2be",padding:10}},
        scales:circular?{}:{x:{grid:{display:false},ticks:{color:"#6d8776",maxTicksLimit:8,font:{size:9}},border:{display:false}},y:{beginAtZero:true,grid:{color:"#2a3730"},ticks:{color:"#6d8776",maxTicksLimit:5,font:{size:9}},border:{display:false}}}}});
}
async function updateMetrics() {
    if (!authenticated || metricsBusy) return;
    metricsBusy = true;
    try {
        await Promise.allSettled([
            (async()=>{ const data=await api("/api/fetch_cowoncy_data"); $("total_cash_card").textContent=number(data.total_cash); $("total_captchas_card").textContent=number(data.total_captchas); drawChart("cowoncy_earnings","line",data.data.labels,data.data.datasets.map((item,i)=>({...item,label:`Tài khoản ${i+1}`,borderColor:palette[i%palette.length],backgroundColor:"#bcf36b0c",borderWidth:2,fill:true,pointRadius:0,tension:.35}))); })(),
            (async()=>{ const data=await api("/api/fetch_cmd_data"); $("total_commands_card").textContent=number(data.count.reduce((a,b)=>a+b,0)); drawChart("total_commands","doughnut",data.command_names,[{data:data.count,backgroundColor:data.count.map((_,i)=>palette[i%palette.length]),borderWidth:0,spacing:3}]); })(),
            (async()=>{ const data=await api("/api/fetch_weekly_runtime"); const seconds=Math.max(0,data.current_uptime[1]-data.current_uptime[0]); $("total_uptime_card").textContent=`${String(Math.floor(seconds/3600)).padStart(2,"0")}:${String(Math.floor(seconds/60)%60).padStart(2,"0")}`; drawChart("weekly_runtimes","bar",["T2","T3","T4","T5","T6","T7","CN"],[{label:"Phút hoạt động",data:data.runtime_data.map(n=>Math.max(0,n)),backgroundColor:"#718e5d",hoverBackgroundColor:"#bcf36b",borderRadius:4,maxBarThickness:30}]); })(),
            (async()=>{ const data=await api("/api/fetch_gamble_data"); drawChart("gamble_earnings","line",Array.from({length:24},(_,i)=>`${i}h`),[{label:"Thắng",data:data.win_data,borderColor:"#6ed6c8",borderWidth:2,pointRadius:0,tension:.3},{label:"Thua",data:data.lose_data,borderColor:"#bd8b7d",borderWidth:2,pointRadius:0,tension:.3}]); })()
        ]);
    } finally { metricsBusy = false; }
}
document.addEventListener("DOMContentLoaded", () => {
    $("today").textContent = new Intl.DateTimeFormat("vi-VN",{timeZone:"Asia/Ho_Chi_Minh",day:"2-digit",month:"long"}).format(new Date());
    $("settings-form").addEventListener("input",()=>{saveError="";dirty=Object.entries(formValues()).some(([key,value])=>value!==savedSettings?.[key]);renderInputs();});
    $("settings-form").addEventListener("submit",async event=>{
        event.preventDefault();if(saving||!dirty)return;
        const invalid = Array.from($("settings-form").elements).find(input=>input.willValidate && !input.checkValidity());
        if (invalid) {
            activatePage(invalid.closest(".tab-page").id.replace("page-",""));
            if (invalid.closest(".game-page")) activateGame(invalid.closest(".game-page").dataset.game);
            invalid.focus(); invalid.reportValidity(); return;
        }
        saving=true;saveError="";$("settings-fields").disabled=true;renderInputs();
        try { const data=await api("/api/settings",{method:"PATCH",data:formValues()});savedSettings=data.settings;dirty=false;if(latest)latest.settings=data.settings;toast("Đã lưu. Thiết lập mới được áp dụng ngay.");renderState(); }
        catch(error){saveError=error.message;toast(error.message,true);}
        finally{saving=false;$("settings-fields").disabled=!authenticated;renderInputs();}
    });
    $("bot-toggle").addEventListener("click",async()=>{
        if(busy||!latest)return;busy=true;$("bot-toggle").disabled=true;
        try{latest=await api("/api/bot",{method:"POST",data:{action:latest.running?"stop":"start"}});busy=false;renderState();toast(latest.running?"Đã bật tự động.":"Đã dừng tự động.");}
        catch(error){busy=false;toast(error.message,true);$("bot-toggle").disabled=true;}
    });
    $("resume-bot").addEventListener("click", async()=>{
        if(busy)return;
        busy=true;$("resume-bot").disabled=true;
        try{latest=await api("/api/bot",{method:"POST",data:{action:"start"}});busy=false;renderState();toast("Đã yêu cầu tiếp tục và xoá trạng thái chờ cũ.");}
        catch(error){busy=false;toast(error.message,true);}
    });
    $("reset-gamble-session").addEventListener("click",resetGambleSession);
    $("risk-bankroll").value=localStorage.getItem("dusk-risk-bankroll") || "";
    $("risk-bankroll").addEventListener("input",()=>{localStorage.setItem("dusk-risk-bankroll",$("risk-bankroll").value);renderGambleRisk();});
    $("risk-apply-bet").addEventListener("click",applyBankrollBet);
    $("risk-losses").addEventListener("input",()=>{riskManual=true;renderGambleRisk();});
    $("risk-use-record").addEventListener("click",()=>{riskManual=false;renderGambleRisk();});
    $("reset-session-account").addEventListener("change",renderGambleRisk);
    $("gamble-risk-form").addEventListener("submit",event=>event.preventDefault());
    $("log-filter").addEventListener("input",renderLogs);
    $("sell-weapons").addEventListener("click",()=>submitSale("weapons"));
    $("sell-animals").addEventListener("click",()=>submitSale("animals"));
    $("sacrifice-animals").addEventListener("click",()=>submitSale("sacrifice"));
    $("weapon-sale-rarity").addEventListener("change",()=>renderSales());
    $("animal-sale-rarity").addEventListener("change",()=>renderSales());
    $("sacrifice-rarity").addEventListener("change",()=>renderSales());
    $("sale-account").addEventListener("change",()=>{lastSaleId=null;renderSales();});
    $("autoscroll").addEventListener("click",()=>{autoScroll=!autoScroll;$("autoscroll").setAttribute("aria-pressed",String(autoScroll));if(autoScroll)renderLogs();});
    initNavigation();
    $("discard-settings").addEventListener("click",()=>{if(savedSettings){saveError="";loadSettings(savedSettings);toast("Đã hoàn tác các thay đổi chưa lưu.");}});
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
    simulation:["Mô phỏng","SO SÁNH COINFLIP","Thử các cách cược trên cùng lịch sử trước khi chỉnh bot."],
    overview:["Tổng quan","HOẠT ĐỘNG HÔM NAY","Trạng thái bot và các số liệu chính trong một màn hình."],
    controls:["Điều khiển","THIẾT LẬP BOT","Nhịp gửi, chế độ nghỉ, gem và kết nối Discord."],
    gambling:["Gamble","TÙY CHỈNH TỪNG TRÒ","Chọn trò, đặt tiền cược và cách tăng cược khi thua."],
    inventory:["Kho đồ","BÁN & HIẾN TẾ","Dọn vũ khí và thú theo độ hiếm. Mỗi thao tác có kết quả riêng."],
    collection:["Thú đã bắt","THỐNG KÊ TÍCH LŨY","Đếm từng loài thú hiếm qua các lần săn; số đếm không giảm khi bán."],
    activity:["Nhật ký","THEO DÕI TRỰC TIẾP","Xem lệnh đã chạy, tìm thông báo và theo dõi lỗi."]
};
let activePage = "overview", activeGame = "coinflip";
function settingsArea(key) {
    return /^(coinflip|slots|blackjack|gambleGoal|gambleLoss)/.test(key) ? "gambling" : "controls";
}
function updateSaveBar(config = formValues()) {
    const changes = savedSettings ? Object.keys(config).filter(key=>config[key]!==savedSettings[key]) : [];
    for (const page of ["controls","gambling"]) {
        $("tab-"+page).querySelector(".tab-dirty").hidden = !changes.some(key=>settingsArea(key)===page);
    }
    $("settings-savebar").hidden = !["controls","gambling"].includes(activePage) && !dirty;
    $("discard-settings").disabled = !dirty || saving || !authenticated;
    const labels = [...new Set(changes.map(key=>PAGES[settingsArea(key)][0]))];
    $("save-context").textContent = changes.length ? `Chưa lưu · ${labels.join(" + ")}` : "Thiết lập đã đồng bộ";
}
function activatePage(page, updateHash = true) {
    if (!PAGES[page]) page="overview";
    activePage=page;
    for (const [key, meta] of Object.entries(PAGES)) {
        $("page-"+key).hidden=key!==page;
        $("tab-"+key).setAttribute("aria-selected",String(key===page));
        $("tab-"+key).tabIndex=key===page?0:-1;
        $("tab-"+key).classList.toggle("active",key===page);
    }
    $("page-title").textContent=PAGES[page][0];
    $("page-eyebrow").textContent=PAGES[page][1];
    $("page-description").textContent=PAGES[page][2];
    document.title=`${PAGES[page][0]} · Dusk`;
    localStorage.setItem("dusk-tab",page);
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
    const page=aliases[key] || key || localStorage.getItem("dusk-tab") || "overview";
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
    if(typeof renderSimulationAccounts==="function") renderSimulationAccounts();
    const usable=accounts.filter(a=>a.accountId);
    const key=JSON.stringify(usable.map(a=>[a.accountId,a.name]));
    if(key!==resetAccountsKey) {
        const selected=$("reset-session-account").value;
        const options=usable.map(account=>{
            const option=document.createElement("option");option.value=account.accountId;option.textContent=account.name;return option;
        });
        $("reset-session-account").replaceChildren(...options);
        if(usable.some(a=>a.accountId===selected)) $("reset-session-account").value=selected;
        resetAccountsKey=key;
    }
    $("reset-account-field").hidden=usable.length<2;
    $("reset-session-account").disabled=resetBusy || Boolean(pendingReset);
    $("reset-gamble-session").disabled=!authenticated || resetBusy || !usable.length;
    $("reset-gamble-session").textContent=resetBusy?"Đang reset…":pendingReset?"Kiểm tra kết quả reset":"Reset lãi/lỗ & chơi lại";
    const fragment=document.createDocumentFragment();
    for(const account of usable) {
        for(const [game,label] of [["coinflip","Coinflip"],["slots","Slots"],["blackjack","Blackjack"]]) {
            const data=account.gambleStreaks?.[game] || {current:0,best:0};
            const card=document.createElement("article");card.className="streak-card";
            const title=document.createElement("h5");title.textContent=label;
            const values=document.createElement("p");
            const current=document.createElement("strong");current.textContent=number(data.current);
            const best=document.createElement("b");best.textContent=number(data.best);
            values.append(current,document.createTextNode(" / "),best);
            const caption=document.createElement("small");caption.textContent=accounts.length>1?account.name:"Chuỗi hiện tại / Kỷ lục";
            card.append(title,values,caption);fragment.append(card);
        }
    }
    if(!usable.length) {
        const empty=document.createElement("p");empty.className="hint";
        empty.textContent="Chưa kết nối Discord. Chuỗi đã lưu sẽ được tải khi tài khoản đăng nhập; bạn vẫn có thể nhập số lần để tính vốn.";
        fragment.append(empty);
    }
    $("gamble-streaks").replaceChildren(fragment);
    renderGambleRisk();
}
async function resetGambleSession() {
    if(resetBusy || !authenticated) return;
    const data=pendingReset || {accountId:$("reset-session-account").value,requestId:crypto.randomUUID()};
    pendingReset=data;resetBusy=true;renderGambleSession(latest?.accounts || []);
    try {
        const result=await api("/api/gamble/reset",{method:"POST",data});
        const account=latest?.accounts.find(a=>a.accountId===data.accountId);
        if(account) {account.gambleProfit=0;account.gambleLossStopped=false;account.gambleStreaks=result.streaks;}
        pendingReset=null;
        $("reset-session-status").textContent="Đã reset lãi/lỗ và chuỗi hiện tại. Giữ nguyên kỷ lục, cấu hình và khoảng chờ; các trò đang bật được phép chơi lại.";
        toast("Đã bắt đầu phiên lãi/lỗ mới.");
        renderState();
    } catch(error) {
        if([400,401].includes(error.status)) pendingReset=null;
        $("reset-session-status").textContent=error.message;
        toast(error.message,true);
    } finally {
        resetBusy=false;renderGambleSession(latest?.accounts || []);
    }
}

function renderGambleRisk() {
    if(!window.GambleMath || !$("risk-losses")) return;
    renderCoinflipSide();
    const game=activeGame;
    const label=gambleLabel(game);
    const accounts=latest?.accounts || [];
    const account=accounts.find(a=>a.accountId===$("reset-session-account").value) || accounts[0];
    const hasRecord=Boolean(account?.accountId);
    const best=account?.gambleStreaks?.[game]?.best || 0;
    $("risk-use-record").disabled=!hasRecord;
    if(!riskManual) $("risk-losses").value=Math.min(60,best);
    const n=Number($("risk-losses").value),base=Number($(game+"-bet").value);
    const doubling=$(game+"-double").checked;
    const budget=$("gamble-loss-enabled").checked?Number($("gamble-loss-amount").value):null;
    renderBankrollBet(game,n,doubling,budget);
    $("risk-heading").textContent=`Vốn cho chuỗi thua · ${label}`;
    $("risk-source").textContent=!hasRecord?"Chưa tải được kỷ lục tài khoản. Nhập số lần thua để mô phỏng.":`${account?.name || "Tài khoản"} · Kỷ lục ${number(best)} lần · ${riskManual?"Đang xem giả lập":"Đang dùng kỷ lục"}${best>60 && !riskManual?" (xem tối đa 60 lượt)":""}`;
    try {
        if($("risk-losses").value==="") throw new Error("Nhập số lần thua từ 0 đến 60.");
        const data=GambleMath.project(base,doubling,n,budget);
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
        $("risk-formula").textContent=doubling
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
    return GambleMath.recommend(Number($("risk-bankroll").value),$(activeGame+"-double").checked,n,limit);
}
function renderBankrollBet(game,n,doubling,limit) {
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
        $("bankroll-constraints").textContent=`Đã tính trần 250.000 mỗi lượt${limit===null?"":`; giới hạn lỗ đang đặt ${number(limit)} nên dùng tối đa ${number(result.usable)} cho chuỗi mới`}. ${doubling?"Gấp đôi: chia vốn cho 2^(N+1)−1 và làm tròn xuống.":"Cược cố định: chia vốn cho N+1 và làm tròn xuống."}`;
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
