function finiteNumber(value, fallback) {
  var number = Number(value)
  return isFinite(number) ? number : fallback
}

function canonicalParentId(value) {
  return value === null || value === undefined || value === "" ? null : String(value)
}

function normalizeStatus(response) {
  var value = response || {}
  if (value.ok === true && value.data && typeof value.data === "object") value = value.data
  var task = value.currentTask || value.task || value.current || null
  var signed = finiteNumber(value.signedRemainingMs, NaN)
  if (!isFinite(signed)) signed = finiteNumber(value.remainingMs, NaN)
  if (!isFinite(signed) && task) signed = finiteNumber(task.timeEstimate, 0) - finiteNumber(task.timeSpent, 0)
  if (!isFinite(signed)) signed = 0
  var context = value.context && typeof value.context === "object" ? value.context : {}
  context = {
    todayOk: context.todayOk === true,
    projectsOk: context.projectsOk === true,
    tasksOk: context.tasksOk === true,
    warnings: Array.isArray(context.warnings) ? context.warnings : []
  }
  return {
    ok: value.ok !== false,
    currentTask: task,
    todayTasks: Array.isArray(value.todayTasks) ? value.todayTasks : [],
    scheduledTasks: Array.isArray(value.scheduledTasks) ? value.scheduledTasks : null,
    todayFetchedAt: typeof value.todayFetchedAt === "number" && isFinite(value.todayFetchedAt)
      && value.todayFetchedAt > 0 ? value.todayFetchedAt : null,
    fetchedAt: Math.max(0, finiteNumber(value.fetchedAt, 0)),
    signedRemainingMs: signed,
    remainingMs: Math.max(0, signed),
    overtimeMs: Math.max(0, -signed),
    context: context,
    error: value.error || "",
    message: value.message || ""
  }
}

function scheduledKey(task) {
  return JSON.stringify([task && task.id, task && task.dueWithTime])
}

function appendSeen(seenKeys, key) {
  if (seenKeys.indexOf(key) === -1) seenKeys.push(key)
  if (seenKeys.length > 128) seenKeys.splice(0, seenKeys.length - 128)
}

function isCurrentScheduledTask(task, currentTask) {
  if (!task || task.id == null || !currentTask) return false
  var scheduledId = String(task.id)
  return currentTask.id != null && scheduledId === String(currentTask.id)
    || canonicalParentId(currentTask.parentId) !== null && scheduledId === canonicalParentId(currentTask.parentId)
}

function reduceSchedule(state, freshTasks, todayFetchedAt, currentTask) {
  var previous = state || { initialized: false, cursorMs: 0, seenKeys: [] }
  var sample = todayFetchedAt
  if (!Array.isArray(freshTasks) || typeof sample !== "number" || !isFinite(sample) || sample <= 0)
    return { state: previous, alerts: [] }

  var seen = Array.isArray(previous.seenKeys) ? previous.seenKeys.slice() : []
  if (seen.length > 128) seen = seen.slice(seen.length - 128)
  var tasks = freshTasks.filter(function (task) {
    var due = task && task.dueWithTime
    return task && task.id != null && task.isDone !== true && canonicalParentId(task.parentId) === null
      && typeof due === "number" && isFinite(due) && due > 0
  }).map(function (task, index) {
    return { task: task, due: task.dueWithTime, index: index, key: scheduledKey(task) }
  }).sort(function (left, right) {
    return left.due - right.due || left.index - right.index
  })

  if (!previous.initialized || sample < Number(previous.cursorMs)) {
    tasks.forEach(function (entry) {
      if (entry.due <= sample) appendSeen(seen, entry.key)
    })
    return { state: { initialized: true, cursorMs: sample, seenKeys: seen }, alerts: [] }
  }

  var cursor = Number(previous.cursorMs)
  var candidates = []
  tasks.forEach(function (entry) {
    if (entry.due <= cursor) {
      appendSeen(seen, entry.key)
    } else if (entry.due <= sample && seen.indexOf(entry.key) === -1) {
      candidates.push(entry)
      appendSeen(seen, entry.key)
    }
  })
  return {
    state: { initialized: true, cursorMs: sample, seenKeys: seen },
    alerts: candidates.filter(function (entry) {
      return !isCurrentScheduledTask(entry.task, currentTask)
    }).slice(0, 1).map(function (entry) { return entry.task })
  }
}

function nextScheduledTask(tasks, nowMs) {
  var now = finiteNumber(nowMs, 0)
  var best = null
  var bestDue = Infinity
  ;(Array.isArray(tasks) ? tasks : []).forEach(function (task) {
    var due = task && task.dueWithTime
    if (!task || task.isDone === true || canonicalParentId(task.parentId) !== null || typeof due !== "number"
        || !isFinite(due) || due <= now) return
    if (due < bestDue) {
      best = task
      bestDue = due
    }
  })
  return best
}

