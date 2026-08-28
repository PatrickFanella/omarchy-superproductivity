const assert = require("node:assert/strict")
const test = require("node:test")
const fs = require("node:fs")
const path = require("node:path")
const Model = require("../Model.js")

test("normalizes helper status and derives remaining time", () => {
  const task = { title: "Write report", timeEstimate: 600000, timeSpent: 120000 }
  assert.deepEqual(Model.normalizeStatus({ ok: true, currentTask: task }), {
    ok: true,
    currentTask: task,
    todayTasks: [],
    scheduledTasks: null,
    todayFetchedAt: null,
    fetchedAt: 0,
    signedRemainingMs: 480000,
    remainingMs: 480000,
    overtimeMs: 0,
    context: { todayOk: false, projectsOk: false, tasksOk: false, warnings: [] },
    error: "",
    message: ""
  })
})

test("normalizes today tasks and fetch timestamp", () => {
  const todayTasks = [{ id: "one" }, { id: "two" }]
  const status = Model.normalizeStatus({ ok: true, task: null, todayTasks, fetchedAt: 1234 })
  assert.equal(status.currentTask, null)
  assert.equal(status.todayTasks, todayTasks)
  assert.equal(status.fetchedAt, 1234)
  assert.deepEqual(Model.normalizeStatus({ todayTasks: "bad", fetchedAt: -1 }).todayTasks, [])
  assert.equal(Model.normalizeStatus({ fetchedAt: -1 }).fetchedAt, 0)
})

test("normalizes all status context capabilities", () => {
  const context = Model.normalizeStatus({
    context: { todayOk: true, projectsOk: true, tasksOk: true, warnings: ["missing-child"] }
  }).context
  assert.deepEqual(context, {
    todayOk: true, projectsOk: true, tasksOk: true, warnings: ["missing-child"]
  })
})

test("normalizes wrapped API status", () => {
  const task = { title: "Focus" }
  assert.equal(Model.normalizeStatus({ ok: true, data: { currentTask: task, remainingMs: -4 } }).remainingMs, 0)
})

test("formats durations for QML labels", () => {
  assert.equal(Model.formatRemaining(0), "0:00")
  assert.equal(Model.formatRemaining(1), "0:01")
  assert.equal(Model.formatRemaining(480000), "8:00")
  assert.equal(Model.formatRemaining(3723000), "1:02:03")
  assert.equal(Model.clampRemaining(-1), 0)
  assert.equal(Model.clampRemaining(500), 500)
  assert.equal(Model.formatOvertime(61001), "+1:02")
})

test("projects signed remaining time through overtime", () => {
  assert.equal(Model.projectSignedRemaining(1000, 5000, 6500), -500)
  assert.deepEqual(Model.timeViews(-500), {
    signedRemainingMs: -500,
    remainingMs: 0,
    overtimeMs: 500,
    timerExpired: true
  })
})

test("side effect state requires a successful exit and parsed success reply", () => {
  assert.equal(Model.sideEffectState(0, { ok: true }), "succeeded")
  assert.equal(Model.sideEffectState(1, { ok: true }), "failed")
  assert.equal(Model.sideEffectState(0, { ok: false }), "failed")
  assert.equal(Model.sideEffectState(0, null), "failed")
})

test("search keeps matching child parent and runnable order skips container parents", () => {
  const tasks = [
    { id: "p", title: "Plan", depth: 0, subTaskIds: ["c"], isDone: false },
    { id: "c", title: "Write", projectTitle: "Work", parentId: "p", depth: 1, isDone: false },
    { id: "solo", title: "Call", depth: 0, isDone: false },
    { id: "done", title: "Done", depth: 0, isDone: true }
  ]
  assert.deepEqual(Model.runnableOrder(tasks).map(task => task.id), ["c", "solo"])
  assert.deepEqual(Model.searchHierarchy(tasks, "write").map(task => task.id), ["p", "c"])
})

test("chronological hierarchy matches the shared block-order fixture without mutation", () => {
  const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "chronological-hierarchy.json"), "utf8"))
  const before = JSON.stringify(fixture.tasks)
  const ordered = Model.chronologicalHierarchy(fixture.tasks)
  assert.deepEqual(ordered.map(task => task.id), fixture.expectedIds)
  assert.equal(JSON.stringify(fixture.tasks), before)
  assert.equal(ordered.find(task => task.id === "orphan-late").depth, 0)
  assert.notEqual(ordered[0], fixture.tasks[5])
})

