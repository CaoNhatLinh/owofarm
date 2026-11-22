"use strict";
let simulationResult=null, simulationChoice=null, simulationChart=null, simulationBusy=false, simulationAccounts="";
const simulationMode={heads:"Heads cố định",tails:"Tails cố định",auto100:"Tự chọn · 100 ván",auto500:"Tự chọn · 500 ván",probe:"Thử 1 + chọn/đảo ngẫu nhiên",probeLossHeads:"Thử Ngửa 1 đến thua → Ngửa chính",probeLossTails:"Thử Sấp 1 đến thua → Sấp chính",switchHeads:"Thắng đổi, thua giữ · đầu Ngửa",switchTails:"Thắng đổi, thua giữ · đầu Sấp",generatorHeads:"Generator · Heads",generatorTails:"Generator · Tails"};
const simulationStop={complete:"Hết tập kiểm tra",goal:"Đạt mục tiêu",loss_limit:"Chặn giới hạn lỗ",bet_cap:"Vượt trần 250.000",capital:"Không đủ vốn"};
function renderSimulationAccounts() {
    const accounts=(latest?.accounts || []).filter(a=>a.accountId);
    const key=JSON.stringify(accounts.map(a=>[a.accountId,a.name]));
    if(key===simulationAccounts) return;
    simulationAccounts=key;
    const old=$("sim-account").value;
    $("sim-account").replaceChildren(...accounts.map(a=>{const o=document.createElement("option");o.value=a.accountId;o.textContent=a.name || a.accountId;return o;}));
    if(accounts.some(a=>a.accountId===old)) $("sim-account").value=old;
    if(!$("sim-base").value && savedSettings) {
        $("sim-base").value=savedSettings.coinflipBet;
        $("sim-goal").value=savedSettings.gambleGoalEnabled?savedSettings.gambleGoalAmount:"";
        $("sim-loss").value=savedSettings.gambleLossEnabled?savedSettings.gambleLossAmount:"";
    }
}
function simulationInputs() {
    return {accountId:$("sim-account").value,capital:Number($("sim-capital").value),base:Number($("sim-base").value),
        warmupPercent:Number($("sim-warmup").value),goal:$("sim-goal").value===""?null:Number($("sim-goal").value),
        lossLimit:$("sim-loss").value===""?null:Number($("sim-loss").value)};
}
function clearSimulation() {
    simulationResult=simulationChoice=null;$("sim-results").hidden=true;$("sim-review").hidden=true;
    $("sim-status").textContent="Thông số đã đổi. Bấm Chạy mô phỏng để so sánh lại.";
}
async function runSimulation() {
    if(simulationBusy || !authenticated) return;
    renderSimulationAccounts();
    const inputs=simulationInputs(), signature=JSON.stringify(inputs);
    simulationBusy=true;$("sim-run").disabled=true;$("sim-status").textContent="Đang mô phỏng 20 tổ hợp…";
    $("sim-results").hidden=true;$("sim-review").hidden=true;
    try {
        const result=await api("/api/gamble/simulate",{method:"POST",data:inputs});
        if(signature!==JSON.stringify(simulationInputs())) {clearSimulation();return;}
        simulationResult=result;simulationChoice=null;
        $("sim-results").hidden=false;
        $("sim-status").textContent=`Đọc ${result.samples} ván: ${result.warmup} ván đầu làm mẫu, ${result.tested} ván sau để kiểm tra. Vốn ${number(inputs.capital)}, cược đầu ${number(inputs.base)}; riêng Generator tự tính cược đầu theo bậc vốn. Cược thử 1 được tính vào lãi/lỗ và số ván. Mọi tổ hợp cùng giới hạn.`;
        const first=result.results.find(r=>r.played>0);
        $("sim-verdict").textContent=!first?"Không tổ hợp nào đủ điều kiện đặt cược với thông số này.":(first.profit>0?"Lãi cao nhất trong tập này: ":"Không có tổ hợp lãi; ít lỗ nhất trong tập này: ")+simulationMode[first.mode]+" · "+(first.doubling?"Gấp đôi":"Cược cố định")+` (${number(first.profit)} cowoncy). Đây là xếp hạng trên tập kiểm tra này, không phải dự báo hay đề xuất tự động.`;
        const fragment=document.createDocumentFragment();
        for(const row of result.results) {
            const tr=document.createElement("tr");
            const values=[simulationMode[row.mode]+" · "+(row.doubling?"Gấp đôi":"Cố định"),number(row.base),number(row.profit),number(row.maxDrawdown),`${row.played}/${result.tested}${row.probes?` (${row.probes} thử)`:""}`,`${row.wins}/${row.losses}`,number(row.maxStake),number(row.maxLossStreak),simulationStop[row.stop]+(row.stopAt?` (lượt ${row.stopAt})`:"")];
            values.forEach((v,i)=>{const td=document.createElement("td");td.textContent=v;if(i===2)td.className=row.profit>=0?"sim-positive":"sim-negative";tr.append(td);});
            const td=document.createElement("td"),button=document.createElement("button");button.type="button";button.className="button secondary";button.textContent=row.applicable?"Xem cấu hình":"Cược đầu vượt trần";button.disabled=!row.applicable;button.addEventListener("click",()=>reviewSimulation(row));td.append(button);tr.append(td);fragment.append(tr);
        }
        $("sim-rows").replaceChildren(fragment);
        if(simulationChart) simulationChart.destroy();
        if(typeof Chart!=="undefined") simulationChart=new Chart($("sim-chart"),{type:"line",data:{datasets:result.results.map((r,i)=>({label:simulationMode[r.mode]+" · "+(r.doubling?"Gấp đôi":"Cố định"),data:r.curve.map(p=>({x:p.round,y:p.profit})),borderColor:palette[i%palette.length],borderDash:i===7?[4,4]:[],borderWidth:2,pointRadius:0}))},options:{responsive:true,maintainAspectRatio:false,animation:false,scales:{x:{type:"linear",title:{display:true,text:"Ván kiểm tra"}},y:{title:{display:true,text:"Lãi/lỗ · cowoncy"}}},plugins:{legend:{labels:{color:"#a8beb2",font:{size:10}}}}}});
    } catch(error) {$("sim-status").textContent=error.message;}
    finally {simulationBusy=false;$("sim-run").disabled=!authenticated;}
}
function reviewSimulation(row) {
    if(!simulationResult) return;
    simulationChoice=row;
    const p=simulationResult.inputs;
    $("sim-review").hidden=false;
    $("sim-review-text").textContent=`${simulationMode[row.mode]} · Cược chính ban đầu ${number(row.base)} · ${row.doubling?"Nhân đôi khi thua":"Cược cố định"}. ${row.mode==="probe"?"Mỗi lượt chính có cược thử 1 trước; chọn/đảo mặt bằng số ngẫu nhiên nội bộ tương đương ochoose. Không dùng tỷ lệ 80% quảng cáo. ":""}${row.mode.startsWith("generator")?"Generator được áp dụng bằng mức đầu theo bậc vốn và bật gấp đôi; không có thuật toán chính xác 65–75%. ":""}Mục tiêu lãi: ${p.goal===null?"tắt":number(p.goal)}; giới hạn lỗ: ${p.lossLimit===null?"tắt":number(p.lossLimit)} (giới hạn chung các trò). Vốn ${number(p.capital)} chỉ dùng giả lập. Nút bên dưới điền bản nháp; cần Lưu thay đổi, không tự bật trò hay gửi cược.`;
    if(row.mode.startsWith("probeLoss")) $("sim-review-text").textContent+=" Thử cùng mặt cược chính với 1 cowoncy cho đến khi thua mới cược chính mức lớn, vẫn cùng mặt. Thử thắng tiếp tục thử, không reset mức chính. Sau mỗi lượt chính trở về thử.";
    if(row.mode.startsWith("switch")) $("sim-review-text").textContent+=" Mỗi lượt chính: thắng đổi mặt, thua giữ mặt; không có cược thử hoặc chọn ngẫu nhiên.";
    $("sim-fill").disabled=!authenticated || saving;
}
function applySimulationDraft() {
    if(!simulationChoice || !simulationResult || simulationChoice.applicable===false || !authenticated || saving) return;
    const p=simulationResult.inputs,r=simulationChoice;
    $("coinflip-bet").value=r.base || p.base;$("coinflip-double").checked=r.doubling;
    $("coinflip-side").value=r.mode.startsWith("auto")?"auto":r.mode.startsWith("probeLoss")?"probe_loss":r.mode.startsWith("switch")?"win_switch":r.mode==="generatorHeads"?"heads":r.mode==="generatorTails"?"tails":r.mode;
    if(r.mode.startsWith("switch")) $("coinflip-switch-start").value=r.mode==="switchHeads"?"heads":"tails";
    if(r.mode.startsWith("probeLoss")) $("coinflip-probe-target").value=r.mode==="probeLossHeads"?"heads":"tails";
    if(r.mode.startsWith("auto")) $("coinflip-history-window").value=r.mode==="auto100"?100:500;
    $("gamble-goal-enabled").checked=p.goal!==null;if(p.goal!==null)$("gamble-goal-amount").value=p.goal;
    $("gamble-loss-enabled").checked=p.lossLimit!==null;if(p.lossLimit!==null)$("gamble-loss-amount").value=p.lossLimit;
    $("coinflip-bet").dispatchEvent(new Event("input",{bubbles:true}));
    activatePage("gambling");activateGame("coinflip");
    toast("Đã điền cấu hình mô phỏng. Kiểm tra rồi bấm Lưu thay đổi để áp dụng.");
}
document.addEventListener("DOMContentLoaded",()=>{
    $("sim-run").addEventListener("click",runSimulation);
    $("sim-fill").addEventListener("click",applySimulationDraft);
    $("coinflip-simulation-form").addEventListener("submit",e=>e.preventDefault());
    $("sim-fields").addEventListener("input",clearSimulation);
});
