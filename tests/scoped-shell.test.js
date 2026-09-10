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
