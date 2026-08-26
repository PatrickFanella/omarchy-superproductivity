var MAX_PENDING = 16
var MAX_AGE_MS = 30000
var MAX_RESULTS = 64
var RESULT_TTL_MS = 600000

var STATES = { succeeded: true, partial: true, conflict: true, failed: true, unknown: true }
var STAGES = {
  queue: true,
  validation: true,
  preflight: true,
  dispatch: true,
  verify: true,
  "followup-preflight": true,
  "followup-dispatch": true,
  "followup-verify": true,
  done: true
}
var COMMON_RESULT_FIELDS = [
  "kind", "targetTaskId", "state", "stage", "mutationApplied", "expectedCurrentId",
  "observedCurrentId", "finalCurrentId", "raceDetected", "createdTaskId", "message"
]

function owns(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key)
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function isNullableString(value) {
  return value === null || typeof value === "string"
}

function isTriState(value) {
  return value === true || value === false || value === null
}

function validRawTask(value) {
  return isRecord(value) && typeof value.id === "string" && validTaskId(value.id)
}

function hasFreshScheduleContext(status) {
  return isRecord(status) && isRecord(status.context) && status.context.todayOk === true
    && Array.isArray(status.scheduledTasks) && typeof status.todayFetchedAt === "number"
    && isFinite(status.todayFetchedAt) && status.todayFetchedAt > 0
}

function validRawStatus(response) {
  if (!isRecord(response) || response.ok !== true || !owns(response, "task")
      || !owns(response, "fetchedAt") || !owns(response, "signedRemainingMs")
      || !isRecord(response.context) || typeof response.fetchedAt !== "number"
      || !isFinite(response.fetchedAt) || response.fetchedAt <= 0)
    return false
  var context = response.context
  if (typeof context.todayOk !== "boolean" || typeof context.projectsOk !== "boolean"
      || typeof context.tasksOk !== "boolean" || !Array.isArray(context.warnings)
      || context.warnings.some(function (warning) { return typeof warning !== "string" }))
    return false
  if (context.todayOk === true) {
    if (!hasFreshScheduleContext(response)) return false
  } else if (response.scheduledTasks !== null || response.todayFetchedAt !== null) {
    return false
  }
  if (context.todayOk === true && !Array.isArray(response.todayTasks)) return false
  if (owns(response, "todayTasks") && (!Array.isArray(response.todayTasks)
      || response.todayTasks.some(function (task) { return !validRawTask(task) })))
    return false
  if (response.task === null) return response.signedRemainingMs === null
  return validRawTask(response.task) && typeof response.signedRemainingMs === "number"
    && isFinite(response.signedRemainingMs)
}

function codePointAt(text, index) {
  var first = text.charCodeAt(index)
  if (first < 0xd800 || first > 0xdbff || index + 1 >= text.length) return first
  var second = text.charCodeAt(index + 1)
  if (second < 0xdc00 || second > 0xdfff) return first
  return 0x10000 + (first - 0xd800) * 0x400 + second - 0xdc00
}

function isUnicodeControl(codePoint) {
  return codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f)
    || codePoint === 0xad || (codePoint >= 0x600 && codePoint <= 0x605)
    || codePoint === 0x61c || codePoint === 0x6dd || codePoint === 0x70f
    || (codePoint >= 0x890 && codePoint <= 0x891) || codePoint === 0x8e2
    || codePoint === 0x180e || (codePoint >= 0x200b && codePoint <= 0x200f)
    || (codePoint >= 0x202a && codePoint <= 0x202e)
    || (codePoint >= 0x2060 && codePoint <= 0x2064)
    || (codePoint >= 0x2066 && codePoint <= 0x206f) || codePoint === 0xfeff
    || (codePoint >= 0xfff9 && codePoint <= 0xfffb) || codePoint === 0x110bd
    || codePoint === 0x110cd || (codePoint >= 0x13430 && codePoint <= 0x1343f)
    || (codePoint >= 0x1bca0 && codePoint <= 0x1bca3)
    || (codePoint >= 0x1d173 && codePoint <= 0x1d17a) || codePoint === 0xe0001
    || (codePoint >= 0xe0020 && codePoint <= 0xe007f)
}

