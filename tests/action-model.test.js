const assert = require("node:assert/strict")
const test = require("node:test")
const Actions = require("../ActionModel.js")

function request(id, queuedAt = 0) {
  return { id, kind: "start", taskId: "task", queuedAt }
}

function reply(overrides = {}) {
  return {
    kind: "start",
    targetTaskId: "task",
    state: "succeeded",
    stage: "done",
    mutationApplied: true,
    expectedCurrentId: null,
    observedCurrentId: "task",
    finalCurrentId: "task",
    raceDetected: false,
    createdTaskId: null,
    message: "Started",
    ...overrides
  }
}

test("request IDs contain the service start and counter", () => {
  assert.equal(Actions.requestId(1234.9, 7), "1234-7")
})

test("quick Add starts only for the add-switch setting", () => {
  assert.equal(Actions.quickAddStartsAfter("add-switch"), true)
  for (const value of [undefined, null, "", "add", "ADD-SWITCH", true, false, 1])
    assert.equal(Actions.quickAddStartsAfter(value), false)
})

test("quick Add switch setting migrates only explicit booleans", () => {
  assert.equal(Actions.quickAddSwitch(true, "add"), true)
  assert.equal(Actions.quickAddSwitch(false, "add-switch"), false)
  assert.equal(Actions.quickAddSwitch("true", "add-switch"), true)
  assert.equal(Actions.quickAddSwitch(null, "add"), false)
  assert.equal(Actions.quickAddSwitch(undefined, undefined), false)
})

test("top-level bar settings override legacy nested settings", () => {
  const entry = {
    quickAddSwitch: false,
    quickAddEnterAction: "add-switch",
    settings: { quickAddSwitch: true, quickAddEnterAction: "add-switch", pollSeconds: 9 }
  }
  assert.equal(Actions.settingValue(entry, "quickAddSwitch", true), false)
  assert.equal(Actions.settingValue(entry, "quickAddEnterAction", ""), "add-switch")
  assert.equal(Actions.settingValue(entry, "pollSeconds", 5), 9)
  assert.equal(Actions.settingValue({ quickAddSwitch: null, settings: { quickAddSwitch: true } }, "quickAddSwitch", false), false)
})

test("integer settings validate integers and clamp config values", () => {
  for (const volume of [0, 50, 100])
    assert.equal(Actions.integerSetting({ alertVolume: volume }, "alertVolume", 100, 0, 100), volume)
  assert.equal(Actions.integerSetting({ alertVolume: -1 }, "alertVolume", 100, 0, 100), 0)
  assert.equal(Actions.integerSetting({ alertVolume: 101 }, "alertVolume", 100, 0, 100), 100)
  for (const value of ["", false, "50.5", "nope", Infinity])
    assert.equal(Actions.integerSetting({ alertVolume: value }, "alertVolume", 100, 0, 100), 100)
})

test("auto-next window requires a bounded strict integer", () => {
  for (const value of [1, 30, 1440])
    assert.equal(Actions.strictIntegerSetting({ autoNextWindowMinutes: value }, "autoNextWindowMinutes", 30, 1, 1440), value)
  for (const value of [0, 1441, true, false, "30", "1.5", "NaN", NaN, Infinity, null])
    assert.equal(Actions.strictIntegerSetting({ autoNextWindowMinutes: value }, "autoNextWindowMinutes", 30, 1, 1440), 30)
})

test("preview volume snapshots strict explicit values and config fallback", () => {
  for (const value of [0, 37, 100])
    assert.deepEqual(Actions.previewVolume(value, 75), { ok: true, value })
  assert.deepEqual(Actions.previewVolume(undefined, 75), { ok: true, value: 75 })
  for (const value of [-1, 101, 1.5, "50", true, null, NaN, Infinity])
    assert.deepEqual(Actions.previewVolume(value, 75), { ok: false, error: "invalid-volume" })
  assert.deepEqual(Actions.previewVolume(undefined, "75"), { ok: false, error: "invalid-volume" })
})

