const test=require('node:test');
const assert=require('node:assert/strict');
const {project,recommend}=require('../website/static/gamble_math.js');

test('200, five losses: cumulative losses, next stake and capital are distinct',()=>{
    const p=project(200,true,5,10000);
    assert.equal(p.total,6200n);
    assert.equal(p.next,6400n);
    assert.equal(p.capital,12600n);
    assert.deepEqual(p.rows.map(r=>r.stake),[200n,400n,800n,1600n,3200n]);
    assert.equal(p.maxBase,158n);
    assert.equal(p.nextAboveBudget,true);
    assert.ok(project(158,true,5,10000).capital<=10000n);
    assert.ok(project(159,true,5,10000).capital>10000n);
});
test('fixed stakes do not grow after losses',()=>{
    const p=project(200,false,5,10000);
    assert.equal(p.total,1000n);assert.equal(p.next,200n);assert.equal(p.capital,1200n);
    assert.equal(p.maxBase,1666n);
});
test('no losses have zero cost but next round still needs capital',()=>{
    const p=project(200,true,0,null);
    assert.equal(p.total,0n);assert.equal(p.next,200n);assert.equal(p.capital,200n);
    assert.equal(p.maxBase,null);assert.equal(p.rows.length,0);
});
test('large calculations remain exact beyond Number precision',()=>{
    const p=project(250000,true,60);
    assert.equal(p.total,250000n*((1n<<60n)-1n));
    assert.equal(p.capital,250000n*((1n<<61n)-1n));
});
test('budget and maximum per bet identify the first impossible round',()=>{
    assert.equal(project(200,true,10,10000).firstBlocked,6);
    assert.equal(project(250000,true,2,null).firstBlocked,2);
    assert.equal(project(1,true,5,10).maxBase,0n);
    assert.equal(project(200,true,1,200).firstBlocked,null);
    assert.equal(project(200,true,1,200).nextAboveBudget,true);
});
test('invalid values do not yield misleading money amounts',()=>{
    for(const args of [[0,true,5],[1.5,true,5],[200,true,-1],[200,true,61],[200,true,1.5],[200,true,5,0]])
        assert.throws(()=>project(...args),RangeError);
});

test('bankroll 100k supports five losses and the sixth stake from base 1587',()=>{
    const p=recommend(100000,true,5);
    assert.equal(p.base,1587n);assert.equal(p.calculation.total,49197n);
    assert.equal(p.calculation.next,50784n);assert.equal(p.calculation.capital,99981n);
    assert.equal(p.leftover,19n);
    assert.ok(project(1588,true,5).capital>100000n);
});
test('recommendation respects the NEXT stake cap, not just the initial one',()=>{
    const p=recommend(10000000,true,5);
    assert.equal(p.base,7812n);
    assert.ok(p.calculation.next<=250000n);
    assert.ok(project(Number(p.base+1n),true,5).next>250000n);
});
test('enabled loss limit further constrains entered bankroll',()=>{
    const p=recommend(100000,true,5,10000);
    assert.equal(p.base,158n);assert.equal(p.usable,10000n);
    assert.ok(p.calculation.capital<=10000n);
});
test('fixed bets and zero losses handle division and per-bet cap',()=>{
    assert.equal(recommend(100000,false,5).base,16666n);
    assert.equal(recommend(1000000,true,0).base,250000n);
});
test('no valid stake is offered if minimum capital or per-bet cap fails',()=>{
    assert.equal(recommend(1,true,5).base,0n);
    assert.equal(recommend(1,true,5).minimumCapital,63n);
    assert.equal(recommend(1000000000000,true,18).base,0n);
    assert.equal(recommend(1000000000000,true,18).capImpossible,true);
});

test('Coinflip bonus increases every multiplier and floors every wager',()=>{
    const projection=project(101,true,4,null,true);
    assert.deepEqual(projection.rows.map(row=>row.stake),[101n,202n,424n,932n]);
    assert.equal(projection.total,1659n);
    assert.equal(projection.next,2143n);
    assert.equal(projection.capital,3802n);
    assert.deepEqual(project(101,false,4,1000,true),project(101,false,4,1000));
});

test('Coinflip bonus recommendation accounts for rounding at the loss-limit boundary',()=>{
    const result=recommend(1000,true,3,46,true);
    assert.equal(result.base,2n);
    assert.equal(result.calculation.capital,31n);
    assert.equal(project(3,true,3,46,true).maxBase,2n);
    assert.equal(project(3,true,3,46,true).capital,47n);
    const exact=recommend(1000,true,3,47,true);
    assert.equal(exact.base,3n);
    assert.equal(exact.calculation.capital,47n);
});

test('Coinflip bonus recommendation accounts for rounding at the next-bet cap',()=>{
    const result=recommend(1000000,true,2,null,true);
    assert.equal(result.base,59524n);
    assert.equal(result.calculation.next,250000n);
    assert.equal(project(59525,true,2,null,true).nextAboveCap,true);
});