test("chronological hierarchy is prototype-safe and keeps unlisted children as blocks", () => {
  const tasks = [
    { id: "constructor", title: "Parent", dueWithTime: 2, subTaskIds: ["__proto__"] },
    { id: "__proto__", title: "Child", parentId: "constructor", dueWithTime: 1 },
    { id: "toString", title: "Orphan", parentId: "constructor", dueWithTime: 0 }
  ]
  assert.deepEqual(Model.chronologicalHierarchy(tasks).map(task => task.id), [
    "constructor", "__proto__", "toString"
  ])
  assert.equal(Model.chronologicalHierarchy(tasks)[2].depth, 0)
})

test("search matches parents whose IDs are object prototype keys", () => {
  const reservedIds = ["constructor", "toString", "__proto__"]
  const tasks = reservedIds.flatMap(id => [
    { id, title: `Parent ${id}` },
    { id: `child-${id}`, title: "Reserved match", parentId: id }
  ])

  assert.deepEqual(
    Model.searchHierarchy(tasks, "reserved match").map(task => task.id),
    reservedIds.flatMap(id => [id, `child-${id}`])
  )
})

test("runnable order skips retained containers without visible runnable children", () => {
  const tasks = [
    { id: "missing", depth: 0, subTaskIds: ["absent"], isDone: false },
    { id: "conflicting", depth: 0, subTaskIds: ["owned-elsewhere"], isDone: false },
    { id: "done-hidden", depth: 0, subTaskIds: ["done"], isDone: false },
    { id: "solo", depth: 0, subTaskIds: [], isDone: false }
  ]
  assert.deepEqual(Model.runnableOrder(tasks).map(task => task.id), ["solo"])
})

test("shortens plain titles and builds bar label", () => {
  assert.equal(Model.displayTitle({ title: "  A   long title  " }, 8), "A long…")
  assert.equal(Model.displayTitle(null, 20), "Untitled task")
  assert.equal(Model.displayTitle({ title: "" }, 20, "Unbenannte Aufgabe"), "Unbenannte Aufgabe")
  assert.equal(Model.displayTitle({ title: " \t\n " }, 20, "Tâche sans titre"), "Tâche sans titre")
  assert.equal(Model.displayTitle(null, 8, "Tarea sin título"), "Tarea s…")
  assert.match(Model.barLabel({ title: "Focus" }, 300000), /Focus  5:00$/)
  assert.match(Model.barLabel({ title: "   " }, 300000, "未命名任务"), /未命名任务  5:00$/)
})

const idle = { taskId: null, phase: "idle", positiveCount: 0 }
const estimated = { id: "task", timeEstimate: 100 }

test("expiry stays idle without an estimated task", () => {
  assert.deepEqual(Model.advanceExpiry(idle, null, 0), {
    state: idle, shouldAlert: false, expired: false
  })
  assert.deepEqual(Model.advanceExpiry(idle, { id: "task", timeEstimate: 0 }, 0), {
    state: { taskId: "task", phase: "idle", positiveCount: 0 },
    shouldAlert: false,
    expired: false
  })
})

test("new task arms when positive and starts expired at zero without alert", () => {
  assert.deepEqual(Model.advanceExpiry(idle, estimated, 10), {
    state: { taskId: "task", phase: "armed", positiveCount: 0 },
    shouldAlert: false,
    expired: false
  })
  assert.deepEqual(Model.advanceExpiry(idle, estimated, 0), {
    state: { taskId: "task", phase: "expired", positiveCount: 0 },
    shouldAlert: false,
    expired: true
  })
})

test("armed positive to zero alerts exactly once", () => {
  const armed = { taskId: "task", phase: "armed", positiveCount: 0 }
  const first = Model.advanceExpiry(armed, estimated, 0)
  assert.equal(first.shouldAlert, true)
  assert.equal(first.expired, true)
  const second = Model.advanceExpiry(first.state, estimated, 0)
  assert.equal(second.shouldAlert, false)
  assert.equal(second.state.phase, "expired")
})