function formatStartTime(milliseconds) {
  var value = milliseconds
  if (typeof value !== "number" || !isFinite(value)) return ""
  var date = new Date(value)
  if (!isFinite(date.getTime())) return ""
  return String(date.getHours()).padStart(2, "0") + ":" + String(date.getMinutes()).padStart(2, "0")
}

function enqueueAlert(queue, alert, maximum) {
  var pending = Array.isArray(queue) ? queue.slice() : []
  var limit = Math.max(1, Math.floor(finiteNumber(maximum, 16)))
  var value = alert || {}
  if (pending.length >= limit) {
    var scheduledIndex = pending.findIndex(function (entry) { return entry && entry.kind === "scheduled" })
    if (value.kind !== "timer") return pending
    pending.splice(scheduledIndex >= 0 ? scheduledIndex : 0, 1)
  }
  pending.push(value)
  return pending
}

function takeNextAlert(queue, nowMs) {
  var now = finiteNumber(nowMs, 0)
  var pending = (Array.isArray(queue) ? queue : []).filter(function (entry) {
    return !entry || entry.kind !== "scheduled" || now - finiteNumber(entry.queuedAt, 0) < 300000
  })
  var timerIndex = pending.findIndex(function (entry) { return entry && entry.kind === "timer" })
  var index = timerIndex >= 0 ? timerIndex : 0
  if (pending.length === 0) return { alert: null, queue: [] }
  return { alert: pending[index], queue: pending.slice(0, index).concat(pending.slice(index + 1)) }
}

function projectSignedRemaining(signedRemainingMs, fetchedAt, now) {
  var signed = finiteNumber(signedRemainingMs, 0)
  var fetched = Math.max(0, finiteNumber(fetchedAt, 0))
  var current = Math.max(fetched, finiteNumber(now, fetched))
  return signed - (current - fetched)
}

function timeViews(signedRemainingMs) {
  var signed = finiteNumber(signedRemainingMs, 0)
  return {
    signedRemainingMs: signed,
    remainingMs: Math.max(0, signed),
    overtimeMs: Math.max(0, -signed),
    timerExpired: signed <= 0
  }
}

function sideEffectState(exitCode, reply) {
  return exitCode === 0 && reply && reply.ok === true ? "succeeded" : "failed"
}

function advanceExpiry(state, task, authoritativeRemaining) {
  var previous = state || { taskId: null, phase: "idle", positiveCount: 0 }
  var taskId = task && task.id != null ? String(task.id) : null
  var estimate = finiteNumber(task && task.timeEstimate, 0)
  var remaining = clampRemaining(authoritativeRemaining)
  var next = { taskId: taskId, phase: "idle", positiveCount: 0 }

  if (!taskId || estimate <= 0) return { state: next, shouldAlert: false, expired: false }

  if (previous.taskId !== taskId || previous.phase === "idle") {
    next.phase = remaining > 0 ? "armed" : "expired"
    return { state: next, shouldAlert: false, expired: remaining <= 0 }
  }

  if (previous.phase === "armed") {
    if (remaining <= 0) {
      next.phase = "expired"
      return { state: next, shouldAlert: true, expired: true }
    }
    next.phase = "armed"
    return { state: next, shouldAlert: false, expired: false }
  }

  if (remaining <= 0) {
    next.phase = "expired"
    return { state: next, shouldAlert: false, expired: true }
  }

  next.phase = "armed"
  return { state: next, shouldAlert: false, expired: false }
}

function displayTitle(task, maximum, fallback) {
  var title = String(task && (task.title || task.name) || "").replace(/\s+/g, " ").trim()
  if (title === "") title = String(fallback === undefined || fallback === null ? "Untitled task" : fallback)
    .replace(/\s+/g, " ").trim()
  var limit = Math.max(1, Math.floor(finiteNumber(maximum, 60)))
  if (title.length <= limit) return title
  if (limit === 1) return "…"
  return title.slice(0, limit - 1).trim() + "…"
}

function clampRemaining(milliseconds) {
  return Math.max(0, finiteNumber(milliseconds, 0))
}

function formatRemaining(milliseconds) {
  var totalSeconds = Math.ceil(clampRemaining(milliseconds) / 1000)
  var hours = Math.floor(totalSeconds / 3600)
  var minutes = Math.floor(totalSeconds % 3600 / 60)
  var seconds = totalSeconds % 60
  var secondsText = String(seconds).padStart(2, "0")
  if (hours > 0) return hours + ":" + String(minutes).padStart(2, "0") + ":" + secondsText
  return minutes + ":" + secondsText
}