test("complete command includes the configured window only with auto-next", () => {
  assert.deepEqual(Actions.completeCommand("/helper", "task", false, 45), ["/helper", "complete", "task"])
  assert.deepEqual(Actions.completeCommand("/helper", "task", true, 45), [
    "/helper", "complete", "task", "--auto-next", "--auto-next-window", "45"
  ])
})

test("queue accepts 16 pending plus one running and rejects overflow", () => {
  let queue = []
  for (let index = 0; index < 16; index++) {
    const added = Actions.enqueue(queue, request("running"), request(String(index)))
    assert.equal(added.accepted, true)
    queue = added.queue
  }
  assert.deepEqual(Actions.enqueue(queue, request("running"), request("overflow")), {
    accepted: false,
    error: "queue-full",
    queue
  })
})

test("expired requests fail before the next request dispatches", () => {
  const taken = Actions.takeNext([request("old", 0), request("next", 1000)], 30001)
  assert.equal(taken.expired.length, 1)
  assert.equal(taken.expired[0].state, "failed")
  assert.equal(taken.expired[0].stage, "queue")
  assert.equal(taken.expired[0].mutationApplied, false)
  assert.equal(taken.request.id, "next")
})

test("structured partial and unknown outcomes survive normalization", () => {
  const partial = Actions.normalizeResult(request("one"), reply({
    state: "partial", stage: "verify", finalCurrentId: "other", message: "Mismatch"
  }), 1, 50)
  assert.equal(partial.ok, false)
  assert.equal(partial.state, "partial")
  assert.equal(partial.finalCurrentId, "other")
  const unknown = Actions.normalizeResult(request("two"), null, 1, 60)
  assert.equal(unknown.state, "unknown")
  assert.equal(unknown.mutationApplied, null)
  assert.equal(unknown.expectedCurrentId, null)
  assert.equal(unknown.observedCurrentId, null)
  assert.equal(unknown.finalCurrentId, null)
  assert.equal(unknown.raceDetected, false)
  assert.equal(unknown.createdTaskId, null)
  assert.equal(unknown.message, "Super Productivity returned an invalid action result")
})

test("primary verify-unknown backend outcome survives normalization", () => {
  const backendReply = {
    ok: false,
    kind: "start",
    targetTaskId: "task",
    state: "unknown",
    stage: "verify",
    mutationApplied: true,
    expectedCurrentId: null,
    observedCurrentId: "other",
    finalCurrentId: "other",
    raceDetected: true,
    createdTaskId: null,
    message: "Unexpected current task",
    actualTaskId: "task"
  }
  const result = Actions.normalizeResult(request("verify"), backendReply, 1, 60)
  assert.equal(result.state, "unknown")
  assert.equal(result.stage, "verify")
  assert.equal(result.mutationApplied, true)
  assert.equal(result.observedCurrentId, "other")
  assert.equal(result.finalCurrentId, "other")
  assert.equal(result.raceDetected, true)
  assert.equal(result.actualTaskId, "task")
  assert.equal(result.message, "Unexpected current task")
})

test("add-and-switch followup verify-unknown backend outcome survives normalization", () => {
  const actionRequest = { id: "add-switch", kind: "add", queuedAt: 0 }
  const backendReply = {
    ok: false,
    kind: "add",
    targetTaskId: "created",
    state: "unknown",
    stage: "followup-verify",
    mutationApplied: true,
    expectedCurrentId: "previous",
    observedCurrentId: "previous",
    finalCurrentId: "external",
    raceDetected: true,
    createdTaskId: "created",
    message: "Unexpected current task",
    followupMutationApplied: true
  }

  assert.deepEqual(Actions.normalizeResult(actionRequest, backendReply, 1, 60), {
    ...backendReply,
    requestId: "add-switch",
    ok: false,
    exitCode: 1,
    finishedAt: 60
  })
})

