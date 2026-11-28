const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

function page() {
    const elements={};
    const element=id=>elements[id] ||= {value:'',checked:false,hidden:false,disabled:false,textContent:'',style:{},children:[],
        append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;},
        addEventListener(){},dispatchEvent(){events.push(id);}};
    const events=[],calls=[];
    const context=vm.createContext({$:element,document:{addEventListener(){},createElement(){return element('node'+Object.keys(elements).length);},createDocumentFragment(){return {append(){}};}},
        accountScope:'a',accountName:()=> 'A',savedSettings:{coinflipBet:200,gambleGoalEnabled:false,gambleLossEnabled:false},
        authenticated:true,saving:false,number:String,Event:class {},palette:['lime'],
        activatePage:v=>calls.push(['page',v]),activateGame:v=>calls.push(['game',v]),toast:v=>calls.push(['toast',v]),api:()=>{throw Error('Unexpected settings request');}});
    vm.runInContext(fs.readFileSync('website/static/simulation.js','utf8'),context);
    return {context,element,events,calls,run:code=>vm.runInContext(code,context)};
}
test('review is read-only; applying only fills a draft and leaves game switch alone',()=>{
    const p=page();p.element('coinflip-enabled').checked=false;
    p.run(`simulationResult={inputs:{accountId:'a',base:125,capital:10000,goal:1000,lossLimit:2000}};reviewSimulation({mode:'auto100',doubling:false});`);
    assert.equal(p.element('coinflip-bet').value,'');
    assert.deepEqual(p.events,[]);
    p.run('applySimulationDraft()');
    assert.equal(p.element('coinflip-bet').value,125);
    assert.equal(p.element('coinflip-side').value,'auto');
    assert.equal(p.element('coinflip-history-window').value,100);
    assert.equal(p.element('coinflip-double').checked,false);
    assert.equal(p.element('gamble-loss-amount').value,2000);
    assert.equal(p.element('coinflip-enabled').checked,false);
    assert.deepEqual(p.events,['coinflip-bet']);
    assert.ok(p.calls.some(c=>c[0]==='page' && c[1]==='gambling'));
});
test('changed inputs invalidate previous results and unauthenticated apply does nothing',()=>{
    const p=page();
    p.run(`simulationResult={inputs:{base:125}};simulationChoice={mode:'heads',doubling:true};clearSimulation();applySimulationDraft();`);
    assert.equal(p.element('sim-results').hidden,true);
    assert.deepEqual(p.events,[]);
    p.run(`authenticated=false;simulationResult={inputs:{base:125}};simulationChoice={mode:'heads'};applySimulationDraft();`);
    assert.deepEqual(p.events,[]);
});
test('probe and valid generator presets can be drafted; invalid tiers cannot',()=>{
    const p=page();
    p.run(`simulationResult={inputs:{accountId:'a',base:100,capital:10000,goal:null,lossLimit:null}};simulationChoice={mode:'probe',base:100,doubling:true,applicable:true};applySimulationDraft();`);
    assert.equal(p.element('coinflip-side').value,'probe');
    p.run(`simulationChoice={mode:'generatorTails',base:204800,doubling:true,applicable:true};applySimulationDraft();`);
    assert.equal(p.element('coinflip-side').value,'tails');
    assert.equal(p.element('coinflip-bet').value,204800);
    p.run(`simulationChoice={mode:'probeLossTails',base:200,doubling:true,applicable:true};applySimulationDraft();`);
    assert.equal(p.element('coinflip-side').value,'probe_loss');
    assert.equal(p.element('coinflip-probe-target').value,'tails');
    p.run(`simulationChoice={mode:'generatorHeads',base:409600,doubling:true,applicable:false};applySimulationDraft();`);
    assert.equal(p.element('coinflip-bet').value,200);
    p.run(`simulationChoice={mode:'switchTails',base:200,doubling:false,applicable:true};applySimulationDraft();`);
    assert.equal(p.element('coinflip-side').value,'win_switch');
    assert.equal(p.element('coinflip-switch-start').value,'tails');
});
test('a bonus ladder preset fills its own toggle and a regular preset clears it',()=>{
    const p=page();
    p.run(`simulationResult={inputs:{accountId:'a',base:100,goal:null,lossLimit:null}};reviewSimulation({mode:'heads',base:100,doubling:true,bonus:true,applicable:true});applySimulationDraft();`);
    assert.equal(p.element('coinflip-bonus').checked,true);
    assert.equal(p.element('coinflip-double').checked,true);
    assert.match(p.element('sim-review-text').textContent,/10% của lượt trước/);
    p.run(`simulationChoice={mode:'tails',base:100,doubling:true,bonus:false};applySimulationDraft();`);
    assert.equal(p.element('coinflip-bonus').checked,false);
});
test('a replay cannot fill a different account’s settings',()=>{
    const p=page();
    p.run(`simulationResult={inputs:{accountId:'a',base:125}};simulationChoice={mode:'heads'};accountScope='b';applySimulationDraft();`);
    assert.equal(p.element('coinflip-bet').value,'');
    assert.deepEqual(p.events,[]);
});