function hasUnicodeControl(value) {
  var text = String(value === undefined || value === null ? "" : value)
  for (var index = 0; index < text.length; index++) {
    var codePoint = codePointAt(text, index)
    if (isUnicodeControl(codePoint)) return true
    if (codePoint > 0xffff) index += 1
  }
  return false
}

function validTaskId(value) {
  var text = String(value === undefined || value === null ? "" : value)
  var length = 0
  for (var index = 0; index < text.length; index++) {
    length += 1
    if (codePointAt(text, index) > 0xffff) index += 1
  }
  return length > 0 && length <= 255 && !hasUnicodeControl(text)
}

function quickAddStartsAfter(value) {
  return value === "add-switch"
}

function quickAddSwitch(value, legacyValue) {
  return typeof value === "boolean" ? value : quickAddStartsAfter(legacyValue)
}

function settingValue(entry, name, fallback) {
  if (!isRecord(entry)) return fallback
  var value
  if (owns(entry, name)) value = entry[name]
  else if (isRecord(entry.settings) && owns(entry.settings, name)) value = entry.settings[name]
  return value === undefined || value === null ? fallback : value
}

function integerSetting(entry, name, fallback, minimum, maximum) {
  var raw = settingValue(entry, name, fallback)
  var value = typeof raw === "number" ? raw
    : (typeof raw === "string" && /^[+-]?\d+$/.test(raw.trim()) ? Number(raw) : NaN)
  if (!isFinite(value) || Math.floor(value) !== value) value = fallback
  return Math.max(minimum, Math.min(maximum, value))
}

function strictIntegerSetting(entry, name, fallback, minimum, maximum) {
  var raw = settingValue(entry, name, fallback)
  var value = typeof raw === "number" ? raw : NaN
  return isFinite(value) && Math.floor(value) === value && value >= minimum && value <= maximum
    ? value : fallback
}

function previewVolume(value, fallback) {
  var selected = value === undefined ? fallback : value
  if (typeof selected !== "number" || !isFinite(selected)
      || Math.floor(selected) !== selected || selected < 0 || selected > 100)
    return { ok: false, error: "invalid-volume" }
  return { ok: true, value: selected }
}

function completeCommand(helperPath, taskId, autoNext, windowMinutes) {
  var args = [String(helperPath), "complete", String(taskId)]
  if (autoNext) args.push("--auto-next", "--auto-next-window", String(windowMinutes))
  return args
}

function requestId(startedAt, counter) {
  return String(Math.floor(Number(startedAt))) + "-" + String(Math.floor(Number(counter)))
}

function enqueue(queue, running, request) {
  var pending = Array.isArray(queue) ? queue : []
  if (running || pending.length < MAX_PENDING) {
    if (pending.length < MAX_PENDING) return { accepted: true, queue: pending.concat([request]) }
  }
  return { accepted: false, error: "queue-full", queue: pending.slice() }
}

function takeNext(queue, now) {
  var pending = Array.isArray(queue) ? queue.slice() : []
  var expired = []
  var current = Number(now)
  while (pending.length && current - Number(pending[0].queuedAt) > MAX_AGE_MS) {
    var request = pending.shift()
    expired.push(normalizeResult(request, {
      kind: String(request.kind),
      targetTaskId: request.taskId ? String(request.taskId) : null,
      state: "failed",
      stage: "queue",
      mutationApplied: false,
      expectedCurrentId: null,
      observedCurrentId: null,
      finalCurrentId: null,
      raceDetected: false,
      createdTaskId: null,
      message: "Request expired in queue"
    }, null, current))
  }
  return { request: pending.length ? pending.shift() : null, queue: pending, expired: expired }
}