test("normalization accepts only declared states, stages, and outcome combinations", () => {
  const valid = [
    reply(),
    reply({ state: "partial", stage: "followup-verify" }),
    reply({ state: "conflict", stage: "preflight", mutationApplied: false }),
    reply({ state: "failed", stage: "validation", mutationApplied: false }),
    reply({ state: "unknown", stage: "dispatch", mutationApplied: null }),
    reply({ state: "unknown", stage: "verify", mutationApplied: true }),
    reply({ state: "unknown", stage: "followup-dispatch", followupMutationApplied: null }),
    reply({ state: "unknown", stage: "followup-verify", followupMutationApplied: true })
  ]
  for (const source of valid)
    assert.equal(Actions.normalizeResult(request("valid"), source, 0, 1).message, source.message)

  const invalid = [
    reply({ state: "invented" }),
    reply({ stage: "invented" }),
    reply({ state: "succeeded", mutationApplied: false }),
    reply({ state: "partial", mutationApplied: null }),
    reply({ state: "conflict", mutationApplied: true }),
    reply({ state: "failed", mutationApplied: null }),
    reply({ state: "unknown", mutationApplied: false }),
    reply({ state: "unknown", mutationApplied: null, followupMutationApplied: true }),
    reply({ state: "unknown", followupMutationApplied: true }),
    reply({ state: "unknown", stage: "dispatch", mutationApplied: true }),
    reply({ state: "unknown", stage: "verify", mutationApplied: true, followupMutationApplied: null }),
    reply({ state: "unknown", stage: "followup-dispatch", followupMutationApplied: true }),
    reply({ state: "unknown", stage: "followup-verify", followupMutationApplied: false }),
    reply({ raceDetected: "false" }),
    reply({ kind: "stop" })
  ]
  for (const source of invalid) {
    const result = Actions.normalizeResult(request("invalid"), source, 1, 2)
    assert.equal(result.state, "unknown")
    assert.equal(result.message, "Super Productivity returned an invalid action result")
  }
})

test("normalization rejects replies missing any common field", () => {
  const common = [
    "kind", "targetTaskId", "state", "stage", "mutationApplied", "expectedCurrentId",
    "observedCurrentId", "finalCurrentId", "raceDetected", "createdTaskId", "message"
  ]
  for (const field of common) {
    const source = reply()
    delete source[field]
    assert.equal(Actions.normalizeResult(request(field), source, 1, 2).state, "unknown")
  }
})

test("raw status validation runs against required backend fields", () => {
  const status = {
    ok: true,
    task: { id: "task" },
    todayTasks: [{ id: "today" }],
    scheduledTasks: [{ id: "scheduled", dueWithTime: 456 }],
    todayFetchedAt: 122,
    fetchedAt: 123,
    signedRemainingMs: -50,
    context: { todayOk: true, projectsOk: true, tasksOk: true, warnings: [] }
  }
  assert.equal(Actions.validRawStatus(status), true)
  assert.equal(Actions.validRawStatus({ ...status, task: null, signedRemainingMs: null }), true)
  assert.equal(Actions.validRawStatus({ ...status, fetchedAt: 0 }), false)
  assert.equal(Actions.validRawStatus({ ...status, fetchedAt: "123" }), false)
  assert.equal(Actions.validRawStatus({ ...status, signedRemainingMs: null }), false)
  assert.equal(Actions.validRawStatus({ ...status, context: null }), false)
  assert.equal(Actions.validRawStatus({ ...status, todayTasks: null }), false)
  assert.equal(Actions.validRawStatus({ ...status, todayTasks: [null] }), false)
  assert.equal(Actions.validRawStatus({ ...status, context: { ...status.context, tasksOk: "yes" } }), false)
  assert.equal(Actions.validRawStatus({ ...status, context: { ...status.context, warnings: [1] } }), false)
  const missingTask = { ...status }
  delete missingTask.task
  assert.equal(Actions.validRawStatus(missingTask), false)
})