test("expired task rearms on the first authoritative positive sample", () => {
  const expired = { taskId: "task", phase: "expired", positiveCount: 0 }
  const rearmed = Model.advanceExpiry(expired, estimated, 20)
  assert.deepEqual(rearmed, {
    state: { taskId: "task", phase: "armed", positiveCount: 0 },
    shouldAlert: false,
    expired: false
  })
})

test("short extension can expire and alert again", () => {
  const expired = { taskId: "task", phase: "expired", positiveCount: 0 }
  const rearmed = Model.advanceExpiry(expired, estimated, 1)
  const expiredAgain = Model.advanceExpiry(rearmed.state, estimated, 0)
  assert.equal(expiredAgain.shouldAlert, true)
  assert.equal(expiredAgain.expired, true)
  assert.equal(expiredAgain.state.phase, "expired")
})

test("task change resets expiry state", () => {
  const expired = { taskId: "old", phase: "expired", positiveCount: 0 }
  const next = Model.advanceExpiry(expired, { id: "new", timeEstimate: 100 }, 5)
  assert.equal(next.state.phase, "armed")
  assert.equal(next.state.taskId, "new")
  assert.equal(next.shouldAlert, false)
})

function scheduled(id, dueWithTime, values = {}) {
  return { id, title: id, dueWithTime, isDone: false, parentId: null, ...values }
}

const emptySchedule = { initialized: false, cursorMs: 0, seenKeys: [] }

test("schedule status keeps fresh data distinct from a failed Today sample", () => {
  const fresh = Model.normalizeStatus({ scheduledTasks: [scheduled("one", 10)], todayFetchedAt: 20 })
  assert.equal(fresh.scheduledTasks[0].id, "one")
  assert.equal(fresh.todayFetchedAt, 20)
  const failed = Model.normalizeStatus({ scheduledTasks: null, todayFetchedAt: null })
  assert.equal(failed.scheduledTasks, null)
  assert.equal(failed.todayFetchedAt, null)
})

test("first schedule sample baselines already-due work without alerting", () => {
  const result = Model.reduceSchedule(emptySchedule, [scheduled("past", 90), scheduled("future", 110)], 100, null)
  assert.deepEqual(result.alerts, [])
  assert.equal(result.state.cursorMs, 100)
  assert.deepEqual(result.state.seenKeys, [Model.scheduledKey(scheduled("past", 90))])
})

test("schedule crossings alert the earliest task while idle", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 100, null).state
  const tasks = [scheduled("later", 160), scheduled("first", 150), scheduled("same-time", 150)]
  const idleSample = Model.reduceSchedule(baseline, tasks, 170, null)
  assert.deepEqual(idleSample.alerts.map(task => task.id), ["first"])
  assert.equal(idleSample.state.seenKeys.length, 3)
})

test("schedule crossing suppresses the exact current task and marks it seen", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 100, null).state
  const task = scheduled("current", 150)
  const result = Model.reduceSchedule(baseline, [task], 170, { id: "current" })
  assert.deepEqual(result.alerts, [])
  assert.deepEqual(result.state.seenKeys, [Model.scheduledKey(task)])
})

test("schedule crossing suppresses the current child's scheduled parent", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 100, null).state
  const task = scheduled("parent", 150)
  const result = Model.reduceSchedule(baseline, [task], 170, { id: "child", parentId: "parent" })
  assert.deepEqual(result.alerts, [])
  assert.deepEqual(result.state.seenKeys, [Model.scheduledKey(task)])
})

test("schedule crossing alerts while an unrelated task is current", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 100, null).state
  const result = Model.reduceSchedule(baseline, [scheduled("scheduled", 150)], 170, { id: "other" })
  assert.deepEqual(result.alerts.map(task => task.id), ["scheduled"])
})

test("mixed simultaneous crossings skip current work and alert the earliest unrelated task", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 100, null).state
  const tasks = [scheduled("current", 150), scheduled("unrelated", 150), scheduled("later", 160)]
  const result = Model.reduceSchedule(baseline, tasks, 170, { id: "current" })
  assert.deepEqual(result.alerts.map(task => task.id), ["unrelated"])
  assert.equal(result.state.seenKeys.length, 3)
})