function normalizeResult(request, reply, exitCode, finishedAt) {
  var source = validResultReply(request, reply) ? reply : syntheticUnknown(request)
  var result = {}
  Object.keys(source).forEach(function (key) { result[key] = source[key] })
  result.requestId = String(request.id)
  result.kind = String(request.kind)
  result.ok = source.state === "succeeded"
  var numericExitCode = Number(exitCode)
  result.exitCode = exitCode === null || exitCode === undefined || !isFinite(numericExitCode) ? null : numericExitCode
  result.finishedAt = Number(finishedAt)
  return result
}

function validResultReply(request, reply) {
  if (!isRecord(reply)) return false
  for (var index = 0; index < COMMON_RESULT_FIELDS.length; index++)
    if (!owns(reply, COMMON_RESULT_FIELDS[index])) return false
  if (typeof reply.kind !== "string" || reply.kind !== String(request.kind)
      || !isNullableString(reply.targetTaskId) || !STATES[reply.state] || !STAGES[reply.stage]
      || !isTriState(reply.mutationApplied) || !isNullableString(reply.expectedCurrentId)
      || !isNullableString(reply.observedCurrentId) || !isNullableString(reply.finalCurrentId)
      || typeof reply.raceDetected !== "boolean" || !isNullableString(reply.createdTaskId)
      || typeof reply.message !== "string")
    return false
  if (owns(reply, "followupMutationApplied") && !isTriState(reply.followupMutationApplied)) return false
  if (reply.state === "succeeded" || reply.state === "partial") return reply.mutationApplied === true
  if (reply.state === "conflict" || reply.state === "failed") return reply.mutationApplied === false
  if (reply.mutationApplied === null)
    return !owns(reply, "followupMutationApplied") || reply.followupMutationApplied === null
  if (reply.mutationApplied !== true) return false
  if (reply.stage === "verify") return !owns(reply, "followupMutationApplied")
  if (!owns(reply, "followupMutationApplied")) return false
  if (reply.stage === "followup-dispatch") return reply.followupMutationApplied === null
  return reply.stage === "followup-verify"
    && (reply.followupMutationApplied === null || reply.followupMutationApplied === true)
}

function syntheticUnknown(request) {
  return {
    kind: String(request.kind),
    targetTaskId: request.taskId ? String(request.taskId) : null,
    state: "unknown",
    stage: "dispatch",
    mutationApplied: null,
    expectedCurrentId: null,
    observedCurrentId: null,
    finalCurrentId: null,
    raceDetected: false,
    createdTaskId: null,
    message: "Super Productivity returned an invalid action result"
  }
}

function retain(results, result, now) {
  var current = Number(now)
  var kept = (Array.isArray(results) ? results : []).filter(function (entry) {
    return current - Number(entry.finishedAt) <= RESULT_TTL_MS
  })
  if (result) kept.push(result)
  if (kept.length > MAX_RESULTS) kept = kept.slice(kept.length - MAX_RESULTS)
  return kept
}

function lookup(id, queue, running, results, now) {
  var key = String(id)
  var pending = Array.isArray(queue) ? queue : []
  for (var i = 0; i < pending.length; i++) {
    if (String(pending[i].id) === key) return { found: true, requestId: key, queueState: "queued" }
  }
  if (running && String(running.id) === key)
    return { found: true, requestId: key, queueState: "running" }
  var retained = retain(results, null, now)
  for (var j = retained.length - 1; j >= 0; j--) {
    if (String(retained[j].requestId) === key)
      return { found: true, requestId: key, queueState: "finished", result: retained[j] }
  }
  return { found: false }
}