test("raw status requires schedule fields coherent with Today context", () => {
  const fresh = {
    ok: true,
    task: null,
    todayTasks: [],
    scheduledTasks: [],
    todayFetchedAt: 123,
    fetchedAt: 124,
    signedRemainingMs: null,
    context: { todayOk: true, projectsOk: true, tasksOk: true, warnings: [] }
  }
  assert.equal(Actions.validRawStatus(fresh), true)
  assert.equal(Actions.hasFreshScheduleContext(fresh), true)

  for (const fields of [
    { scheduledTasks: null },
    { scheduledTasks: {} },
    { todayFetchedAt: null },
    { todayFetchedAt: 0 },
    { todayFetchedAt: -1 },
    { todayFetchedAt: Infinity },
    { todayFetchedAt: "123" }
  ]) {
    const malformed = { ...fresh, ...fields }
    assert.equal(Actions.validRawStatus(malformed), false)
    assert.equal(Actions.hasFreshScheduleContext(malformed), false)
  }

  const failedToday = {
    ...fresh,
    scheduledTasks: null,
    todayFetchedAt: null,
    context: { ...fresh.context, todayOk: false }
  }
  delete failedToday.todayTasks
  assert.equal(Actions.validRawStatus(failedToday), true)
  assert.equal(Actions.hasFreshScheduleContext(failedToday), false)
  assert.equal(Actions.validRawStatus({ ...failedToday, scheduledTasks: [] }), false)
  assert.equal(Actions.validRawStatus({ ...failedToday, todayFetchedAt: 123 }), false)
  assert.equal(Actions.validRawStatus({ ...failedToday, scheduledTasks: undefined }), false)
  assert.equal(Actions.validRawStatus({ ...failedToday, todayFetchedAt: undefined }), false)
})

test("malformed raw status is rejected before context merge", () => {
  const previous = {
    currentTask: { id: "current", projectTitle: "Work" },
    todayTasks: [{ id: "old", title: "Old" }]
  }
  const malformed = {
    ok: true,
    task: null,
    todayTasks: "not-an-array",
    fetchedAt: 123,
    signedRemainingMs: null,
    context: { todayOk: true, projectsOk: false, tasksOk: false, warnings: [] }
  }
  const result = Actions.validRawStatus(malformed)
    ? Actions.mergeStatus(previous, malformed)
    : previous
  assert.equal(result, previous)
  assert.deepEqual(result.todayTasks, [{ id: "old", title: "Old" }])
})

test("task IDs reject every backend Unicode control category range", () => {
  const controls = [
    0x00, 0x7f, 0x9f, 0xad, 0x600, 0x61c, 0x6dd, 0x70f, 0x890, 0x8e2,
    0x180e, 0x200b, 0x202e, 0x2060, 0x206f, 0xfeff, 0xfff9, 0x110bd,
    0x110cd, 0x13430, 0x1bca0, 0x1d173, 0xe0001, 0xe0020, 0xe007f
  ]
  for (const codePoint of controls) {
    const value = `task${String.fromCodePoint(codePoint)}id`
    assert.equal(Actions.hasUnicodeControl(value), true, codePoint.toString(16))
    assert.equal(Actions.validTaskId(value), false, codePoint.toString(16))
  }
  assert.equal(Actions.validTaskId("task-😀-id"), true)
  assert.equal(Actions.validTaskId("😀".repeat(255)), true)
  assert.equal(Actions.validTaskId("😀".repeat(256)), false)
})

test("history expires by age and evicts the oldest over 64", () => {
  let results = [{ requestId: "stale", finishedAt: 0 }]
  for (let index = 0; index < 65; index++)
    results = Actions.retain(results, { requestId: String(index), finishedAt: 600001 }, 600001)
  assert.equal(results.length, 64)
  assert.equal(results[0].requestId, "1")
  assert.equal(results.some(entry => entry.requestId === "stale"), false)
})

test("lookup reports queued, running, finished, and missing", () => {
  assert.equal(Actions.lookup("q", [request("q")], null, [], 0).queueState, "queued")
  assert.equal(Actions.lookup("r", [], request("r"), [], 0).queueState, "running")
  const done = { requestId: "f", finishedAt: 5, state: "succeeded" }
  assert.equal(Actions.lookup("f", [], null, [done], 5).result, done)
  assert.deepEqual(Actions.lookup("missing", [], null, [], 0), { found: false })
})

