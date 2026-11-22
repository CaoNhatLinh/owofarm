"use strict";
(function(root) {
    function project(base, doubling, losses, budget=null) {
        if (!Number.isInteger(base) || base<1 || base>250000 ||
            !Number.isInteger(losses) || losses<0 || losses>60 || typeof doubling!=="boolean")
            throw new RangeError("Tiền cược 1–250.000; chuỗi thua 0–60 lần.");
        if (budget!==null && (!Number.isInteger(budget) || budget<1 || budget>1000000000000))
            throw new RangeError("Vốn tính toán không hợp lệ.");
        const amount=BigInt(base), cap=250000n, bank=budget===null?null:BigInt(budget);
        let stake=amount,total=0n;
        const rows=[];
        for(let i=1;i<=losses;i++) {
            total+=stake;
            rows.push({round:i,stake,total,aboveCap:stake>cap,aboveBudget:bank!==null && total>bank});
            if(doubling) stake*=2n;
        }
        const units= doubling ? (1n<<BigInt(losses+1))-1n : BigInt(losses+1);
        const capBase=cap/(doubling?(1n<<BigInt(losses)):1n);
        return {base:amount,losses,total,next:stake,capital:total+stake,rows,
            firstBlocked:rows.find(row=>row.aboveCap || row.aboveBudget)?.round || null,
            nextAboveCap:stake>cap,nextAboveBudget:bank!==null && total+stake>bank,
            maxBase:bank===null?null:(bank/units>capBase?capBase:bank/units)};
    }
    function recommend(bankroll, doubling, losses, lossLimit=null) {
        const unit=project(1,doubling,losses,bankroll);
        if(lossLimit!==null && (!Number.isInteger(lossLimit) || lossLimit<1 || lossLimit>1000000000000))
            throw new RangeError("Giới hạn lỗ không hợp lệ.");
        const bank=BigInt(bankroll), limit=lossLimit===null?bank:BigInt(lossLimit);
        const usable=bank<limit?bank:limit;
        const byCapital=usable/unit.capital, byBetCap=250000n/unit.next;
        const base=byCapital<byBetCap?byCapital:byBetCap;
        const calculation=base>0n?project(Number(base),doubling,losses,Number(usable)):null;
        return {base,bank,usable,minimumCapital:unit.capital,capImpossible:unit.next>250000n,
            calculation,leftover:calculation?bank-calculation.capital:bank};
    }
    if(typeof module!=="undefined" && module.exports) module.exports={project,recommend};
    else root.GambleMath={project,recommend};
})(typeof globalThis!=="undefined"?globalThis:this);