function formatOvertime(milliseconds) {
  var totalSeconds = Math.ceil(clampRemaining(milliseconds) / 1000)
  var minutes = Math.floor(totalSeconds / 60)
  var seconds = totalSeconds % 60
  return "+" + minutes + ":" + String(seconds).padStart(2, "0")
}

function chronologicalHierarchy(tasks) {
  var values = Array.isArray(tasks) ? tasks : []
  var byId = Object.create(null)
  var originalIndex = Object.create(null)
  values.forEach(function (task, index) {
    if (!task || task.id == null) return
    var id = String(task.id)
    if (Object.prototype.hasOwnProperty.call(byId, id)) return
    byId[id] = task
    originalIndex[id] = index
  })

  var owned = Object.create(null)
  values.forEach(function (parent) {
    if (!parent || parent.id == null || canonicalParentId(parent.parentId) !== null || !Array.isArray(parent.subTaskIds)) return
    var parentId = String(parent.id)
    parent.subTaskIds.forEach(function (childId) {
      var key = String(childId)
      var child = byId[key]
      if (child && canonicalParentId(child.parentId) !== null && String(child.parentId) === parentId
          && !Object.prototype.hasOwnProperty.call(owned, key)) owned[key] = parentId
    })
  })

  var roots = []
  Object.keys(byId).forEach(function (id) {
    if (Object.prototype.hasOwnProperty.call(owned, id)) return
    var task = byId[id]
    var due = task && task.dueWithTime
    var scheduled = typeof due === "number" && isFinite(due) && due > 0
    roots.push({ id: id, due: scheduled ? due : Infinity, index: originalIndex[id] })
  })
  roots.sort(function (left, right) { return left.due - right.due || left.index - right.index })

  var output = []
  roots.forEach(function (entry) {
    var parent = byId[entry.id]
    var root = Object.assign({}, parent)
    if (canonicalParentId(root.parentId) !== null) {
      root.depth = 0
      root.parentTitle = null
    }
    output.push(root)
    if (canonicalParentId(parent.parentId) !== null || !Array.isArray(parent.subTaskIds)) return
    var emitted = Object.create(null)
    parent.subTaskIds.forEach(function (childId) {
      var key = String(childId)
      if (emitted[key] || owned[key] !== entry.id) return
      emitted[key] = true
      output.push(Object.assign({}, byId[key], {
        parentId: parent.id,
        parentTitle: parent.title,
        depth: 1
      }))
    })
  })
  return output
}

function runnableOrder(tasks) {
  var values = Array.isArray(tasks) ? tasks : []
  return values.filter(function (task) {
    if (!task || task.isDone === true || task.id == null) return false
    return Number(task.depth) === 1 || !Array.isArray(task.subTaskIds) || task.subTaskIds.length === 0
  })
}

function searchHierarchy(tasks, query) {
  var values = Array.isArray(tasks) ? tasks : []
  var needle = String(query || "").trim().toLowerCase()
  if (!needle) return values.slice()
  var matchingParents = Object.create(null)
  values.forEach(function (task) {
    if (!task) return
    var text = [task.title, task.projectTitle, task.parentTitle].join(" ").toLowerCase()
    if (text.indexOf(needle) !== -1 && canonicalParentId(task.parentId) !== null) matchingParents[canonicalParentId(task.parentId)] = true
  })
  return values.filter(function (task) {
    if (!task) return false
    var text = [task.title, task.projectTitle, task.parentTitle].join(" ").toLowerCase()
    return text.indexOf(needle) !== -1 || matchingParents[String(task.id)] === true
  })
}

function barLabel(task, remainingMs, fallback) {
  return "󰄬  " + displayTitle(task, 52, fallback) + "  " + formatRemaining(remainingMs)
}

if (typeof module !== "undefined") {
  module.exports = {
    normalizeStatus: normalizeStatus,
    scheduledKey: scheduledKey,
    reduceSchedule: reduceSchedule,
    nextScheduledTask: nextScheduledTask,
    formatStartTime: formatStartTime,
    enqueueAlert: enqueueAlert,
    takeNextAlert: takeNextAlert,
    projectSignedRemaining: projectSignedRemaining,
    timeViews: timeViews,
    sideEffectState: sideEffectState,
    advanceExpiry: advanceExpiry,
    displayTitle: displayTitle,
    clampRemaining: clampRemaining,
    formatRemaining: formatRemaining,
    formatOvertime: formatOvertime,
    chronologicalHierarchy: chronologicalHierarchy,
    runnableOrder: runnableOrder,
    searchHierarchy: searchHierarchy,
    barLabel: barLabel
  }
}