function copyProjectContext(task, previousById, previousByProject) {
  if (!task || typeof task !== "object") return task
  var copy = {}
  Object.keys(task).forEach(function (key) { copy[key] = task[key] })
  var prior = previousById[String(task.id)]
  if ((copy.projectTitle === null || copy.projectTitle === undefined) && prior)
    copy.projectTitle = prior.projectTitle
  if ((copy.projectTitle === null || copy.projectTitle === undefined) && copy.projectId != null)
    copy.projectTitle = previousByProject[String(copy.projectId)]
  if ((copy.parentTitle === null || copy.parentTitle === undefined) && prior && prior.parentTitle !== undefined)
    copy.parentTitle = prior.parentTitle
  return copy
}

function hydratePreviousChildren(tasks, previousTasks) {
  var previousById = Object.create(null)
  var incomingById = Object.create(null)
  previousTasks.forEach(function (task) {
    if (task && task.id != null) previousById[String(task.id)] = task
  })
  tasks.forEach(function (task) {
    if (task && task.id != null) incomingById[String(task.id)] = task
  })

  var merged = []
  var added = Object.create(null)
  function add(task) {
    if (!task || task.id == null || added[String(task.id)]) return
    added[String(task.id)] = true
    merged.push(task)
  }
  tasks.forEach(function (task) {
    add(task)
    if (!task || task.parentId != null || !Array.isArray(task.subTaskIds)) return
    task.subTaskIds.forEach(function (childId) {
      var child = incomingById[String(childId)] || previousById[String(childId)]
      if (!child || child.isDone === true) return
      if (child === previousById[String(childId)]) {
        child = copyProjectContext(child, previousById, {})
        child.parentId = task.id
        child.parentTitle = task.title
        child.depth = 1
      }
      add(child)
    })
  })
  return merged
}

function mergeStatus(previous, incoming) {
  var old = previous && typeof previous === "object" ? previous : { currentTask: null, todayTasks: [] }
  var next = incoming && typeof incoming === "object" ? incoming : {}
  var context = next.context && typeof next.context === "object" ? next.context : {}
  var oldTasks = Array.isArray(old.todayTasks) ? old.todayTasks : []
  var nextTasks = context.todayOk === false ? oldTasks : (Array.isArray(next.todayTasks) ? next.todayTasks : [])
  if (context.todayOk !== false && context.tasksOk === false)
    nextTasks = hydratePreviousChildren(nextTasks, oldTasks)
  if (context.projectsOk === false) {
    var byId = {}
    var byProject = {}
    oldTasks.concat(old.currentTask ? [old.currentTask] : []).forEach(function (task) {
      if (!task) return
      if (task.id != null) byId[String(task.id)] = task
      if (task.projectId != null && task.projectTitle) byProject[String(task.projectId)] = task.projectTitle
    })
    if (context.todayOk !== false)
      nextTasks = nextTasks.map(function (task) { return copyProjectContext(task, byId, byProject) })
    next.currentTask = copyProjectContext(next.currentTask, byId, byProject)
  }
  next.todayTasks = nextTasks
  return next
}

if (typeof module !== "undefined") module.exports = {
  MAX_PENDING: MAX_PENDING,
  MAX_AGE_MS: MAX_AGE_MS,
  MAX_RESULTS: MAX_RESULTS,
  RESULT_TTL_MS: RESULT_TTL_MS,
  validRawStatus: validRawStatus,
  hasFreshScheduleContext: hasFreshScheduleContext,
  hasUnicodeControl: hasUnicodeControl,
  validTaskId: validTaskId,
  quickAddStartsAfter: quickAddStartsAfter,
  quickAddSwitch: quickAddSwitch,
  settingValue: settingValue,
  integerSetting: integerSetting,
  strictIntegerSetting: strictIntegerSetting,
  previewVolume: previewVolume,
  completeCommand: completeCommand,
  requestId: requestId,
  enqueue: enqueue,
  takeNext: takeNext,
  normalizeResult: normalizeResult,
  retain: retain,
  lookup: lookup,
  mergeStatus: mergeStatus
}
