const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../website/static/script.js"), "utf8");

function dashboard() {
    const elements = new Map(), listeners = new Map(), requests = [];
    const element = id => {
        if (!elements.has(id)) elements.set(id, {
            value: "", checked: false, disabled: false, hidden: false, elements: [],
            textContent: "", dataset: {}, style: {}, events: {},
            classList: {add() {}, remove() {}, toggle() {}},
            addEventListener(type, callback) { this.events[type] = callback; },
        });
        return elements.get(id);
    };
    const context = vm.createContext({
        document: {
            addEventListener(type, callback) { listeners.set(type, callback); },
            getElementById: element,
        },
        setInterval() {},
        request: async (route, options) => {
            requests.push({route, options});
            return null;
        },
    });
    const run = code => vm.runInContext(code, context);
    vm.runInContext(source, context);
    run([
        'renderInputs = () => renderRandomChatSetting();',
        'renderState = renderScope = renderSales = toast = initNavigation = login = () => {};',
        'authenticated = true;',
        'const defaults = {...formValues(), coinflipHistoryWindow:500, gemSkipAtOrAbove:"none",',
        '    coinflipSide:"heads", coinflipSwitchStart:"heads", coinflipProbeTarget:"heads",',
        '    prefix:"o", randomChatEnabled:false};',
        'latest = {settings:defaults, accounts:[], overrides:{}};',
        'api = request;',
        'loadSettings(defaults);',
    ].join("\n"));
    listeners.get("DOMContentLoaded")();
    return {element, run, requests};
}

test("random chat loads off by default and serializes a boolean without writing settings", () => {
    const page = dashboard();
    assert.equal(page.element("random-chat-enabled").checked, false);
    assert.equal(page.element("random-chat-enabled").disabled, false);
    assert.equal(page.run("formValues().randomChatEnabled"), false);
    assert.equal(page.run("dirty"), false);
    assert.equal(page.run('settingsArea("randomChatEnabled")'), "controls");
    page.run("loadSettings({...defaults, randomChatEnabled:true})");
    assert.equal(page.element("random-chat-enabled").checked, true);
    assert.equal(page.run("formValues().randomChatEnabled"), true);
    assert.deepEqual(page.requests, []);
});

test("saving random chat only patches the selected account setting", async () => {
    const page = dashboard();
    page.run([
        'accountScope = "account-a";',
        'api = async (route, options) => {',
        '    await request(route, options);',
        '    return {settings:{...defaults, ...options.data}, overrides:options.data};',
        '};',
    ].join("\n"));
    page.element("random-chat-enabled").checked = true;
    page.element("settings-form").events.input();
    assert.equal(page.run("dirty"), true);
    await page.element("settings-form").events.submit({preventDefault() {}});
    assert.equal(page.requests.length, 1);
    assert.equal(page.requests[0].route, "/api/settings?accountId=account-a");
    assert.equal(page.requests[0].options.method, "PATCH");
    assert.deepEqual(JSON.parse(JSON.stringify(page.requests[0].options.data)), {randomChatEnabled:true});
    assert.equal(page.run("dirty"), false);
    assert.equal(page.element("settings-fields").disabled, false);
});

test("switching accounts keeps the random chat draft separate", async () => {
    const page = dashboard();
    page.run([
        'accountScope = "account-a";',
        'api = async route => {',
        '    await request(route);',
        '    return {settings:{...defaults}, accounts:[], overrides:{}};',
        '};',
    ].join("\n"));
    page.element("random-chat-enabled").checked = true;
    page.element("settings-form").events.input();
    await page.run('selectAccountScope("account-b")');
    assert.equal(page.element("random-chat-enabled").checked, false);
    assert.equal(page.run('accountDrafts.get("account-a").randomChatEnabled'), true);
    assert.equal(page.run("dirty"), false);
    await page.run('selectAccountScope("account-a")');
    assert.equal(page.element("random-chat-enabled").checked, true);
    assert.equal(page.run("dirty"), true);
    assert.ok(page.requests.every(request => request.options?.method !== "PATCH"));
});

test("polling preserves unsaved random chat changes and refreshes a clean form", async () => {
    const page = dashboard();
    page.run('api = async route => route === "/api/console" ? null : {settings:{...defaults}, accounts:[], overrides:{}};');
    page.element("random-chat-enabled").checked = true;
    page.element("settings-form").events.input();
    await page.run("poll()");
    assert.equal(page.element("random-chat-enabled").checked, true);
    page.run("loadSettings(defaults)");
    assert.equal(page.run("dirty"), false);
    page.run('api = async route => route === "/api/console" ? null : {settings:{...defaults, randomChatEnabled:true}, accounts:[], overrides:{}};');
    await page.run("poll()");
    assert.equal(page.element("random-chat-enabled").checked, true);
    assert.equal(page.run("dirty"), false);
});

test("old bot configuration disables random chat without breaking other settings saves", async () => {
    const page = dashboard();
    page.run([
        'const oldDefaults = {...defaults}; delete oldDefaults.randomChatEnabled;',
        'latest.settings = oldDefaults; loadSettings(oldDefaults);',
        'accountScope = "account-a";',
        'api = async (route, options) => {',
        '    await request(route, options);',
        '    return {settings:{...oldDefaults, ...options.data}, overrides:options.data};',
        '};',
    ].join("\n"));
    assert.equal(page.element("random-chat-enabled").disabled, true);
    assert.match(page.element("random-chat-hint").textContent, /Khởi động lại bot/);
    assert.equal(page.run('Object.hasOwn(formValues(), "randomChatEnabled")'), false);
    assert.equal(page.run("dirty"), false);
    page.element("battle-enabled").checked = true;
    page.element("settings-form").events.input();
    await page.element("settings-form").events.submit({preventDefault() {}});
    assert.equal(page.requests.length, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(page.requests[0].options.data)), {battleEnabled:true});
    assert.equal(page.run("dirty"), false);
});
