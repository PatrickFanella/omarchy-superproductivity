import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "patrickfanella.superproductivity"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var engine: null

  property bool initialFocusChosen: false
  property bool settingsView: false
  property bool todayCollapsed: false
  property bool quickAddCollapsed: false
  property var collapsedParentIds: []
  property int todayCursorIndex: -1
  property string focusedTaskId: ""
  property bool heroControlFocused: false
  property bool editableControlFocused: false
  property bool quickAddSwitchValue: false
  property bool quickAddSwitchInitialized: false
  property int alertVolumeOverride: -1

  property string completionRequestId: ""
  property string completionTaskId: ""
  property string completionTaskTitle: ""
  property string completionNextTaskId: ""
  property string completionPreviousTaskId: ""
  property bool completionFocusPending: false

  property string mutationRequestId: ""
  property string mutationState: ""
  property string mutationMessage: ""
  property string settingsState: ""
  property string settingsMessage: ""
  property string addRequestId: ""
  property string addState: ""
  property string addMessage: ""
  property string todayState: ""
  property string todayMessage: ""
  property var addRequestModes: []

  readonly property var task: engine ? engine.currentTask : null
  readonly property var nextScheduledTask: engine ? engine.nextScheduledTask : null
  readonly property real nextScheduledStartMs: engine && isFinite(Number(engine.nextScheduledStartMs))
    ? Number(engine.nextScheduledStartMs) : 0
  readonly property string nextScheduledTitle: String(engine && engine.nextScheduledTitle
    || nextScheduledTask && (nextScheduledTask.title || nextScheduledTask.name)
    || "Untitled task").replace(/\s+/g, " ").trim()
  readonly property bool hasNextScheduled: !task && errorText === ""
    && !!nextScheduledTask && nextScheduledStartMs > 0
  readonly property string nextScheduledTime: hasNextScheduled
    ? Model.formatStartTime(nextScheduledStartMs) : ""
  readonly property real signedRemainingMs: engine ? engine.signedRemainingMs : 0
  readonly property real remainingMs: engine ? engine.remainingMs : 0
  readonly property real overtimeMs: engine ? engine.overtimeMs : 0
  readonly property real estimateMs: engine ? engine.estimateMs : 0
  readonly property real spentMs: engine ? engine.spentMs : 0
  readonly property bool timerExpired: engine ? engine.timerExpired === true : false
  readonly property bool taskOverdue: !!task && estimateMs > 0 && timerExpired
  readonly property bool mutationBusy: engine ? engine.mutationBusy === true : false
  readonly property string mutationTaskId: engine ? String(engine.mutationTaskId || "") : ""
  readonly property string errorText: engine ? String(engine.errorText || "") : "Super Productivity service is not loaded"
  readonly property string contextWarning: engine ? String(engine.contextWarning || "") : ""
  readonly property string alertError: engine ? String(engine.alertError || "") : ""
  readonly property bool refreshing: engine ? engine.refreshing === true : false
  readonly property var todayTasks: unfinishedTasks(engine ? engine.todayTasks : [])
  readonly property var visibleTodayTasks: visibleTasks(todayTasks, searchField.text)
  readonly property color foreground: Color.popups.text
  readonly property color urgent: Color.urgent
  readonly property color accent: Color.accent
  readonly property color dim: Util.alpha(foreground, 0.66)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property real progress: estimateMs > 0
    ? Math.max(0, Math.min(1, spentMs / estimateMs)) : 0
  readonly property bool currentHasChildren: hasRetainedChildren(task)
  readonly property bool quickAddSwitchSource: engine && engine.quickAddSwitch !== undefined
    ? engine.quickAddSwitch === true : boolSetting("quickAddSwitch", false)
  readonly property bool goTopVisible: scroller.contentY > Style.space(72)
  readonly property bool interactiveFocusActive: heroControlFocused
    || settingsView
    || stopButton.activeFocus
    || completeButton.activeFocus
    || extendFiveButton.activeFocus
    || extendFifteenButton.activeFocus
    || customMinutes.activeFocus
    || extendButton.activeFocus
    || quickAddSectionToggle.activeFocus
    || addField.activeFocus
    || addOnlyButton.activeFocus
    || quickAddSwitchControl.activeFocus
    || todaySectionToggle.activeFocus
    || searchField.activeFocus
    || goTopButton.activeFocus
    || todayControlFocused()

  function taskId(value) {
    return String(value && value.id !== undefined && value.id !== null ? value.id : "")
  }

  function isComplete(value) {
    if (!value) return true
    if (value.done === true || value.isDone === true || value.completed === true) return true
    var status = String(value.status || "").toLowerCase()
    return status === "done" || status === "completed"
  }

  function taskDepth(value) {
    var depth = Number(value && value.depth)
    return isFinite(depth) ? Math.max(0, depth) : 0
  }

  function hasRetainedChildren(value) {
    var ids = value ? value.subTaskIds : null
    return !!ids && typeof ids.length === "number" && ids.length > 0
  }

  function hasMatchingUnfinishedChild(value) {
    var ids = value ? value.subTaskIds : null
    var values = engine ? engine.todayTasks : null
    if (!ids || typeof ids.length !== "number" || !values || typeof values.length !== "number") return false
    for (var i = 0; i < ids.length; i++) {
      var childId = String(ids[i])
      for (var j = 0; j < values.length; j++) {
        if (taskId(values[j]) === childId && !isComplete(values[j])) return true
      }
    }
    return false
  }

  function runnable(value) {
    return !!value && !isComplete(value) && !hasRetainedChildren(value)
  }

  function unfinishedTasks(values) {
    var result = []
    if (!values || typeof values.length !== "number") return result
    for (var i = 0; i < values.length; i++) if (!isComplete(values[i])) result.push(values[i])
    return result
  }

  function visibleTasks(values, query) {
    var filtered = Model.searchHierarchy(values, query)
    if (String(query || "").trim() !== "") return filtered
    var result = []
    for (var i = 0; i < filtered.length; i++) {
      var value = filtered[i]
      var parent = String(value && value.parentId !== undefined && value.parentId !== null ? value.parentId : "")
      if (taskDepth(value) === 0 || parent === "" || !isParentCollapsed(parent)) result.push(value)
    }
    return result
  }

  function toggleParent(id) {
    var key = String(id || "")
    if (key === "") return
    var next = []
    var found = false
    for (var i = 0; i < collapsedParentIds.length; i++) {
      var existing = String(collapsedParentIds[i])
      if (existing === key) found = true
      else next.push(existing)
    }
    if (!found) next.push(key)
    collapsedParentIds = next
    Qt.callLater(function() {
      if (todayRepeater.count > 0) focusTodayRow(Math.min(todayCursorIndex, todayRepeater.count - 1))
    })
  }

  function isParentCollapsed(id) {
    var key = String(id || "")
    for (var i = 0; i < collapsedParentIds.length; i++) {
      if (String(collapsedParentIds[i]) === key) return true
    }
    return false
  }

  function titleFor(value) {
    var title = Model.displayTitle(value, 100)
    var parent = String(value && value.parentTitle || "").trim()
    return taskDepth(value) === 1 && parent !== "" ? parent + " › " + title : title
  }

  function scheduledText(value) {
    var stamp = Number(value && value.dueWithTime)
    if (isFinite(stamp) && stamp > 0) return Qt.formatDateTime(new Date(stamp), "ddd h:mm AP")
    var day = String(value && value.dueDay || "")
    return day !== "" ? "Due " + day : ""
  }

  function contextText(value) {
    var parts = []
    var project = String(value && value.projectTitle || "").trim()
    var schedule = scheduledText(value)
    if (project !== "") parts.push(project)
    if (schedule !== "") parts.push(schedule)
    return parts.join(" · ")
  }

  function taskSignedRemaining(value, current) {
    var remaining = Number(value && value.signedRemainingMs)
    if (current) remaining = signedRemainingMs
    if (!isFinite(remaining)) remaining = Number(value && value.remainingMs)
    if (!isFinite(remaining)) {
      var estimate = Number(value && value.timeEstimate)
      var spent = Number(value && value.timeSpent)
      remaining = (isFinite(estimate) ? estimate : 0) - (isFinite(spent) ? spent : 0)
    }
    return remaining
  }

  function taskEstimate(value, current) {
    var estimate = current ? estimateMs : Number(value && value.timeEstimate)
    return isFinite(estimate) ? estimate : 0
  }

  function taskClock(value, current) {
    if (taskEstimate(value, current) <= 0) return "No estimate"
    var remaining = taskSignedRemaining(value, current)
    return remaining <= 0 ? Model.formatOvertime(-remaining) + " over" : Model.formatRemaining(remaining) + " left"
  }

  function rememberAddMode(requestId, startAfter) {
    var id = String(requestId || "")
    var next = []
    for (var i = 0; i < addRequestModes.length; i++) {
      if (String(addRequestModes[i][0]) !== id) next.push(addRequestModes[i])
    }
    next.push([id, startAfter === true])
    addRequestModes = next
  }

  function addModeFor(requestId) {
    var id = String(requestId || "")
    for (var i = 0; i < addRequestModes.length; i++) {
      if (String(addRequestModes[i][0]) === id) return addRequestModes[i][1] === true
    }
    return false
  }

  function forgetAddMode(requestId) {
    var id = String(requestId || "")
    var next = []
    for (var i = 0; i < addRequestModes.length; i++) {
      if (String(addRequestModes[i][0]) !== id) next.push(addRequestModes[i])
    }
    addRequestModes = next
  }

  function resultState(result, ok) {
    var value = String(result && result.state || "")
    return value !== "" ? value : (ok ? "succeeded" : "failed")
  }

  function resultMessage(result, message) {
    var text = String(message || result && result.message || "")
    var stage = String(result && result.stage || "")
    return stage !== "" && stage !== "done" ? text + " · " + stage : text
  }

  function setting(key, fallback) {
    if (!settings || typeof settings !== "object") return fallback
    var value = settings[key]
    return value === undefined || value === null ? fallback : value
  }

  function boolSetting(key, fallback) {
    var value = setting(key, fallback)
    if (typeof value === "string") return value.toLowerCase() !== "false" && value !== "0"
    return !!value
  }

  function persistSetting(key, value, label) {
    settingsState = ""
    settingsMessage = ""
    if (!bar || !bar.shell || !bar.shell.pluginRegistry
        || typeof bar.shell.pluginRegistry.setBarWidget !== "function") {
      settingsState = "failed"
      settingsMessage = "Plugin settings are unavailable"
      return false
    }
    try {
      var error = String(bar.shell.pluginRegistry.setBarWidget(moduleName, key, value, {}) || "")
      if (error !== "") {
        settingsState = "failed"
        settingsMessage = error
        return false
      }
      settingsState = "succeeded"
      settingsMessage = (label || key) + " saved"
      return true
    } catch (error) {
      settingsState = "failed"
      settingsMessage = String(error)
      return false
    }
  }

  function rejection(error) {
    var value = String(error || "request-rejected")
    return "Request rejected: " + value.replace(/-/g, " ")
  }

  function acceptMutation(kind, targetId, request) {
    if (!request || request.accepted !== true) {
      mutationRequestId = ""
      mutationState = "failed"
      mutationMessage = rejection(request && request.error)
      return false
    }
    mutationRequestId = String(request.requestId || "")
    mutationState = "running"
    mutationMessage = kind + " queued"
    return true
  }

  function stopCurrent() {
    if (!engine || mutationBusy || !task) return
    var capturedId = taskId(task)
    acceptMutation("Stop", capturedId, engine.stopTask(capturedId))
  }

  function completeCurrent() {
    if (!engine || mutationBusy || !task || hasRetainedChildren(task)) return
    var capturedId = taskId(task)
    acceptMutation("Complete", capturedId, engine.completeTask(capturedId))
  }

  function extendCurrent(minutes) {
    if (!engine || mutationBusy || !task) return
    var text = String(minutes || "").trim()
    if (!/^\d+$/.test(text) || Number(text) < 1 || Number(text) > 1440) {
      mutationState = "failed"
      mutationMessage = "Extension must be a whole number from 1 to 1440 minutes"
      return
    }
    var capturedId = taskId(task)
    if (acceptMutation("Extend", capturedId, engine.extendTask(capturedId, text))) customMinutes.clear()
  }

  function startTodayTask(value) {
    if (!engine || mutationBusy || !runnable(value)) return
    var capturedId = taskId(value)
    if (capturedId === taskId(task)) return
    var request = engine.startTask(capturedId)
    if (!request || request.accepted !== true) {
      todayState = "failed"
      todayMessage = rejection(request && request.error)
      return
    }
    mutationRequestId = String(request.requestId || "")
    mutationState = "running"
    mutationMessage = "Start queued"
    todayState = "running"
    todayMessage = "Starting " + Model.displayTitle(value, 80)
  }

  function rowIndexForTaskId(id) {
    var key = String(id || "")
    if (key === "") return -1
    for (var i = 0; i < todayRepeater.count; i++) {
      var row = todayRepeater.itemAt(i)
      if (row && row.taskIdentifier === key) return i
    }
    return -1
  }

  function rememberCompletionFocus(value) {
    var index = rowIndexForTaskId(taskId(value))
    completionTaskId = taskId(value)
    completionTaskTitle = Model.displayTitle(value, 80)
    completionNextTaskId = ""
    completionPreviousTaskId = ""
    if (index >= 0) {
      var next = todayRepeater.itemAt(index + 1)
      var previous = todayRepeater.itemAt(index - 1)
      completionNextTaskId = next ? next.taskIdentifier : ""
      completionPreviousTaskId = previous ? previous.taskIdentifier : ""
    }
    completionFocusPending = true
  }

  function completeTodayTask(value) {
    if (!engine || mutationBusy || !value || hasRetainedChildren(value)) return
    var capturedId = taskId(value)
    if (capturedId === "") return
    rememberCompletionFocus(value)
    var request = capturedId === taskId(task)
      ? engine.completeTask(capturedId)
      : engine.completeListedTask(capturedId)
    if (!acceptMutation("Complete", capturedId, request)) {
      completionFocusPending = false
      todayState = "failed"
      todayMessage = mutationMessage
      return
    }
    completionRequestId = mutationRequestId
    todayState = "running"
    todayMessage = "Completing " + completionTaskTitle
  }

  function warnParentCompletion() {
    todayState = "conflict"
    todayMessage = "Complete subtasks first; Super Productivity manages the parent."
  }

  function submitAdd(startAfter) {
    if (!engine || mutationBusy) return
    var value = String(addField.text || "").trim()
    if (value === "") {
      addState = "failed"
      addMessage = "Type a task first"
      return
    }
    var request = engine.add(value, startAfter)
    if (!request || request.accepted !== true) {
      addRequestId = ""
      addState = "failed"
      addMessage = rejection(request && request.error)
      return
    }
    addRequestId = String(request.requestId || "")
    rememberAddMode(addRequestId, startAfter)
    addState = "running"
    addMessage = startAfter ? "Creating, then switching once" : "Creating task once"
  }

  function toggleQuickAddSwitch() {
    var previous = quickAddSwitchValue
    quickAddSwitchValue = !previous
    if (!persistSetting("quickAddSwitch", quickAddSwitchValue, "Add & switch")) {
      quickAddSwitchValue = previous
      addState = "failed"
      addMessage = settingsMessage
      return
    }
    addState = "succeeded"
    addMessage = quickAddSwitchValue ? "Add & switch enabled" : "Add & switch disabled"
  }

  function focusTodayRow(index) {
    if (todayCollapsed || todayRepeater.count <= 0) {
      todayCursorIndex = -1
      return
    }
    todayCursorIndex = Math.max(0, Math.min(todayRepeater.count - 1, index))
    var row = todayRepeater.itemAt(todayCursorIndex)
    if (!row) return
    focusedTaskId = row.taskIdentifier
    row.forceActiveFocus()
    scroller.reveal(row)
  }

  function focusTodayTask(id) {
    var index = rowIndexForTaskId(id)
    if (index < 0) return false
    focusTodayRow(index)
    return true
  }

  function restoreFocusedTask() {
    if (!opened || settingsView || focusedTaskId === "" || completionFocusPending) return
    var index = rowIndexForTaskId(focusedTaskId)
    if (index < 0) return
    todayCursorIndex = index
    if (!interactiveFocusActive || todayControlFocused() || keyCatcher.activeFocus) focusTodayRow(index)
  }

  function restoreCompletionFocus(succeeded) {
    if (!completionFocusPending || !opened) return
    if (!succeeded && focusTodayTask(completionTaskId)) {
      completionFocusPending = false
      return
    }
    if (succeeded && rowIndexForTaskId(completionTaskId) >= 0) return
    if (!focusTodayTask(completionNextTaskId) && !focusTodayTask(completionPreviousTaskId)) {
      todayCursorIndex = -1
      focusedTaskId = ""
      searchField.forceActiveFocus(Qt.TabFocusReason)
      scroller.reveal(searchField)
    }
    completionFocusPending = false
  }

  function scheduleCompletionFocusRestore(succeeded) {
    completionFocusRestore.succeeded = succeeded
    completionFocusRestore.restart()
  }

  function moveTodayCursor(dx, dy) {
    if (dy === 0 || todayCollapsed || todayRepeater.count <= 0) return
    var index = todayCursorIndex
    if (index < 0 || index >= todayRepeater.count) index = 0
    focusTodayRow(index + (dy < 0 ? -1 : 1))
  }

  function activateTodayCursor() {
    if (todayCursorIndex < 0 || todayCursorIndex >= todayRepeater.count) return
    var row = todayRepeater.itemAt(todayCursorIndex)
    if (row) row.activate()
  }

  function handleRowKey(event, row) {
    if (event.isAutoRepeat || (event.modifiers & ~Qt.KeypadModifier)) return
    if (event.key === Qt.Key_Up || event.key === Qt.Key_K) {
      event.accepted = true
      moveTodayCursor(0, -1)
    } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
      event.accepted = true
      moveTodayCursor(0, 1)
    } else if (event.key === Qt.Key_C) {
      event.accepted = true
      if (row.parentRow) {
        warnParentCompletion()
      } else {
        completeTodayTask(row.modelData)
      }
    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
      event.accepted = true
      row.activate()
    }
  }

  function todayControlFocused() {
    for (var i = 0; i < todayRepeater.count; i++) {
      var row = todayRepeater.itemAt(i)
      if (row && row.interactiveFocus) return true
    }
    return false
  }

  function shortcutSuppressed() {
    return settingsView || editableControlFocused || addField.activeFocus
      || searchField.activeFocus || customMinutes.activeFocus
  }

  function homeOwnedByFocusedControl() {
    var focused = activeLocalItem()
    return editableControlFocused
      || !!(focused && "inputMethodComposing" in focused && focused.inputMethodComposing === true)
      || !!(focused && "popup" in focused && focused.popup && focused.popup.visible === true)
  }

  function tabOwnedByFocusedControl() {
    var focused = activeLocalItem()
    return !!(focused && "inputMethodComposing" in focused && focused.inputMethodComposing === true)
      || !!(focused && "popup" in focused && focused.popup && focused.popup.visible === true)
  }

  function listShortcutActive() {
    return keyCatcher.activeFocus || todayControlFocused()
  }

  function goTop() {
    scroller.contentY = 0
    focusTopControl()
  }

  function focusSearch() {
    if (settingsView) return
    todayCollapsed = false
    Qt.callLater(function() {
      searchField.forceActiveFocus(Qt.ShortcutFocusReason)
      scroller.reveal(searchField)
    })
  }

  function isInside(item, ancestor) {
    var cursor = item
    var seen = []
    for (var i = 0; cursor && i < 512; i++) {
      if (cursor === ancestor) return true
      for (var j = 0; j < seen.length; j++) if (seen[j] === cursor) return false
      seen.push(cursor)
      cursor = cursor.parent
    }
    return false
  }

  function activeFocusDescendant() {
    var pending = [[keyCatcher, 0]]
    var seen = []
    var focused = null
    var focusedDepth = -1
    for (var i = 0; pending.length > 0 && i < 4096; i++) {
      var entry = pending.pop()
      var item = entry[0]
      var depth = entry[1]
      if (!item) continue
      var duplicate = false
      for (var j = 0; j < seen.length; j++) {
        if (seen[j] === item) { duplicate = true; break }
      }
      if (duplicate || !isInside(item, keyCatcher)) continue
      seen.push(item)
      if (item.activeFocus && depth > focusedDepth) {
        focused = item
        focusedDepth = depth
      }
      var children = item.children
      if (!children || typeof children.length !== "number") continue
      for (var k = 0; k < children.length; k++) pending.push([children[k], depth + 1])
    }
    return focused
  }

  function effectivelyFocusable(item) {
    if (!item || item === keyCatcher || item.activeFocusOnTab !== true) return false
    var cursor = item
    var seen = []
    for (var i = 0; cursor && cursor !== keyCatcher && i < 512; i++) {
      if (cursor.visible === false || cursor.enabled === false) return false
      for (var j = 0; j < seen.length; j++) if (seen[j] === cursor) return false
      seen.push(cursor)
      cursor = cursor.parent
    }
    return cursor === keyCatcher
  }

  function activeLocalItem() {
    var actual = activeFocusDescendant()
    if (actual) return actual
    if (keyCatcher.activeFocus) return keyCatcher
    var candidate = keyCatcher.nextItemInFocusChain(true)
    var seen = []
    for (var i = 0; candidate && candidate !== keyCatcher && i < 512; i++) {
      if (!isInside(candidate, keyCatcher)) return null
      if (candidate.activeFocus) return candidate
      for (var j = 0; j < seen.length; j++) if (seen[j] === candidate) return null
      seen.push(candidate)
      candidate = candidate.nextItemInFocusChain(true)
    }
    return null
  }

  function localTabControls() {
    var controls = []
    var candidate = keyCatcher.nextItemInFocusChain(true)
    var seen = []
    for (var i = 0; candidate && i < 512; i++) {
      if (candidate === keyCatcher || !isInside(candidate, keyCatcher)) break
      var duplicate = false
      for (var j = 0; j < seen.length; j++) {
        if (seen[j] === candidate) { duplicate = true; break }
      }
      if (duplicate) break
      seen.push(candidate)
      if (effectivelyFocusable(candidate)) controls.push(candidate)
      candidate = candidate.nextItemInFocusChain(true)
    }
    return controls
  }

  function focusedTabControl(controls) {
    var focused = activeLocalItem()
    if (!focused || focused === keyCatcher) return -1
    for (var i = 0; i < controls.length; i++) {
      if (controls[i].activeFocus || isInside(focused, controls[i])) return i
    }
    return -1
  }

  function containingTabControl(item) {
    var cursor = item
    var seen = []
    for (var i = 0; cursor && i < 512; i++) {
      if (effectivelyFocusable(cursor)) return cursor
      for (var j = 0; j < seen.length; j++) if (seen[j] === cursor) return null
      seen.push(cursor)
      if (cursor === keyCatcher) break
      cursor = cursor.parent
    }
    return null
  }

  function localTabStep(origin, direction) {
    if (!origin || !isInside(origin, keyCatcher)) return { target: null, boundary: false }
    var forward = direction >= 0
    var originControl = containingTabControl(origin)
    var current = origin
    var seen = []
    for (var i = 0; current && i < 512; i++) {
      for (var j = 0; j < seen.length; j++) {
        if (seen[j] === current) return { target: null, boundary: false }
      }
      seen.push(current)
      var candidate = current.nextItemInFocusChain(forward)
      if (!candidate) return { target: null, boundary: true }
      for (var k = 0; k < seen.length; k++) {
        if (seen[k] === candidate) return { target: null, boundary: false }
      }
      if (candidate === keyCatcher || !isInside(candidate, keyCatcher))
        return { target: null, boundary: true }
      if (effectivelyFocusable(candidate) && candidate !== originControl)
        return { target: candidate, boundary: false }
      current = candidate
    }
    return { target: null, boundary: false }
  }

  function focusLocalControl(direction) {
    var forward = direction >= 0
    var focused = activeLocalItem()
    if (focused && focused !== keyCatcher) {
      var step = localTabStep(focused, direction)
      if (step.target) {
        step.target.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
        return 1
      }
      return step.boundary ? 0 : -1
    }
    var controls = localTabControls()
    if (controls.length === 0) return 0
    var currentIndex = focusedTabControl(controls)
    var targetIndex = currentIndex < 0 ? (forward ? 0 : controls.length - 1)
      : currentIndex + (forward ? 1 : -1)
    if (targetIndex < 0 || targetIndex >= controls.length) return 0
    controls[targetIndex].forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    return 1
  }

  function switchPanel(direction) {
    var panelBar = root.bar || (root.hostWidget && root.hostWidget.bar)
    if (panelBar && typeof panelBar.switchPanelFrom === "function")
      return panelBar.switchPanelFrom(root.hostWidget || root, direction)
    return false
  }

  function handleTab(direction) {
    if (focusLocalControl(direction) === 0) switchPanel(direction)
  }

  function focusFirstControlWithin(container) {
    var controls = localTabControls()
    for (var i = 0; i < controls.length; i++) {
      if (isInside(controls[i], container)) {
        controls[i].forceActiveFocus(Qt.TabFocusReason)
        return true
      }
    }
    return false
  }

  function focusTopControl() {
    if (settingsView) {
      if (effectivelyFocusable(settingsBackButton))
        settingsBackButton.forceActiveFocus(Qt.TabFocusReason)
      else
        focusFirstControlWithin(settingsContent)
      return
    }
    if (effectivelyFocusable(addField))
      addField.forceActiveFocus(Qt.TabFocusReason)
    else
      focusFirstControlWithin(normalContent)
  }

  function focusInitial() {
    if (!opened) return
    if (initialFocusChosen
        && !(keyCatcher.activeFocus && focusedTaskId === "" && !todayCollapsed && todayRepeater.count > 0)) return
    if (!todayCollapsed && todayRepeater.count > 0) {
      var currentId = taskId(task)
      var targetIndex = 0
      for (var i = 0; i < todayRepeater.count; i++) {
        var candidate = todayRepeater.itemAt(i)
        if (candidate && candidate.taskIdentifier === currentId) { targetIndex = i; break }
      }
      focusTodayRow(targetIndex)
      initialFocusChosen = true
      return
    }
    keyCatcher.forceActiveFocus()
    initialFocusChosen = true
  }

  function openApp() { if (engine) engine.show() }
  function toggleSettings() {
    settingsView = !settingsView
    settingsState = ""
    settingsMessage = ""
    scroller.contentY = 0
    if (settingsView)
      Qt.callLater(function() { settingsBackButton.forceActiveFocus(Qt.TabFocusReason) })
    else
      Qt.callLater(function() { keyCatcher.forceActiveFocus(Qt.TabFocusReason) })
  }

  function closeSettings() {
    settingsView = false
    scroller.contentY = 0
    Qt.callLater(function() { keyCatcher.forceActiveFocus(Qt.TabFocusReason) })
  }

  function testNotification() {
    if (!engine || engine.testNotificationBusy) return
    var request = engine.testNotification()
    if (!request || request.accepted !== true) {
      settingsState = "failed"
      settingsMessage = rejection(request && request.error)
    }
  }

  function previewSound() {
    if (!engine || engine.previewBusy) return
    var configuredVolume = alertVolumeOverride >= 0
      ? alertVolumeOverride : Number(setting("alertVolume", 100))
    if (!isFinite(configuredVolume)) configuredVolume = 100
    configuredVolume = Math.max(0, Math.min(100, Math.round(configuredVolume)))
    var request = engine.previewSound(configuredVolume)
    if (!request || request.accepted !== true) {
      settingsState = "failed"
      settingsMessage = rejection(request && request.error)
    }
  }

  onOpenedChanged: {
    if (opened) {
      initialFocusChosen = false
      settingsView = false
      focusedTaskId = ""
      if (engine) engine.refresh()
      Qt.callLater(focusInitial)
    }
  }

  onVisibleTodayTasksChanged: {
    if (todayCursorIndex >= visibleTodayTasks.length) todayCursorIndex = visibleTodayTasks.length - 1
    if (completionFocusPending) scheduleCompletionFocusRestore(true)
  }

  onQuickAddSwitchSourceChanged: {
    if (!quickAddSwitchInitialized || quickAddSwitchValue !== quickAddSwitchSource) {
      quickAddSwitchValue = quickAddSwitchSource
      quickAddSwitchInitialized = true
    }
  }

  onGoTopVisibleChanged: {
    if (!goTopVisible && goTopButton.activeFocus) focusTopControl()
  }

  Component.onCompleted: {
    quickAddSwitchValue = quickAddSwitchSource
    quickAddSwitchInitialized = true
  }

  Timer {
    id: completionFocusRestore
    interval: 0
    property bool succeeded: true
    onTriggered: root.restoreCompletionFocus(succeeded)
  }

  Connections {
    target: root.engine
    function onActionFinished(requestId, kind, ok, message, result) {
      var id = String(requestId || "")
      if (id === root.addRequestId) {
        var submittedStartAfter = root.addModeFor(id)
        root.addRequestId = ""
        root.addState = root.resultState(result, ok)
        root.addMessage = root.resultMessage(result, message)
        if (root.addMessage === "") root.addMessage = submittedStartAfter ? "Task created and switched" : "Task created"
        root.forgetAddMode(id)
        if (root.addState === "succeeded" || (result && result.createdTaskId)) addField.clear()
        return
      }
      if (id === root.mutationRequestId) {
        root.mutationRequestId = ""
        root.mutationState = root.resultState(result, ok)
        root.mutationMessage = root.resultMessage(result, message)
        if (id === root.completionRequestId) {
          root.completionRequestId = ""
          root.todayState = root.mutationState
          root.todayMessage = root.mutationState === "succeeded"
            ? "Completed " + root.completionTaskTitle
            : root.mutationMessage
          root.scheduleCompletionFocusRestore(root.mutationState === "succeeded")
        }
        if (String(kind) === "start") {
          root.todayState = root.mutationState
          root.todayMessage = root.mutationMessage
        }
      }
    }
    function onTodayTasksChanged() {
      root.scheduleCompletionFocusRestore(true)
    }
    function onRefreshingChanged() { }
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: popup.fittedContentWidth(Style.space(420))
    contentHeight: popup.fittedContentHeight(content.implicitHeight, Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      Keys.forwardTo: [shortcutInterceptor]
      blocked: root.interactiveFocusActive
      onMoveRequested: function(dx, dy) { root.moveTodayCursor(dx, dy) }
      onActivateRequested: root.activateTodayCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) {
        root.handleTab(direction)
      }
      onTextKey: function(text) {
        if (text === "r" || text === "R") { if (root.engine) root.engine.refresh() }
        else if (text === "j" || text === "J") root.moveTodayCursor(0, 1)
        else if (text === "k" || text === "K") root.moveTodayCursor(0, -1)
      }

      Item {
        id: shortcutInterceptor
        Keys.onPressed: function(event) {
          var tabKey = event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab
          if (tabKey && !(event.modifiers & ~(Qt.ShiftModifier | Qt.KeypadModifier))) {
            if (root.tabOwnedByFocusedControl()) return
            event.accepted = true
            if (!event.isAutoRepeat)
              root.handleTab((event.modifiers & Qt.ShiftModifier) || event.key === Qt.Key_Backtab ? -1 : 1)
            return
          }
          var managedKey = event.key === Qt.Key_Escape || event.key === Qt.Key_Slash
            || event.key === Qt.Key_Home || event.key === Qt.Key_C
            || event.key === Qt.Key_J || event.key === Qt.Key_K
            || event.key === Qt.Key_Up || event.key === Qt.Key_Down
          if (event.isAutoRepeat || (event.modifiers & ~Qt.KeypadModifier)) {
            if (managedKey && !(event.key === Qt.Key_Home && root.homeOwnedByFocusedControl()))
              event.accepted = true
            return
          }
          if (event.key === Qt.Key_Escape) {
            event.accepted = true
            if (root.settingsView) root.closeSettings()
            else root.close()
            return
          }
          if (event.key === Qt.Key_Home) {
            if (!root.homeOwnedByFocusedControl()) {
              event.accepted = true
              root.goTop()
            }
            return
          }
          if (root.shortcutSuppressed()) return
          if (event.key === Qt.Key_Slash) {
            event.accepted = true
            root.focusSearch()
          } else if (root.listShortcutActive() && event.key === Qt.Key_C) {
            event.accepted = true
            var completeRow = todayRepeater.itemAt(root.rowIndexForTaskId(root.focusedTaskId))
            if (completeRow) {
              if (completeRow.parentRow) root.warnParentCompletion()
              else root.completeTodayTask(completeRow.modelData)
            }
          } else if (root.listShortcutActive() && (event.key === Qt.Key_J || event.key === Qt.Key_Down)) {
            event.accepted = true
            root.moveTodayCursor(0, 1)
          } else if (root.listShortcutActive() && (event.key === Qt.Key_K || event.key === Qt.Key_Up)) {
            event.accepted = true
            root.moveTodayCursor(0, -1)
          }
        }
      }

      Flickable {
        id: scroller
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        function reveal(item) {
          if (!item) return
          var top = item.mapToItem(content, 0, 0).y
          var bottom = top + item.height
          if (top < contentY) contentY = Math.max(0, top)
          else if (bottom > contentY + height)
            contentY = Math.min(Math.max(0, contentHeight - height), bottom - height)
        }

        Column {
          id: content
          width: scroller.width
          spacing: Style.space(12)

          Column {
            id: settingsContent
            visible: root.settingsView
            width: parent.width
            spacing: Style.space(12)

            Row {
              width: parent.width
              spacing: Style.space(10)

              Button {
                id: settingsBackButton
                width: Style.space(78)
                text: "← Back"
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: true
                Accessible.name: "Back to task view"
                Accessible.role: Accessible.Button
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { scroller.reveal(settingsBackButton) })
                onClicked: root.closeSettings()
                Accessible.onPressAction: root.closeSettings()
              }

              Column {
                width: parent.width - settingsBackButton.width - parent.spacing
                spacing: Style.space(2)
                Text {
                  width: parent.width
                  text: "WIDGET SETTINGS"
                  textFormat: Text.PlainText
                  color: root.accent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  font.letterSpacing: 1
                  Accessible.name: "Super Productivity widget settings"
                }
                Text {
                  width: parent.width
                  text: "Changes apply to this bar widget"
                  textFormat: Text.PlainText
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }

            PanelSeparator { width: parent.width; foreground: root.foreground }

            Text {
              width: parent.width
              text: "GENERAL"
              textFormat: Text.PlainText
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 0.9
            }

            SettingNumber { label: "Status refresh"; description: "Seconds between helper checks"; settingKey: "pollSeconds"; fallbackValue: 5; minimum: 2; maximum: 30; suffix: "seconds" }
            SettingNumber { label: "Maximum bar width"; description: "Width before the task title is shortened"; settingKey: "maxTitleWidth"; fallbackValue: 300; minimum: 120; maximum: 520; suffix: "pixels" }
            SettingToggle { label: "Show while idle"; description: "Keep the bar marker visible with no active task"; settingKey: "showIdle"; fallbackValue: true }
            SettingToggle { label: "Start next after Complete"; description: "Start the next runnable task after panel completion"; settingKey: "autoStartNext"; fallbackValue: false }
            SettingNumber { label: "Auto-next schedule window"; description: "Only scheduled tasks within ±window"; settingKey: "autoNextWindowMinutes"; fallbackValue: 30; minimum: 1; maximum: 1440; step: 5; suffix: "minutes" }

            PanelSeparator { width: parent.width; foreground: root.foreground }

            Text {
              width: parent.width
              text: "ALERTS"
              textFormat: Text.PlainText
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 0.9
            }

            SettingToggle { label: "Task alerts"; description: "Countdown expiry or scheduled start, including while tracking"; settingKey: "alertEnabled"; fallbackValue: true }
            SettingToggle { label: "Play alert sound"; description: "Sound for countdown expiry and scheduled start"; settingKey: "soundEnabled"; fallbackValue: true }
            SettingNumber {
              label: "Alert volume"
              description: "Countdown and scheduled-start alerts and previews"
              settingKey: "alertVolume"
              fallbackValue: 100
              minimum: 0
              maximum: 100
              step: 5
              suffix: "%"
              minimumLabel: "0 muted"
              maximumLabel: "100%"
              immediate: true
            }
            SettingText { label: "Alert sound path"; description: "Custom sound for countdown expiry and scheduled start"; settingKey: "soundPath"; fallbackValue: ""; placeholder: "Bundled sound" }
            SettingChoice {
              label: "Notification urgency"
              description: "Urgency for countdown expiry and scheduled start"
              settingKey: "notificationUrgency"
              fallbackValue: "critical"
              choices: [{ label: "Low", value: "low" }, { label: "Normal", value: "normal" }, { label: "Critical", value: "critical" }]
            }

            Flow {
              width: parent.width
              spacing: Style.space(7)
              ActionButton {
                text: root.engine && root.engine.testNotificationBusy ? "Sending…" : "Test notification"
                accessibleText: root.engine && root.engine.testNotificationBusy ? "Test notification in progress" : "Test notification"
                enabled: !!root.engine && !root.engine.testNotificationBusy
                onTriggered: root.testNotification()
              }
              ActionButton {
                text: root.engine && root.engine.previewBusy ? "Playing…" : "Preview sound"
                accessibleText: root.engine && root.engine.previewBusy ? "Sound preview in progress" : "Preview alert sound"
                enabled: !!root.engine && !root.engine.previewBusy
                onTriggered: root.previewSound()
              }
            }

            ResultFeedback {
              visible: root.engine && root.engine.testNotificationState !== "idle"
              resultState: root.engine ? root.engine.testNotificationState : ""
              message: root.engine && root.engine.testNotificationMessage !== ""
                ? root.engine.testNotificationMessage : "Sending test notification…"
            }
            ResultFeedback {
              visible: root.engine && root.engine.previewState !== "idle"
              resultState: root.engine ? root.engine.previewState : ""
              message: root.engine && root.engine.previewMessage !== ""
                ? root.engine.previewMessage : "Playing alert sound…"
            }
            ResultFeedback { visible: root.settingsState !== ""; resultState: root.settingsState; message: root.settingsMessage }
          }

          Column {
            id: normalContent
            visible: !root.settingsView
            width: parent.width
            spacing: Style.space(12)

          PanelHero {
            width: parent.width
            title: root.task ? root.titleFor(root.task) : (root.hasNextScheduled ? root.nextScheduledTitle : "Super Productivity")
            meta: root.taskOverdue ? "OVERTIME" : (root.errorText !== "" ? "CONNECTION ISSUE" : (root.task ? "CURRENT FOCUS" : (root.hasNextScheduled ? "NEXT SCHEDULED" : "READY")))
            detail: root.taskOverdue
              ? Model.formatOvertime(root.overtimeMs)
              : (root.task ? root.taskClock(root.task, true) : (root.hasNextScheduled ? "Starts at " + root.nextScheduledTime : "No task running"))
            foreground: root.taskOverdue || root.errorText !== "" ? root.urgent : root.foreground
            fontFamily: root.fontFamily
            Accessible.name: root.task
              ? root.titleFor(root.task) + ", " + root.taskClock(root.task, true)
              : (root.hasNextScheduled
                ? "Super Productivity, next scheduled task " + root.nextScheduledTitle + " at " + root.nextScheduledTime
                : "Super Productivity, no current task")
            iconComponent: Component {
              Item {
                implicitWidth: Style.font.display
                implicitHeight: Style.font.display
                Text {
                  visible: root.taskOverdue
                  anchors.centerIn: parent
                  text: "⏰"
                  textFormat: Text.PlainText
                  color: root.urgent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.title
                }
                Text {
                  visible: !root.taskOverdue && root.hasNextScheduled
                  anchors.centerIn: parent
                  text: "󰥔"
                  textFormat: Text.PlainText
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.title
                }
                Rectangle {
                  visible: !root.taskOverdue && !root.hasNextScheduled
                  anchors.fill: parent
                  radius: width / 2
                  color: "transparent"
                  border.width: 2
                  border.color: root.errorText !== "" ? root.urgent : root.accent
                }
                Rectangle {
                  visible: !root.taskOverdue && !!root.task
                  anchors.centerIn: parent
                  width: parent.width * 0.34
                  height: width
                  radius: width / 2
                  color: root.accent
                }
              }
            }
            trailingControl: Component {
              Row {
                spacing: Style.space(4)
                PanelActionButton {
                  iconText: "󰑐"
                  tooltipText: "Refresh status"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  focusable: true
                  Accessible.name: "Refresh Super Productivity status"
                  Accessible.role: Accessible.Button
                  onActiveFocusChanged: root.heroControlFocused = activeFocus
                  onClicked: if (root.engine) root.engine.refresh()
                  Accessible.onPressAction: if (root.engine) root.engine.refresh()
                }
                PanelActionButton {
                  id: settingsButton
                  iconText: "󰒓"
                  tooltipText: root.settingsView ? "Widget settings open" : "Open widget settings"
                  foreground: root.settingsView ? root.accent : root.foreground
                  hoverColor: root.accent
                  hasCursor: root.settingsView
                  bordered: root.settingsView
                  fontFamily: root.fontFamily
                  focusable: true
                  Accessible.name: root.settingsView ? "Super Productivity widget settings open" : "Open Super Productivity widget settings"
                  Accessible.role: Accessible.Button
                  onActiveFocusChanged: root.heroControlFocused = activeFocus
                  onClicked: root.toggleSettings()
                  Accessible.onPressAction: root.toggleSettings()
                }
                PanelActionButton {
                  iconText: "󰏌"
                  tooltipText: "Open Super Productivity"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  focusable: true
                  Accessible.name: "Open Super Productivity"
                  Accessible.role: Accessible.Button
                  onActiveFocusChanged: root.heroControlFocused = activeFocus
                  onClicked: root.openApp()
                  Accessible.onPressAction: root.openApp()
                }
              }
            }
          }

          Text {
            visible: !!root.task && root.contextText(root.task) !== ""
            width: parent.width
            text: root.contextText(root.task)
            textFormat: Text.PlainText
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
            Accessible.name: "Current task context: " + text
          }

          FeedbackText { visible: root.errorText !== ""; resultState: "failed"; message: root.errorText }
          FeedbackText { visible: root.contextWarning !== ""; resultState: "conflict"; message: "Context warning: " + root.contextWarning }
          FeedbackText { visible: root.alertError !== ""; resultState: "failed"; message: "Alert: " + root.alertError }

          Column {
            visible: !!root.task
            width: parent.width
            spacing: Style.space(8)

            Rectangle {
              width: parent.width
              height: Style.space(3)
              radius: height / 2
              color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
              Rectangle {
                width: parent.width * root.progress
                height: parent.height
                radius: parent.radius
                color: root.taskOverdue ? root.urgent : root.accent
                Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
              }
            }

            Grid {
              id: metrics
              width: parent.width
              columns: width >= Style.space(360) ? 3 : 1
              columnSpacing: Style.space(8)
              rowSpacing: Style.space(6)
              Metric { width: metrics.columns === 3 ? (metrics.width - metrics.columnSpacing * 2) / 3 : metrics.width; label: root.taskOverdue ? "OVERTIME" : "REMAINING"; value: root.taskOverdue ? Model.formatOvertime(root.overtimeMs) : (root.estimateMs > 0 ? Model.formatRemaining(root.remainingMs) : "No estimate"); emphasis: true; warning: root.taskOverdue }
              Metric { width: metrics.columns === 3 ? (metrics.width - metrics.columnSpacing * 2) / 3 : metrics.width; label: "ESTIMATE"; value: Model.formatRemaining(root.estimateMs) }
              Metric { width: metrics.columns === 3 ? (metrics.width - metrics.columnSpacing * 2) / 3 : metrics.width; label: "SPENT"; value: Model.formatRemaining(root.spentMs) }
            }

            Flow {
              width: parent.width
              spacing: Style.space(7)
              ActionButton { id: stopButton; text: root.mutationBusy && root.engine.mutationKind === "stop" ? "Stopping…" : "Stop"; accessibleText: "Stop current task"; enabled: !root.mutationBusy; onTriggered: root.stopCurrent() }
              ActionButton {
                id: completeButton
                visible: !root.currentHasChildren
                enabled: visible && !root.mutationBusy
                text: root.mutationBusy && root.engine.mutationKind === "complete" ? "Completing…" : "Complete"
                accessibleText: "Complete current task. Auto-next considers scheduled tasks only within the configured schedule window"
                onTriggered: root.completeCurrent()
              }
              ActionButton { id: extendFiveButton; text: "+5m"; accessibleText: "Extend current task by 5 minutes"; enabled: !root.mutationBusy; onTriggered: root.extendCurrent("5") }
              ActionButton { id: extendFifteenButton; text: "+15m"; accessibleText: "Extend current task by 15 minutes"; enabled: !root.mutationBusy; onTriggered: root.extendCurrent("15") }
            }

            Row {
              width: parent.width
              spacing: Style.space(7)
              TextField {
                id: customMinutes
                width: Math.max(Style.space(120), parent.width - extendButton.width - parent.spacing)
                enabled: !root.mutationBusy
                foreground: root.foreground
                accent: root.accent
                placeholderText: "Minutes (1–1440)"
                inputMethodHints: Qt.ImhDigitsOnly
                validator: IntValidator { bottom: 1; top: 1440 }
                Accessible.name: "Custom whole-minute extension"
                onActiveFocusChanged: {
                  root.editableControlFocused = activeFocus
                  if (activeFocus) Qt.callLater(function() { scroller.reveal(customMinutes) })
                }
                Keys.onReturnPressed: function(event) { event.accepted = true; root.extendCurrent(text) }
                Keys.onEnterPressed: function(event) { event.accepted = true; root.extendCurrent(text) }
              }
              Button {
                id: extendButton
                width: Style.space(96)
                text: "Extend"
                bordered: true
                enabled: !root.mutationBusy
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: true
                Accessible.name: "Apply custom extension"
                Accessible.role: Accessible.Button
                onClicked: root.extendCurrent(customMinutes.text)
                Accessible.onPressAction: root.extendCurrent(customMinutes.text)
              }
            }

            Text {
              visible: root.currentHasChildren
              width: parent.width
              text: "Complete subtasks first; Super Productivity manages the parent."
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
              Accessible.name: text
            }
            ResultFeedback { visible: root.mutationState !== ""; resultState: root.mutationState; message: root.mutationMessage }
          }

          Text {
            visible: !root.task && root.errorText === ""
            width: parent.width
            text: root.hasNextScheduled
              ? "Next at " + root.nextScheduledTime + ": " + root.nextScheduledTitle + ". Start it from Today when ready."
              : "Pick an explicit task below, or capture the next one with Quick Add."
            textFormat: Text.PlainText
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
            Accessible.name: text
          }

          PanelSeparator { width: parent.width; foreground: root.foreground }

          Column {
            width: parent.width
            spacing: Style.space(7)

            SectionToggle {
              id: quickAddSectionToggle
              text: "QUICK ADD"
              collapsed: root.quickAddCollapsed
              countText: ""
              accessibleText: (root.quickAddCollapsed ? "Expand" : "Collapse") + " Quick Add"
              onTriggered: root.quickAddCollapsed = !root.quickAddCollapsed
            }

            Column {
              visible: !root.quickAddCollapsed
              width: parent.width
              spacing: Style.space(7)

              Row {
                id: quickAddRow
                width: parent.width
                spacing: Style.space(7)

                TextField {
                  id: addField
                  width: parent.width - addOnlyButton.width - parent.spacing
                  enabled: !root.mutationBusy
                  foreground: root.foreground
                  accent: root.accent
                  placeholderText: "Write report 30m +Work #focus @tomorrow"
                  Accessible.name: "Quick Add task"
                  onActiveFocusChanged: {
                    root.editableControlFocused = activeFocus
                    if (activeFocus) Qt.callLater(function() { scroller.reveal(addField) })
                  }
                  Keys.onReturnPressed: function(event) {
                    event.accepted = true
                    root.submitAdd(root.quickAddSwitchValue)
                  }
                  Keys.onEnterPressed: function(event) {
                    event.accepted = true
                    root.submitAdd(root.quickAddSwitchValue)
                  }
                }

                Button {
                  id: addOnlyButton
                  width: addField.implicitHeight
                  height: width
                  text: root.addRequestId !== "" && !root.addModeFor(root.addRequestId) ? "…" : "+"
                  bordered: true
                  enabled: !root.mutationBusy
                  foreground: root.accent
                  fontFamily: root.fontFamily
                  focusable: true
                  tooltipText: root.quickAddSwitchValue ? "Add task and switch to it" : "Add task"
                  Accessible.name: root.quickAddSwitchValue ? "Add task and switch to it" : "Add task"
                  Accessible.role: Accessible.Button
                  onClicked: root.submitAdd(root.quickAddSwitchValue)
                  Accessible.onPressAction: root.submitAdd(root.quickAddSwitchValue)
                }
              }

              Row {
                width: parent.width
                spacing: Style.space(8)
                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  width: Math.max(0, parent.width - quickAddSwitchControl.width - parent.spacing)
                  text: "+project, @schedule, #tag"
                  textFormat: Text.PlainText
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  Accessible.name: text
                }
                Rectangle {
                  id: quickAddSwitchControl
                  anchors.verticalCenter: parent.verticalCenter
                  width: switchContent.implicitWidth + Style.space(14)
                  height: Style.space(28)
                  radius: Style.space(4)
                  color: activeFocus ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.12) : "transparent"
                  border.width: 0
                  activeFocusOnTab: true
                  Accessible.role: Accessible.CheckBox
                  Accessible.name: "Add & switch"
                  Accessible.description: "When checked, Enter and the plus button add the task and switch to it"
                  Accessible.checked: root.quickAddSwitchValue
                  Accessible.onPressAction: root.toggleQuickAddSwitch()
                  Keys.onReturnPressed: function(event) { event.accepted = true; root.toggleQuickAddSwitch() }
                  Keys.onEnterPressed: function(event) { event.accepted = true; root.toggleQuickAddSwitch() }
                  Keys.onSpacePressed: function(event) { event.accepted = true; root.toggleQuickAddSwitch() }
                  onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { scroller.reveal(quickAddSwitchControl) })
                  TapHandler {
                    acceptedButtons: Qt.LeftButton
                    onTapped: {
                      quickAddSwitchControl.forceActiveFocus(Qt.MouseFocusReason)
                      root.toggleQuickAddSwitch()
                    }
                  }
                  Row {
                    id: switchContent
                    anchors.centerIn: parent
                    spacing: Style.space(5)
                    Rectangle {
                      anchors.verticalCenter: parent.verticalCenter
                      width: Style.space(14)
                      height: width
                      radius: Style.space(2)
                      color: root.quickAddSwitchValue ? root.accent : "transparent"
                      border.width: 1
                      border.color: root.quickAddSwitchValue ? root.accent : root.dim
                      Text {
                        visible: root.quickAddSwitchValue
                        anchors.centerIn: parent
                        text: "✓"
                        color: Color.popups.background
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        font.bold: true
                      }
                    }
                    Text {
                      anchors.verticalCenter: parent.verticalCenter
                      text: "Add & switch"
                      color: root.quickAddSwitchValue ? root.accent : root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }
                  }
                  Rectangle {
                    visible: quickAddSwitchControl.activeFocus
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: Style.space(2)
                    color: root.accent
                  }
                }
              }
              ResultFeedback { visible: root.addState !== ""; resultState: root.addState; message: root.addMessage }
            }
          }

          PanelSeparator { width: parent.width; foreground: root.foreground }

          Column {
            width: parent.width
            spacing: Style.space(7)

            SectionToggle {
              id: todaySectionToggle
              text: "TODAY"
              collapsed: root.todayCollapsed
              countText: String(root.visibleTodayTasks.length)
              accessibleText: (root.todayCollapsed ? "Expand" : "Collapse") + " Today tasks"
              onTriggered: {
                root.todayCollapsed = !root.todayCollapsed
                if (!root.todayCollapsed) Qt.callLater(function() { root.focusTodayRow(Math.max(0, root.todayCursorIndex)) })
              }
            }

            Column {
              visible: !root.todayCollapsed
              width: parent.width
              spacing: Style.space(7)

              TextField {
                id: searchField
                width: parent.width
                foreground: root.foreground
                accent: root.accent
                placeholderText: "Search title, project, or parent"
                Accessible.name: "Search Today tasks by title, project, or parent"
                onActiveFocusChanged: {
                  root.editableControlFocused = activeFocus
                  if (activeFocus) Qt.callLater(function() { scroller.reveal(searchField) })
                }
              }

              Text {
                visible: root.visibleTodayTasks.length === 0
                width: parent.width
                text: searchField.text !== "" ? "No Today tasks match this search." : (root.refreshing ? "Loading Today…" : "No tasks left today.")
                textFormat: Text.PlainText
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                Accessible.name: text
              }

              Repeater {
                id: todayRepeater
                model: root.visibleTodayTasks

                delegate: Rectangle {
                  id: todayRow
                  required property var modelData
                  required property int index
                  readonly property string taskIdentifier: root.taskId(modelData)
                  readonly property bool current: taskIdentifier !== "" && taskIdentifier === root.taskId(root.task)
                  readonly property bool pending: taskIdentifier !== "" && taskIdentifier === root.mutationTaskId
                  readonly property bool parentRow: root.hasRetainedChildren(modelData)
                  readonly property bool canStart: root.runnable(modelData)
                  readonly property bool expanded: !root.isParentCollapsed(taskIdentifier)
                  readonly property bool overdue: root.taskEstimate(modelData, current) > 0
                    && root.taskSignedRemaining(modelData, current) <= 0
                  readonly property bool interactiveFocus: activeFocus || startControl.activeFocus
                    || (!parentRow && completeControl.activeFocus)
                  readonly property real indent: root.taskDepth(modelData) === 1 ? Style.space(18) : 0

                  function activate() {
                    if (parentRow) {
                      if (searchField.text.trim() === "") root.toggleParent(taskIdentifier)
                    }
                    else if (canStart) root.startTodayTask(modelData)
                  }

                  width: content.width
                  height: Style.space(58)
                  radius: Style.cornerRadius
                  color: current
                    ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.14)
                    : (pending
                      ? Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.10)
                      : (hover.hovered || activeFocus ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.075) : "transparent"))
                  border.width: interactiveFocus ? 2 : (current || pending ? 1 : 0)
                  border.color: interactiveFocus ? root.accent : (pending ? root.urgent : (current ? root.accent : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.5)))
                  opacity: root.mutationBusy && !pending ? 0.56 : 1
                  activeFocusOnTab: true
                  Accessible.role: Accessible.Button
                  Accessible.name: (parentRow ? (expanded ? "Expanded parent " : "Collapsed parent ") : "Task ")
                    + Model.displayTitle(modelData, 120) + ", " + root.taskClock(modelData, current)
                    + (root.contextText(modelData) !== "" ? ", " + root.contextText(modelData) : "")
                    + (current ? ", current" : (pending ? ", pending" : ""))
                  Accessible.description: parentRow
                    ? ((searchField.text.trim() === "" ? "Press Enter to toggle subtasks. " : "Search result; collapse state is unchanged. ")
                      + "Complete is not available. Complete subtasks first; Super Productivity manages the parent.")
                    : "Use Start or press Enter to start. Use Complete or press C to complete"
                  Accessible.onPressAction: activate()

                  Keys.onPressed: function(event) { root.handleRowKey(event, todayRow) }
                  onActiveFocusChanged: if (activeFocus) {
                    root.todayCursorIndex = index
                    root.focusedTaskId = taskIdentifier
                  }

                  HoverHandler { id: hover }
                  Row {
                    anchors.fill: parent
                    anchors.leftMargin: Style.space(10) + todayRow.indent
                    anchors.rightMargin: Style.space(8)
                    spacing: Style.space(8)

                    Text {
                      visible: todayRow.parentRow
                      anchors.verticalCenter: parent.verticalCenter
                      width: Style.space(12)
                      text: todayRow.expanded || searchField.text.trim() !== "" ? "▾" : "▸"
                      textFormat: Text.PlainText
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                    }

                    Column {
                      id: rowTextArea
                      anchors.verticalCenter: parent.verticalCenter
                      width: parent.width - (todayRow.parentRow ? Style.space(20) : 0) - rowActions.width - parent.spacing
                      spacing: Style.space(2)
                      TapHandler {
                        acceptedButtons: Qt.LeftButton
                        onTapped: {
                          todayRow.forceActiveFocus(Qt.MouseFocusReason)
                          todayRow.activate()
                        }
                      }
                      Text {
                        width: parent.width
                        text: Model.displayTitle(todayRow.modelData, 120)
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        color: todayRow.current ? root.accent : (todayRow.pending ? root.urgent : root.foreground)
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.bold: todayRow.current || todayRow.pending || todayRow.parentRow
                      }
                      Text {
                        width: parent.width
                        text: (todayRow.current ? "CURRENT · " : (todayRow.pending ? "PENDING · " : ""))
                          + root.taskClock(todayRow.modelData, todayRow.current)
                          + (root.contextText(todayRow.modelData) !== "" ? " · " + root.contextText(todayRow.modelData) : "")
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        color: todayRow.overdue ? root.urgent : (todayRow.current ? root.accent : (todayRow.pending ? root.urgent : root.dim))
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }

                    Row {
                      id: rowActions
                      anchors.verticalCenter: parent.verticalCenter
                      width: (completeControl.visible ? completeControl.width : 0)
                        + (startControl.visible ? startControl.width + (completeControl.visible ? spacing : 0) : 0)
                      spacing: Style.space(5)
                      Button {
                        id: startControl
                        visible: todayRow.canStart
                        width: Style.space(56)
                        text: todayRow.current ? "Active" : (todayRow.pending ? "Starting…" : "Start")
                        bordered: true
                        enabled: !root.mutationBusy && !todayRow.current
                        foreground: todayRow.current ? root.accent : root.foreground
                        fontFamily: root.fontFamily
                        focusable: true
                        Accessible.name: "Start " + Model.displayTitle(todayRow.modelData, 120)
                        Accessible.role: Accessible.Button
                        onActiveFocusChanged: if (activeFocus) {
                          root.todayCursorIndex = todayRow.index
                          root.focusedTaskId = todayRow.taskIdentifier
                          Qt.callLater(function() { scroller.reveal(todayRow) })
                        }
                        onClicked: root.startTodayTask(todayRow.modelData)
                        Accessible.onPressAction: root.startTodayTask(todayRow.modelData)
                      }
                      Button {
                        id: completeControl
                        visible: !todayRow.parentRow
                        width: visible ? Style.space(72) : 0
                        text: todayRow.pending && root.engine && String(root.engine.mutationKind || "").indexOf("complete") === 0 ? "Working…" : "Complete"
                        bordered: true
                        enabled: visible && !root.mutationBusy
                        foreground: root.foreground
                        fontFamily: root.fontFamily
                        focusable: true
                        tooltipText: "Complete " + Model.displayTitle(todayRow.modelData, 120)
                        Accessible.name: "Complete " + Model.displayTitle(todayRow.modelData, 120)
                        Accessible.description: todayRow.current
                          ? "Completes the current task. Auto-next considers scheduled tasks only within the configured schedule window"
                          : "Completes this listed task"
                        Accessible.role: Accessible.Button
                        onActiveFocusChanged: if (activeFocus) {
                          root.todayCursorIndex = todayRow.index
                          root.focusedTaskId = todayRow.taskIdentifier
                          Qt.callLater(function() { scroller.reveal(todayRow) })
                        }
                        onClicked: root.completeTodayTask(todayRow.modelData)
                        Accessible.onPressAction: root.completeTodayTask(todayRow.modelData)
                      }
                    }
                  }
                }
              }

              ResultFeedback { visible: root.todayState !== ""; resultState: root.todayState; message: root.todayMessage }
            }
          }

          }

          Item {
            width: parent.width
            height: root.goTopVisible ? Style.space(58) : 0
            visible: height > 0
            Accessible.ignored: true
          }
        }
      }

      Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: Style.space(12)
        anchors.bottomMargin: Style.space(12)
        width: goTopButton.width + Style.space(4)
        height: goTopButton.height + Style.space(4)
        radius: Style.cornerRadius
        color: Color.popups.background
        border.width: goTopButton.activeFocus ? 2 : 1
        border.color: goTopButton.activeFocus ? root.accent : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.4)
        visible: root.goTopVisible
        z: 20

        Button {
          id: goTopButton
          anchors.centerIn: parent
          width: Style.space(92)
          height: Style.space(34)
          text: "↑ Go top"
          bordered: false
          visible: root.goTopVisible
          enabled: visible
          activeFocusOnTab: visible
          focusable: visible
          foreground: root.foreground
          fontFamily: root.fontFamily
          tooltipText: "Scroll to top (Home)"
          Accessible.name: "Go to top"
          Accessible.description: root.settingsView
            ? "Scrolls to the top and moves focus to Back"
            : (root.quickAddCollapsed
              ? "Scrolls to the top and moves focus to the first visible header control"
              : "Scrolls to the top and moves focus to Quick Add")
          Accessible.role: Accessible.Button
          onClicked: root.goTop()
          Accessible.onPressAction: root.goTop()
        }
      }
    }
  }

  component SettingNumber: Rectangle {
    id: numberSetting
    property string label: ""
    property string description: ""
    property string settingKey: ""
    property int fallbackValue: 0
    property int minimum: 0
    property int maximum: 100
    property int step: 1
    property string suffix: ""
    property string minimumLabel: ""
    property string maximumLabel: ""
    property bool immediate: false
    width: parent ? parent.width : 0
    implicitHeight: Style.space(minimumLabel !== "" || maximumLabel !== "" ? 78 : 68)
    radius: Style.cornerRadius
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.04)
    border.width: numberField.activeFocus ? 1 : 0
    border.color: root.accent

    Column {
      anchors.left: parent.left
      anchors.right: controls.left
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      anchors.verticalCenterOffset: rangeLabels.visible ? -Style.space(7) : 0
      spacing: Style.space(2)
      Text { width: parent.width; text: numberSetting.label; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; elide: Text.ElideRight }
      Text {
        width: parent.width
        text: numberSetting.description + " · "
          + (numberSetting.minimumLabel !== "" ? numberSetting.minimumLabel : numberSetting.minimum + numberSetting.suffix)
          + "–"
          + (numberSetting.maximumLabel !== "" ? numberSetting.maximumLabel : numberSetting.maximum + numberSetting.suffix)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
    Row {
      id: controls
      anchors.right: parent.right
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(6)
      TextField {
        id: numberField
        width: Style.space(74)
        text: String(root.setting(numberSetting.settingKey, numberSetting.fallbackValue))
        foreground: root.foreground
        accent: root.accent
        inputMethodHints: Qt.ImhDigitsOnly
        validator: IntValidator { bottom: numberSetting.minimum; top: numberSetting.maximum }
        Accessible.name: numberSetting.label + ", " + numberSetting.minimum + " to " + numberSetting.maximum + " " + numberSetting.suffix
        onActiveFocusChanged: {
          root.editableControlFocused = activeFocus
          if (activeFocus) Qt.callLater(function() { scroller.reveal(numberField) })
        }
        Keys.onReturnPressed: function(event) { event.accepted = true; numberSetting.applyValue() }
        Keys.onEnterPressed: function(event) { event.accepted = true; numberSetting.applyValue() }
        onEditingFinished: if (numberSetting.immediate && acceptableInput) numberSetting.applyValue()
      }
      Button {
        id: numberApply
        width: Style.space(62)
        text: "Apply"
        visible: !numberSetting.immediate
        enabled: visible
        activeFocusOnTab: visible
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        focusable: true
        Accessible.name: "Apply " + numberSetting.label
        Accessible.role: Accessible.Button
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { scroller.reveal(numberApply) })
        onClicked: numberSetting.applyValue()
        Accessible.onPressAction: numberSetting.applyValue()
      }
    }
    Text {
      id: rangeLabels
      visible: numberSetting.minimumLabel !== "" || numberSetting.maximumLabel !== ""
      anchors.right: parent.right
      anchors.rightMargin: Style.space(8)
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.space(7)
      width: controls.width
      text: numberSetting.minimumLabel + "  ·  " + numberSetting.maximumLabel
      textFormat: Text.PlainText
      horizontalAlignment: Text.AlignHCenter
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
    function applyValue() {
      var value = String(numberField.text || "").trim()
      if (!/^\d+$/.test(value) || Number(value) < minimum || Number(value) > maximum
          || (step > 1 && Number(value) !== minimum && Number(value) % step !== 0)) {
        root.settingsState = "failed"
        root.settingsMessage = label + " must be a whole number from " + minimum + " to " + maximum
          + (step > 1 ? " in steps of " + step : "")
        numberField.forceActiveFocus(Qt.OtherFocusReason)
        return
      }
      if (root.persistSetting(settingKey, Number(value), label)
          && settingKey === "alertVolume") root.alertVolumeOverride = Number(value)
    }
  }

  component SettingToggle: Rectangle {
    id: toggleSetting
    property string label: ""
    property string description: ""
    property string settingKey: ""
    property bool fallbackValue: false
    width: parent ? parent.width : 0
    implicitHeight: Style.space(56)
    radius: Style.cornerRadius
    color: toggleSetting.activeFocus ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.09)
                                      : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.04)
    border.width: toggleSetting.activeFocus ? 2 : 0
    border.color: root.accent
    activeFocusOnTab: true
    Accessible.name: toggleSetting.label
    Accessible.description: toggleSetting.description
    Accessible.role: Accessible.CheckBox
    Accessible.checked: root.boolSetting(toggleSetting.settingKey, toggleSetting.fallbackValue)
    Accessible.onPressAction: toggleSetting.toggleValue()
    Keys.onReturnPressed: function(event) { event.accepted = true; toggleSetting.toggleValue() }
    Keys.onEnterPressed: function(event) { event.accepted = true; toggleSetting.toggleValue() }
    Keys.onSpacePressed: function(event) { event.accepted = true; toggleSetting.toggleValue() }
    onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { scroller.reveal(toggleSetting) })
    Column {
      anchors.left: parent.left
      anchors.right: settingSwitch.left
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)
      Text { width: parent.width; text: toggleSetting.label; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; elide: Text.ElideRight }
      Text { width: parent.width; text: toggleSetting.description; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
    }
    ToggleSwitch {
      id: settingSwitch
      anchors.right: parent.right
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      checked: root.boolSetting(toggleSetting.settingKey, toggleSetting.fallbackValue)
      interactive: false
      hasCursor: toggleSetting.activeFocus
      foreground: root.foreground
      accent: root.accent
    }
    TapHandler {
      acceptedButtons: Qt.LeftButton
      onTapped: {
        toggleSetting.forceActiveFocus(Qt.MouseFocusReason)
        toggleSetting.toggleValue()
      }
    }
    function toggleValue() {
      root.persistSetting(settingKey,
                          !root.boolSetting(settingKey, fallbackValue),
                          label)
    }
  }

  component SettingText: Rectangle {
    id: textSetting
    property string label: ""
    property string description: ""
    property string settingKey: ""
    property string fallbackValue: ""
    property string placeholder: ""
    width: parent ? parent.width : 0
    implicitHeight: Style.space(94)
    radius: Style.cornerRadius
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.04)
    Column {
      anchors.fill: parent
      anchors.margins: Style.space(9)
      spacing: Style.space(5)
      Text { width: parent.width; text: textSetting.label; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body }
      Text { width: parent.width; text: textSetting.description; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
      Row {
        width: parent.width
        spacing: Style.space(7)
        TextField {
          id: settingTextField
          width: parent.width - textApply.width - parent.spacing
          text: String(root.setting(textSetting.settingKey, textSetting.fallbackValue) || "")
          placeholderText: textSetting.placeholder
          foreground: root.foreground
          accent: root.accent
          Accessible.name: textSetting.label
          onActiveFocusChanged: {
            root.editableControlFocused = activeFocus
            if (activeFocus) Qt.callLater(function() { scroller.reveal(settingTextField) })
          }
          Keys.onReturnPressed: function(event) { event.accepted = true; textSetting.applyValue() }
          Keys.onEnterPressed: function(event) { event.accepted = true; textSetting.applyValue() }
        }
        Button {
          id: textApply
          width: Style.space(62)
          text: "Apply"
          bordered: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          focusable: true
          Accessible.name: "Apply " + textSetting.label
          Accessible.role: Accessible.Button
          onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { scroller.reveal(textApply) })
          onClicked: textSetting.applyValue()
          Accessible.onPressAction: textSetting.applyValue()
        }
      }
    }
    function applyValue() {
      var value = String(settingTextField.text || "").trim()
      if (/[\u0000-\u001f\u007f]/.test(value)) {
        root.settingsState = "failed"
        root.settingsMessage = label + " contains an unsupported control character"
        settingTextField.forceActiveFocus(Qt.OtherFocusReason)
        return
      }
      root.persistSetting(settingKey, value, label)
    }
  }

  component SettingChoice: Rectangle {
    id: choiceSetting
    property string label: ""
    property string description: ""
    property string settingKey: ""
    property string fallbackValue: ""
    property var choices: []
    width: parent ? parent.width : 0
    implicitHeight: choiceLayout.implicitHeight + Style.space(18)
    radius: Style.cornerRadius
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.04)
    Column {
      id: choiceLayout
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.space(9)
      spacing: Style.space(5)
      Text { width: parent.width; text: choiceSetting.label; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; wrapMode: Text.WordWrap }
      Text { width: parent.width; text: choiceSetting.description; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; wrapMode: Text.WordWrap }
      Flow {
        id: choiceFlow
        width: parent.width
        spacing: Style.space(6)
        Repeater {
          model: choiceSetting.choices
          Button {
            id: choiceButton
            required property var modelData
            readonly property bool selected: String(root.setting(choiceSetting.settingKey, choiceSetting.fallbackValue)) === String(modelData.value)
            width: Math.min(choiceFlow.width, Math.max(Style.space(74), String(modelData.label).length * Style.font.body * 0.62 + Style.space(24)))
            text: String(modelData.label)
            bordered: true
            foreground: selected ? root.accent : root.foreground
            fontFamily: root.fontFamily
            focusable: true
            Accessible.name: choiceSetting.label + ": " + modelData.label
            Accessible.description: selected ? "Selected" : "Not selected"
            Accessible.role: Accessible.RadioButton
            Accessible.checked: selected
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { scroller.reveal(choiceButton) })
            onClicked: root.persistSetting(choiceSetting.settingKey, modelData.value, choiceSetting.label)
            Accessible.onPressAction: root.persistSetting(choiceSetting.settingKey, modelData.value, choiceSetting.label)
          }
        }
      }
    }
  }

  component Metric: Rectangle {
    id: metric
    property string label: ""
    property string value: ""
    property bool emphasis: false
    property bool warning: false
    height: Style.space(48)
    radius: Style.cornerRadius
    color: warning
      ? Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.13)
      : (emphasis ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.11)
                  : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.05))
    border.width: emphasis ? 1 : 0
    border.color: warning ? root.urgent : Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.35)
    Accessible.role: Accessible.StaticText
    Accessible.name: label + ": " + value
    Column {
      anchors.centerIn: parent
      spacing: Style.space(2)
      Text { anchors.horizontalCenter: parent.horizontalCenter; text: metric.label; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.letterSpacing: 0.7 }
      Text { anchors.horizontalCenter: parent.horizontalCenter; text: metric.value; color: metric.warning ? root.urgent : (metric.emphasis ? root.accent : root.foreground); font.family: root.fontFamily; font.pixelSize: metric.emphasis ? Style.font.title : Style.font.body; font.bold: metric.emphasis }
    }
  }

  component ActionButton: Button {
    id: action
    property string accessibleText: text
    signal triggered()
    implicitWidth: Math.max(Style.space(76), action.text.length * Style.font.body * 0.65 + Style.space(24))
    bordered: true
    foreground: root.foreground
    fontFamily: root.fontFamily
    focusable: true
    Accessible.name: accessibleText
    Accessible.role: Accessible.Button
    onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { scroller.reveal(action) })
    onClicked: triggered()
    Accessible.onPressAction: triggered()
  }

  component SectionToggle: Rectangle {
    id: section
    property string text: ""
    property bool collapsed: false
    property string countText: ""
    property string accessibleText: ""
    signal triggered()
    width: parent ? parent.width : 0
    height: Style.space(34)
    radius: Style.cornerRadius
    color: hover.hovered || activeFocus ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.07) : "transparent"
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: accessibleText
    Accessible.onPressAction: triggered()
    Keys.onReturnPressed: function(event) { event.accepted = true; triggered() }
    Keys.onEnterPressed: function(event) { event.accepted = true; triggered() }
    Keys.onSpacePressed: function(event) { event.accepted = true; triggered() }
    HoverHandler { id: hover }
    TapHandler { acceptedButtons: Qt.LeftButton; onTapped: { section.forceActiveFocus(); section.triggered() } }
    Row {
      anchors.fill: parent
      anchors.leftMargin: Style.space(3)
      anchors.rightMargin: Style.space(3)
      spacing: Style.space(7)
      Text { anchors.verticalCenter: parent.verticalCenter; text: section.collapsed ? "▸" : "▾"; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.body }
      Text { anchors.verticalCenter: parent.verticalCenter; text: section.text; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 0.9 }
      Item { width: Math.max(0, parent.width - parent.children[0].width - parent.children[1].width - count.width - parent.spacing * 3); height: 1 }
      Text { id: count; visible: text !== ""; anchors.verticalCenter: parent.verticalCenter; text: section.countText; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
    }
  }

  component FeedbackText: Text {
    property string resultState: ""
    property string message: ""
    property bool announce: false
    width: parent ? parent.width : 0
    text: message
    textFormat: Text.PlainText
    color: resultState === "failed" || resultState === "conflict" || resultState === "unknown" || resultState === "partial" ? root.urgent : root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
    Accessible.role: announce ? Accessible.AlertMessage : Accessible.StaticText
    Accessible.name: message
  }

  component ResultFeedback: Rectangle {
    id: feedback
    property string resultState: ""
    property string message: ""
    width: parent ? parent.width : 0
    implicitHeight: feedbackRow.implicitHeight + Style.space(14)
    radius: Style.cornerRadius
    readonly property bool positive: resultState === "succeeded"
    readonly property bool pending: resultState === "running"
    color: positive
      ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.09)
      : (pending ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.06)
                 : Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.09))
    border.width: 1
    border.color: positive ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.35)
                           : (pending ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.24)
                                      : Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.35))
    Accessible.role: Accessible.AlertMessage
    Accessible.name: resultState + ": " + message
    Row {
      id: feedbackRow
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(8)
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(8)
      Text { text: feedback.resultState.toUpperCase(); color: feedback.positive ? root.accent : (feedback.pending ? root.dim : root.urgent); font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 0.6 }
      Text { width: parent.width - parent.children[0].width - parent.spacing; text: feedback.message; textFormat: Text.PlainText; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.caption; wrapMode: Text.WordWrap }
    }
  }
}
