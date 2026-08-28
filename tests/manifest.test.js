const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const test = require("node:test")

const root = path.resolve(__dirname, "..")
const manifestPath = path.join(root, "manifest.json")
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"))
const serviceSource = fs.readFileSync(path.join(root, "Service.qml"), "utf8")
const barSource = fs.readFileSync(path.join(root, "BarWidget.qml"), "utf8")
const panelSource = fs.readFileSync(path.join(root, "Panel.qml"), "utf8")

test("manifest declares the publication contract", () => {
  assert.equal(manifest.schemaVersion, 1)
  assert.equal(manifest.id, "patrickfanella.superproductivity")
  assert.match(manifest.version, /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/)
  for (const field of ["name", "author", "description"]) {
    assert.equal(typeof manifest[field], "string", `${field} must be a string`)
    assert.ok(manifest[field].trim(), `${field} must not be empty`)
  }
  assert.equal(manifest.license, "MIT")
  assert.deepEqual(manifest.kinds, ["service", "bar-widget"])
  assert.deepEqual(manifest.entryPoints, {
    service: "Service.qml",
    barWidget: "BarWidget.qml"
  })
})

test("manifest entry points are safe existing files", () => {
  for (const [kind, entryPoint] of Object.entries(manifest.entryPoints)) {
    assert.equal(path.isAbsolute(entryPoint), false, `${kind} entry point must be relative`)
    assert.equal(entryPoint.split(/[\\/]/).includes(".."), false, `${kind} entry point must not contain ..`)
    assert.equal(fs.statSync(path.join(root, entryPoint)).isFile(), true, `${kind} entry point must exist`)
  }
})

