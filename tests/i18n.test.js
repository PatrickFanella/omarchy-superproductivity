const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const test = require("node:test")
const I18n = require("../I18n.js")

test("supported locales are stable and complete", () => {
  assert.deepEqual(I18n.SUPPORTED_LOCALES, ["en", "de", "es", "fr", "it", "pt-BR", "nl", "pl", "hr", "zh-CN"])
  assert.deepEqual(Object.keys(I18n.CATALOGS), I18n.SUPPORTED_LOCALES)
})

test("locale aliases and unsupported locales resolve safely", () => {
  const cases = {"de_DE.UTF-8":"de",pt_BR:"pt-BR",zh_CN:"zh-CN",hr_HR:"hr",C:"en",POSIX:"en","en_US.UTF-8":"en",fr_CA:"fr",xx_YY:"en"}
  for (const [source, expected] of Object.entries(cases)) assert.equal(I18n.resolveLocale(source), expected, source)
})

test("missing locale entries fall back per key to English", () => {
  const original = I18n.CATALOGS.de["service.opened"]
  delete I18n.CATALOGS.de["service.opened"]
  assert.equal(I18n.translate("de", "service.opened"), "Super Productivity opened")
  I18n.CATALOGS.de["service.opened"] = original
  assert.equal(I18n.translate("de", "unknown.protocol-token"), "unknown.protocol-token")
})

test("translation fallback rejects inherited English keys", () => {
  for (const locale of ["en", "de"]) {
    for (const key of ["constructor", "toString", "__proto__"])
      assert.equal(I18n.translate(locale, key), key, `${locale}:${key}`)
  }
})

test("named placeholders interpolate and unknown placeholders survive", () => {
  assert.equal(I18n.translate("en", "notification.scheduledNow", {title:"Write +Work #focus"}), "Scheduled now: Write +Work #focus")
  assert.equal(I18n.translate("de", "service.statusFailed", {}), "Super-Productivity-Status fehlgeschlagen (Exit {exitCode})")
  assert.equal(I18n.translate("en", "bar.taskLeft", {title:"{private}",remaining:"5m"}), "{private} · 5m left")
})

test("translated warning sentences join without duplicate punctuation", () => {
  assert.equal(I18n.joinSentences(["Some tasks were malformed.", "Some subtasks could not be found."]),
    "Some tasks were malformed. Some subtasks could not be found.")
  assert.equal(I18n.joinSentences(["第一句。", "第二句。"]), "第一句。 第二句。")
  assert.doesNotMatch(I18n.joinSentences(["Warning.", "Next."]), /\.\s*,/)
})

