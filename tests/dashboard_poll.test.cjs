const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../website/static/script.js"), "utf8");

function dashboard(request) {
    const connection = {classList: {add() {}, remove() {}}};
    const context = vm.createContext({
        document: {addEventListener() {}, getElementById: () => connection},
        request,
    });
    vm.runInContext(source, context);
    return code => vm.runInContext(code, context);
}

test("a poll started before a start or stop cannot replace the new status", async () => {
    let resolvePoll;
    const run = dashboard((route, options) => {
        if (route === "/api/console") return Promise.resolve(null);
        if (options?.method === "POST") return Promise.resolve({running: false});
        return new Promise(resolve => { resolvePoll = resolve; });
    });
    run(`authenticated = dashboardOnline = true;
         latest = {running: true}; api = request; renderState = () => {}; toast = () => {};`);
    const polling = run("poll()");
    await run('setDashboardRunning("stop")');
    resolvePoll({running: true});
    await polling;
    assert.equal(run("latest.running"), false);
});

test("a failed poll keeps remote actions unavailable until the connection recovers", async () => {
    let calls = 0;
    const run = dashboard(async () => { calls++; throw new Error("offline"); });
    run(`authenticated = dashboardOnline = true;
         latest = {running: true}; api = request; renderState = () => {};`);
    await run("poll()");
    assert.equal(run("dashboardOnline"), false);
    await run('setDashboardRunning("stop")');
    assert.equal(calls, 1);
});