test("status merge preserves failed Today and project context", () => {
  const previous = {
    currentTask: { id: "current", projectId: "p", projectTitle: "Work" },
    todayTasks: [{ id: "one", projectId: "p", projectTitle: "Work" }]
  }
  const noToday = Actions.mergeStatus(previous, {
    currentTask: { id: "current", projectId: "p", projectTitle: null },
    todayTasks: [], context: { todayOk: false, projectsOk: false }
  })
  assert.equal(noToday.todayTasks, previous.todayTasks)
  assert.equal(noToday.currentTask.projectTitle, "Work")
  const freshToday = Actions.mergeStatus(previous, {
    currentTask: null,
    todayTasks: [{ id: "two", projectId: "p", projectTitle: null }],
    context: { todayOk: true, projectsOk: false }
  })
  assert.equal(freshToday.todayTasks[0].projectTitle, "Work")
})

test("status merge restores only authorized prior children when bulk context fails", () => {
  const previous = {
    todayTasks: [
      { id: "old-parent", title: "Gone", subTaskIds: ["gone-child"] },
      { id: "gone-child", parentId: "old-parent", depth: 1 },
      { id: "parent", title: "Old title", subTaskIds: ["second", "first", "removed"] },
      { id: "second", title: "Second", parentId: "parent", parentTitle: "Old title", depth: 1 },
      { id: "first", title: "First", parentId: "parent", parentTitle: "Old title", depth: 1 },
      { id: "removed", title: "Removed", parentId: "parent", depth: 1 }
    ]
  }
  const merged = Actions.mergeStatus(previous, {
    todayTasks: [
      { id: "parent", title: "Fresh title", subTaskIds: ["first", "second"] },
      { id: "fresh", title: "Fresh", subTaskIds: [] }
    ],
    context: { todayOk: true, projectsOk: true, tasksOk: false }
  })
  assert.deepEqual(merged.todayTasks.map(task => task.id), ["parent", "first", "second", "fresh"])
  assert.equal(merged.todayTasks[1].parentTitle, "Fresh title")
  assert.equal(merged.todayTasks.some(task => task.id === "old-parent" || task.id === "removed"), false)
})

test("status merge restores prior children whose IDs match object prototype keys", () => {
  const reservedIds = ["constructor", "toString", "__proto__"]
  const previous = {
    todayTasks: [
      { id: "parent", title: "Old title", subTaskIds: reservedIds },
      ...reservedIds.map(id => ({ id, title: id, parentId: "parent", depth: 1 }))
    ]
  }
  const merged = Actions.mergeStatus(previous, {
    todayTasks: [{ id: "parent", title: "Fresh title", subTaskIds: reservedIds }],
    context: { todayOk: true, projectsOk: true, tasksOk: false }
  })

  assert.deepEqual(merged.todayTasks.map(task => task.id), ["parent", ...reservedIds])
  for (const child of merged.todayTasks.slice(1)) {
    assert.equal(child.parentId, "parent")
    assert.equal(child.parentTitle, "Fresh title")
  }
})

test("status merge preserves incoming children whose IDs match object prototype keys", () => {
  const reservedIds = ["constructor", "toString", "__proto__"]
  const previous = {
    todayTasks: reservedIds.map(id => ({ id, title: `Old ${id}`, parentId: "parent" }))
  }
  const incomingChildren = reservedIds.map(id => ({ id, title: `Fresh ${id}`, parentId: "parent" }))
  const merged = Actions.mergeStatus(previous, {
    todayTasks: [
      { id: "parent", title: "Parent", subTaskIds: reservedIds },
      ...incomingChildren
    ],
    context: { todayOk: true, projectsOk: true, tasksOk: false }
  })

  assert.deepEqual(merged.todayTasks.map(task => task.id), ["parent", ...reservedIds])
  assert.deepEqual(merged.todayTasks.slice(1).map(task => task.title), reservedIds.map(id => `Fresh ${id}`))
})