test("catalogs contain only canonical keys with matching placeholders", () => {
  const english = I18n.CATALOGS.en
  const placeholders = value => [...String(value).matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(match => match[1]).sort()
  for (const locale of I18n.SUPPORTED_LOCALES.slice(1)) {
    assert.deepEqual(Object.keys(I18n.RAW_OVERLAYS[locale]).sort(), Object.keys(english).sort(), `raw overlay ${locale}`)
    for (const key of Object.keys(english)) assert.deepEqual(placeholders(I18n.RAW_OVERLAYS[locale][key]), placeholders(english[key]), `raw overlay ${locale}:${key}`)
  }
  for (const locale of I18n.SUPPORTED_LOCALES) {
    assert.deepEqual(Object.keys(I18n.CATALOGS[locale]).sort(), Object.keys(english).sort(), locale)
    for (const key of Object.keys(english)) assert.deepEqual(placeholders(I18n.CATALOGS[locale][key]), placeholders(english[key]), `${locale}:${key}`)
  }
  assert.equal(Object.hasOwn(english, "panel.startingTask"), false)
  assert.equal(Object.hasOwn(english, "panel.a11y.numberRange"), false)
})

test("semantic protocol values map without changing unknown values", () => {
  assert.equal(I18n.warningText("de", "today-unavailable"), "Heutige Aufgaben sind nicht verfügbar.")
  assert.equal(I18n.warningText("de", "future-warning"), "future-warning")
  assert.equal(I18n.stateText("de", "failed"), "Fehlgeschlagen")
  assert.equal(I18n.stateText("fr", "future-state"), "future-state")
  assert.equal(I18n.stageText("de", "followup-verify"), "Nachfolgende Überprüfung")
  assert.equal(I18n.stageText("it", "future-stage"), "future-stage")
  assert.equal(I18n.resultText("de", {messageKey:"notification.scheduledNow",messageArgs:{title:"Plan"},message:"ignored"}), "Jetzt geplant: Plan")
  assert.equal(I18n.resultText("de", {messageKey:"task-started",message:"Task started"}), "Aufgabe gestartet")
  assert.equal(I18n.resultText("pl", {message:"Upstream diagnostic"}), "Upstream diagnostic")
  assert.equal(I18n.kindText("de", "extend"), "Verlängern")
  assert.equal(I18n.kindText("de", "future-kind"), "future-kind")
  assert.notEqual(I18n.requestErrorText("pl", "invalid-task-id"), "invalid-task-id")
  assert.equal(I18n.requestErrorText("pl", "upstream-error"), "upstream-error")
})

test("all backend semantic message keys are localized", () => {
  const keys = ["invalid-task-id","invalid-auto-next-window","malformed-requested-task","malformed-child-state","missing-child","no-unfinished-child","completed-task-remains-current","task-completed","auto-next-postcondition-failed","task-completed-and-next-started","parent-correction-postcondition-failed","task-completed-and-parent-stopped","completed-listed-task-remains-current","task-added-and-started"]
  for (const locale of I18n.SUPPORTED_LOCALES.slice(1)) {
    for (const key of keys) assert.notEqual(I18n.resultText(locale, {messageKey:key}), key, `${locale}:${key}`)
  }
})

test("remaining time and destructive actions use contextual translations", () => {
  const expected = {
    de:["Noch 5 min","Abschließen"], es:["Quedan 5 min","Completar"], fr:["5 min restantes","Terminer"],
    it:["5 min rimanenti","Completa"], "pt-BR":["Restam 5 min","Concluir"], nl:["Nog 5 min","Voltooien"],
    pl:["Pozostało 5 min","Ukończ"], hr:["Preostalo je 5 min","Dovrši"], "zh-CN":["剩余 5 min","完成"]
  }
  for (const [locale, [remaining, complete]] of Object.entries(expected)) {
    assert.equal(I18n.translate(locale, "panel.clock.left", {duration:"5 min"}), remaining)
    assert.equal(I18n.translate(locale, "panel.action.complete"), complete)
  }
})

test("semantic lookups reject inherited object keys", () => {
  for (const value of ["constructor", "toString", "__proto__"]) {
    assert.equal(I18n.warningText("de", value), value)
    assert.equal(I18n.stateText("de", value), value)
    assert.equal(I18n.stageText("de", value), value)
    assert.equal(I18n.kindText("de", value), value)
    assert.equal(I18n.requestErrorText("de", value), value)
    assert.equal(I18n.resultText("de", {messageKey:value, message:value}), value)
    assert.equal(I18n.resultText("de", {message:value}), value)
  }
})

test("Panel catalog templates preserve user content and named placeholders", () => {
  const task = "+Work #focus @tomorrow"
  assert.equal(I18n.translate("de", "panel.mutation.starting", {title:task}).includes(task), true)
  assert.equal(I18n.translate("zh-CN", "panel.idle.nextHint", {time:"09:30",title:task}).includes(task), true)
  assert.equal(I18n.translate("fr", "panel.feedback.withStage", {message:"Diagnostic",stage:"Validation"}), "Diagnostic · Validation")
})

test("every literal QML translation lookup uses a canonical catalog key", () => {
  for (const file of ["Panel.qml", "BarWidget.qml", "Service.qml"]) {
    const source = fs.readFileSync(path.join(__dirname, "..", file), "utf8")
    for (const match of source.matchAll(/\btr\("([^"]+)"/g)) {
      assert.equal(Object.hasOwn(I18n.CATALOGS.en, match[1]), true, `${file}:${match[1]}`)
    }
  }
})