test("schedule crossing interval excludes the cursor and includes the sample", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 100, null).state
  const result = Model.reduceSchedule(baseline, [scheduled("at-cursor", 100), scheduled("at-sample", 200)], 200, null)
  assert.deepEqual(result.alerts.map(task => task.id), ["at-sample"])
  assert.equal(result.state.seenKeys.length, 2)
})

test("failed samples and suspend-like gaps do not replay schedule alerts", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 100, null).state
  const failed = Model.reduceSchedule(baseline, null, null, null)
  assert.equal(failed.state, baseline)
  const resumed = Model.reduceSchedule(failed.state, [scheduled("crossed", 150)], 1000, null)
  assert.deepEqual(resumed.alerts.map(task => task.id), ["crossed"])
  assert.deepEqual(Model.reduceSchedule(resumed.state, [scheduled("crossed", 150)], 1010, null).alerts, [])
})

test("newly observed overdue tasks are consumed without backfill alerts", () => {
  const baseline = Model.reduceSchedule(emptySchedule, [], 200, null).state
  const result = Model.reduceSchedule(baseline, [scheduled("new-old", 150)], 210, null)
  assert.deepEqual(result.alerts, [])
  assert.equal(result.state.seenKeys.length, 1)
})

test("clock rollback safely rebaselines and later day-like replacement crosses once", () => {
  let state = { initialized: true, cursorMs: 1000, seenKeys: [] }
  let result = Model.reduceSchedule(state, [scheduled("rollback-old", 400), scheduled("future", 700)], 500, null)
  assert.deepEqual(result.alerts, [])
  assert.equal(result.state.cursorMs, 500)
  assert.equal(result.state.seenKeys.length, 1)
  result = Model.reduceSchedule(result.state, [scheduled("next-day", 650)], 700, null)
  assert.deepEqual(result.alerts.map(task => task.id), ["next-day"])
})

test("schedule ledger is FIFO, capped at 128, and keys do not concatenate-collide", () => {
  const tasks = Array.from({ length: 129 }, (_, index) => scheduled(String(index), index + 1))
  const result = Model.reduceSchedule(emptySchedule, tasks, 200, null)
  assert.equal(result.state.seenKeys.length, 128)
  assert.equal(result.state.seenKeys[0], Model.scheduledKey(tasks[1]))
  assert.notEqual(Model.scheduledKey(scheduled("a,b", 1)), Model.scheduledKey(scheduled("a", "b,1")))
  assert.notEqual(Model.scheduledKey(scheduled("__proto__", 1)), Model.scheduledKey(scheduled("constructor", 1)))
})

test("next scheduled task filters invalid, done, child, and already-started entries", () => {
  const tiedFirst = scheduled("first", 200)
  const tiedSecond = scheduled("second", 200)
  const tasks = [
    scheduled("past", 100), scheduled("done", 150, { isDone: true }),
    scheduled("child", 160, { parentId: "parent" }), scheduled("bad", Infinity),
    scheduled("string", "120"), tiedFirst, tiedSecond, scheduled("later", 300)
  ]
  assert.equal(Model.nextScheduledTask(tasks, 100), tiedFirst)
  assert.equal(Model.nextScheduledTask(tasks, 300), null)
})

test("formats scheduled starts at local minute boundaries", () => {
  const value = new Date(2026, 0, 2, 3, 4, 59, 999).getTime()
  assert.equal(Model.formatStartTime(value), "03:04")
  assert.equal(Model.formatStartTime(NaN), "")
})

test("alert queue prioritizes timers, expires scheduled alerts, and stays bounded", () => {
  let queue = []
  for (let index = 0; index < 16; index++)
    queue = Model.enqueueAlert(queue, { kind: "scheduled", title: String(index), queuedAt: index }, 16)
  queue = Model.enqueueAlert(queue, { kind: "timer", title: "new timer", queuedAt: 20 }, 16)
  assert.equal(queue.length, 16)
  assert.equal(queue.some(alert => alert.title === "0"), false)
  assert.equal(Model.takeNextAlert(queue, 20).alert.title, "new timer")
  assert.equal(Model.takeNextAlert([{ kind: "scheduled", queuedAt: 0 }], 300000).alert, null)
})
