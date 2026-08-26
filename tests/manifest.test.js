const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const test = require("node:test")

const root = path.resolve(__dirname, "..")
const manifestPath = path.join(root, "manifest.json")
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"))
const serviceSource = fs.readFileSync(path.join(root, "Service.qml"), "utf8")
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