test("service does not depend on Shell Settings", () => {
  assert.doesNotMatch(serviceSource, /shell\.settings/)
  assert.doesNotMatch(serviceSource, /callIfLoaded/)
  assert.doesNotMatch(serviceSource, /function\s+openSettings\s*\(/)
  assert.doesNotMatch(serviceSource, /function\s+settings\s*\(/)
})

test("Today row activation never starts tracking", () => {
  const activation = panelSource.match(/function activate\(\) \{([\s\S]*?)\n\s*\}/)
  assert.ok(activation, "Today row activate function must exist")
  assert.doesNotMatch(activation[1], /startTodayTask/)
  assert.match(panelSource, /onClicked: root\.startTodayTask\(todayRow\.modelData\)/)
})

test("sound previews queue immutable volume snapshots", () => {
  assert.match(serviceSource, /previewQueue = previewQueue\.concat\(\[parsed\.value\]\)/)
  assert.match(serviceSource, /var volume = previewQueue\[0\]/)
  assert.match(serviceSource, /args\.push\("--volume", String\(volume\)\)/)
  assert.match(serviceSource, /args\.push\("--volume", String\(alertVolume\)\)/)
})

test("service and bar use the runtime localization catalog", () => {
  assert.match(serviceSource, /import "I18n\.js" as I18n/)
  assert.match(barSource, /import "I18n\.js" as I18n/)
  assert.match(serviceSource, /localeName:\s*I18n\.resolveLocale\(Qt\.locale\(\)\.name\)/)
  assert.match(serviceSource, /function tr\(key, args\)/)
  assert.match(barSource, /engine\.localeName[\s\S]*I18n\.resolveLocale\(Qt\.locale\(\)\.name\)/)
})

test("notification bodies are translated without changing alert protocol values", () => {
  assert.match(serviceSource, /I18n\.warningText\(localeName, code\)/)
  assert.match(serviceSource, /tr\("notification\.scheduledNow", \{ title:/)
  assert.match(serviceSource, /tr\("notification\.timerExpired"\)/)
  assert.match(serviceSource, /args\.push\("--", currentAlert\.title\)/)
  assert.match(serviceSource, /args\.push\("--notification-title", tr\("notification\.title"\)\)/)
  assert.match(serviceSource, /testProcess\.command = \[\s*helperPath, "test-notification", "--urgency", notificationUrgency,[\s\S]*"--notification-title", tr\("notification\.title"\),[\s\S]*"--body", tr\("notification\.testBody"\)[\s\S]*\]/)
})

test("localized service display values do not replace English IPC fields", () => {
  assert.match(serviceSource, /error:\s*root\.ipcErrorText/)
  assert.match(serviceSource, /alertError:\s*root\.ipcAlertError/)
  assert.match(serviceSource, /previewMessage:\s*root\.ipcPreviewMessage/)
  assert.match(serviceSource, /testNotificationMessage:\s*root\.ipcTestNotificationMessage/)
  assert.match(serviceSource, /contextWarning:\s*root\.contextWarning/)
  assert.match(serviceSource, /message: "Super Productivity helper could not be started"/)
  assert.match(serviceSource, /messageKey: "helper-start-failed"/)
})

test("panel routes display text through runtime localization", () => {
  assert.match(panelSource, /import "I18n\.js" as I18n/)
  assert.match(panelSource, /engine\.localeName[\s\S]*I18n\.resolveLocale\(Qt\.locale\(\)\.name\)/)
  assert.match(panelSource, /function tr\(key, args\)/)
  assert.match(panelSource, /I18n\.warningText\(localeName, code\)/)
  assert.match(panelSource, /I18n\.resultText\(localeName, result\)/)
  assert.match(panelSource, /I18n\.stateText\(localeName, state\)/)
  assert.match(panelSource, /I18n\.stageText\(localeName, stage\)/)
  assert.match(panelSource, /I18n\.kindText\(localeName, kind\)/)
  assert.match(panelSource, /I18n\.requestErrorText\(localeName, error\)/)
})

test("panel separates resolved translation locale from raw system date formatting locale", () => {
  assert.doesNotMatch(panelSource, /resultState\.toUpperCase\(\)/)
  assert.doesNotMatch(panelSource, /Accessible\.name:\s*resultState\s*\+/)
  assert.match(panelSource, /localeName:[\s\S]*I18n\.resolveLocale\(Qt\.locale\(\)\.name\)/)
  assert.match(panelSource, /formattingLocale:\s*Qt\.locale\(\)/)
  assert.match(panelSource, /formattingLocale\.toString\(new Date\(stamp\), Locale\.ShortFormat\)/)
  assert.match(panelSource, /formattingLocale\.timeFormat\(Locale\.ShortFormat\)/)
  assert.doesNotMatch(panelSource, /Qt\.locale\(localeName\)/)
  assert.doesNotMatch(panelSource, /toString\(new Date\(nextScheduledStartMs\), "t"\)/)
  assert.match(panelSource, /new Date\(Number\(match\[1\]\), Number\(match\[2\]\) - 1, Number\(match\[3\]\)\)/)
  assert.match(panelSource, /formattingLocale\.dateFormat\(Locale\.ShortFormat\)/)
  assert.match(panelSource, /resultState:\s*root\.mutationState/)
})

test("bar separates resolved translation locale from raw system time formatting locale", () => {
  assert.match(barSource, /localeName:[\s\S]*I18n\.resolveLocale\(Qt\.locale\(\)\.name\)/)
  assert.match(barSource, /formattingLocale:\s*Qt\.locale\(\)/)
  assert.match(barSource, /formattingLocale\.timeFormat\(Locale\.ShortFormat\)/)
  assert.doesNotMatch(barSource, /Qt\.locale\(localeName\)/)
  assert.doesNotMatch(barSource, /Model\.formatStartTime\(nextScheduledStartMs\)/)
  assert.doesNotMatch(barSource, /HH:mm/)
})

test("warnings and settings ranges use whole localized templates", () => {
  assert.match(serviceSource, /I18n\.joinSentences/)
  assert.match(panelSource, /I18n\.joinSentences/)
  assert.doesNotMatch(panelSource, /numberSetting\.description \+ " · "/)
  assert.match(panelSource, /tr\("panel\.setting\.rangeSummary"/)
})

test("panel uses canonical catalog keys only", () => {
  assert.doesNotMatch(panelSource, /tr\("panel\.a11y\./)
  for (const alias of ["panel.dueDay", "panel.timeLeft", "panel.settingsTitle", "panel.quickAdd", "panel.today"]) {
    assert.equal(panelSource.includes(`tr("${alias}")`), false, alias)
  }
})

test("panel keeps user and protocol content outside translation", () => {
  assert.match(panelSource, /placeholderText: "Write report 30m \+Work #focus @tomorrow"/)
  assert.match(panelSource, /text: "\+project, @schedule, #tag"/)
  assert.match(panelSource, /settingKey: "pollSeconds"/)
  assert.match(panelSource, /root\.engine\.mutationKind === "stop"/)
  assert.match(panelSource, /resultState === "failed"/)
  assert.match(panelSource, /elide: Text\.ElideRight/)
  assert.match(panelSource, /fittedContentWidth\(Style\.space\(420\)\)/)
  assert.match(panelSource, /fittedContentHeight\(content\.implicitHeight, Style\.space\(620\)\)/)
})
