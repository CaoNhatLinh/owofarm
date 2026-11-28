"use strict";
(function(root) {
    const cap=250000n;

    function stakes(base, doubling, losses, bonus) {
        const amounts=[base];
        for (let previousLosses=0; previousLosses<losses; previousLosses++) {
            const previous=amounts[previousLosses];
            const multiplier=bonus ? 200n+10n*BigInt(previousLosses) : 200n;
            amounts.push(doubling ? previous*multiplier/100n : previous);
        }
        return amounts;
    }

    function affordableBase(doubling, losses, bank, bonus) {
        if (!doubling || !bonus) {
            const nextUnits=doubling ? 1n<<BigInt(losses) : 1n;
            const totalUnits=doubling ? 2n*nextUnits-1n : BigInt(losses+1);
            const byCapital=bank/totalUnits;
            const byBetCap=cap/nextUnits;
            return byCapital<byBetCap ? byCapital : byBetCap;
        }

        // Rounding every step makes total exposure nonlinear in the starting bet.
        // Larger starting bets never reduce any later wager or total exposure.
        let low=0n;
        let high=cap;
        while (low<high) {
            const mid=(low+high+1n)/2n;
            const amounts=stakes(mid, doubling, losses, bonus);
            const capital=amounts.reduce((total, stake)=>total+stake, 0n);
            if (amounts[losses]<=cap && capital<=bank) low=mid;
            else high=mid-1n;
        }
        return low;
    }

    function project(base, doubling, losses, budget=null, bonus=false) {
        if (!Number.isInteger(base) || base<1 || base>250000 ||
            !Number.isInteger(losses) || losses<0 || losses>60 ||
            typeof doubling!=="boolean" || typeof bonus!=="boolean")
            throw new RangeError("Tiền cược 1–250.000; chuỗi thua 0–60 lần.");
        if (budget!==null && (!Number.isInteger(budget) || budget<1 || budget>1000000000000))
            throw new RangeError("Vốn tính toán không hợp lệ.");
        const amount=BigInt(base), bank=budget===null?null:BigInt(budget);
        const amounts=stakes(amount, doubling, losses, bonus);
        let total=0n;
        const rows=[];
        for(let i=1;i<=losses;i++) {
            const stake=amounts[i-1];
            total+=stake;
            rows.push({round:i,stake,total,aboveCap:stake>cap,aboveBudget:bank!==null && total>bank});
        }
        const stake=amounts[losses];
        return {base:amount,losses,total,next:stake,capital:total+stake,rows,
            firstBlocked:rows.find(row=>row.aboveCap || row.aboveBudget)?.round || null,
            nextAboveCap:stake>cap,nextAboveBudget:bank!==null && total+stake>bank,
            maxBase:bank===null?null:affordableBase(doubling, losses, bank, bonus)};
    }
    function recommend(bankroll, doubling, losses, lossLimit=null, bonus=false) {
        if (!Number.isInteger(bankroll) || bankroll<1 || bankroll>1000000000000)
            throw new RangeError("Vốn tính toán không hợp lệ.");
        const unit=project(1,doubling,losses,null,bonus);
        if(lossLimit!==null && (!Number.isInteger(lossLimit) || lossLimit<1 || lossLimit>1000000000000))
            throw new RangeError("Giới hạn lỗ không hợp lệ.");
        const bank=BigInt(bankroll), limit=lossLimit===null?bank:BigInt(lossLimit);
        const usable=bank<limit?bank:limit;
        const base=affordableBase(doubling, losses, usable, bonus);
        const calculation=base>0n?project(Number(base),doubling,losses,Number(usable),bonus):null;
        return {base,bank,usable,minimumCapital:unit.capital,capImpossible:unit.next>cap,
            calculation,leftover:calculation?bank-calculation.capital:bank};
    }
    if(typeof module!=="undefined" && module.exports) module.exports={project,recommend};
    else root.GambleMath={project,recommend};
})(typeof globalThis!=="undefined"?globalThis:this);
