const assert = require("node:assert/strict")
const test = require("node:test")
const fs = require("node:fs")
const vm = require("node:vm")
const path = require("node:path")
function qmlFunction(file, name, context) {
  const source = fs.readFileSync(path.join(__dirname, "..", file), "utf8")
  const match = source.match(new RegExp("^  function " + name + "\\([^]*?^  }", "m"))
  assert.ok(match, name)
  vm.runInNewContext(match[0] + "; this.call = " + name, context)
  return context.call
}

test("service reads saved inline settings through a scoped shell", () => {
  const entry = {id: "patrickfanella.superproductivity", autoStartNext: true, notificationUrgency: "normal"}
  const ctx = {shell: {barConfig: {layout: {right: [entry]}}}, pluginId: entry.id}
  ctx.entriesIn = qmlFunction("Service.qml", "entriesIn", ctx)
  const result = qmlFunction("Service.qml", "configEntry", ctx)()
  assert.equal(result.autoStartNext, true)
  assert.equal(result.notificationUrgency, "normal")
})
test("settings writer submits only its own entry and reports rejection", () => {
  let request
  const ctx = {bar: {shell: {updateEntryInline: (id, values) => {request = {id, values}; return true}}},
    settings: {notificationUrgency: "normal"}, moduleName: "patrickfanella.superproductivity", tr: key => key}
  const persist = qmlFunction("Panel.qml", "persistSetting", ctx)
  assert.equal(persist("autoStartNext", false, "Auto next"), true)
  assert.equal(request.id, ctx.moduleName)
  assert.deepEqual(JSON.parse(JSON.stringify(request.values)), {notificationUrgency: "normal", autoStartNext: false})
  ctx.bar.shell.updateEntryInline = () => false
  assert.equal(persist("autoStartNext", true, "Auto next"), false)
  assert.equal(ctx.settingsState, "failed")
})


test("quick Add IPC selects the popup mode only during summon", () => {
  const ctx = {quickAddRequested: false}
  ctx.summon = method => {
    assert.equal(method, "summon")
    assert.equal(ctx.quickAddRequested, true)
    return "ok"
  }
  const open = qmlFunction("Service.qml", "quickAdd", ctx)
  assert.equal(open(), "ok")
  assert.equal(ctx.quickAddRequested, false)
  ctx.summon = () => { throw new Error("unavailable") }
  assert.throws(open, /unavailable/)
  assert.equal(ctx.quickAddRequested, false)
})

test("quick Add popup preserves drafts and pending results while focusing the input", () => {
  let focuses = 0
  const ctx = {quickAddOnly: false, settingsView: true, scroller: {contentY: 100},
    addRequestId: "pending", addState: "running", addMessage: "Creating",
    addField: {text: "Draft 30m", forceActiveFocus: () => focuses++},
    Qt: {callLater: fn => fn()}}
  ctx.root = {opened: false, open: () => { ctx.root.opened = true }}
  const open = qmlFunction("Panel.qml", "quickAdd", ctx)
  open()
  assert.equal(ctx.quickAddOnly, true)
  assert.equal(ctx.settingsView, false)
  assert.equal(ctx.scroller.contentY, 0)
  assert.equal(ctx.addField.text, "Draft 30m")
  assert.equal(ctx.addState, "running")
  assert.equal(focuses, 1)
  ctx.addRequestId = ""
  open()
  assert.equal(ctx.addState, "")
  assert.equal(ctx.addMessage, "")
})

test("modal add uses the shared queue and keeps rejected input for correction", () => {
  let submitted
  const ctx = {engine: {add: (value, startAfter) => {
    submitted = {value, startAfter}
    return {accepted: true, requestId: "request-1"}
  }}, mutationBusy: false, addField: {text: " Draft 30m "}, quickAddOnly: true,
    rememberAddMode: () => {}, tr: key => key, rejection: error => error}
  const submit = qmlFunction("Panel.qml", "submitAdd", ctx)
  submit(true)
  assert.deepEqual(submitted, {value: "Draft 30m", startAfter: true})
  assert.equal(ctx.addCloseOnSuccess, true)
  assert.equal(ctx.addState, "running")
  ctx.engine.add = () => ({accepted: false, error: "queue-full"})
  submit(false)
  assert.equal(ctx.addRequestId, "")
  assert.equal(ctx.addState, "failed")
  assert.equal(ctx.addMessage, "queue-full")
  assert.equal(ctx.addField.text, " Draft 30m ")
})


test("popup positions the painted card at screen center and preserves bar anchoring", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "TaskPopup.qml"), "utf8")
  const binding = source.match(/readonly property point cardOrigin: (\{[^]*?^  \})/m)
  assert.ok(binding)
  assert.match(source, /x: root\.cardOrigin\.x/)
  assert.match(source, /y: root\.cardOrigin\.y/)
  const ctx = {centerOnScreen: true, screenW: 2160, screenH: 1350,
    contentWidth: 840, contentHeight: 240, Qt: {point: (x, y) => ({x, y})},
    anchorItem: {}, bar: {}, centerOnBar: false, margin: 10, gap: 10,
    barPos: "top", barH: 26, barW: 26, anchorScreenPos: {x: 1000, y: 0}, anchorW: 40, anchorH: 26}
  const position = vm.runInNewContext("(function() " + binding[1] + ")", ctx)
  assert.deepEqual(position(), {x: 660, y: 555})
  ctx.centerOnScreen = false
  assert.deepEqual(position(), {x: 600, y: 36})
  ctx.barPos = "bottom"
  assert.deepEqual(position(), {x: 600, y: 1074})
})
