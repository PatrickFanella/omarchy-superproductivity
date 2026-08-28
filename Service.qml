import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model
import "ActionModel.js" as Actions
import "I18n.js" as I18n

Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string pluginId: "patrickfanella.superproductivity"
  readonly property string pluginDir: manifest && manifest.__sourceDir
    ? String(manifest.__sourceDir)
    : (Quickshell.env("HOME") || "") + "/.config/omarchy/plugins/" + pluginId
  readonly property string helperPath: pluginDir + "/backend/superproductivity.py"
  readonly property string localeName: I18n.resolveLocale(Qt.locale().name)

  property var snapshot: ({ ok: true, currentTask: null, todayTasks: [] })
  property string errorText: ""
  property string ipcErrorText: ""
  property string contextWarning: ""
  property string contextWarningText: ""
  property string alertError: ""
  property string ipcAlertError: ""
  property bool refreshing: false
  readonly property bool todayRefreshing: refreshing
  property bool refreshPending: false
  property var statusReply: null
  property double mutationEpoch: 0

  property double clockMs: Date.now()
  property double sampledAtMs: clockMs
  property double lastTickMs: clockMs
  property real signedAtSample: 0
  property double fetchedAt: 0
  property bool localZeroRefreshRequested: false
  property var expiryState: ({ taskId: "", phase: "idle", positiveCount: 0 })
  property var scheduleState: ({ initialized: false, cursorMs: 0, seenKeys: [] })
  property bool scheduleContextFresh: false
  property bool authoritativeExpired: false

  readonly property double serviceStartedAt: Date.now()
  property int nextActionCounter: 1
  property var actionQueue: []
  property var currentAction: null
  property var actionReply: null
  property var actionResults: []
  readonly property bool mutationBusy: currentAction !== null || actionQueue.length > 0
  readonly property string mutationKind: currentAction ? String(currentAction.kind) : ""
  readonly property string mutationTaskId: currentAction ? String(currentAction.taskId || "") : ""
  readonly property string switchingTaskId: mutationKind === "start" ? mutationTaskId : ""

  property bool showBusy: false
  property string showMessage: ""
  property var showReply: null
  property bool testNotificationBusy: false
  property string testNotificationState: "idle"
  property string testNotificationMessage: ""
  property string ipcTestNotificationMessage: ""
  property var testReply: null
  property var previewQueue: []
  readonly property bool previewBusy: previewProcess.running || previewQueue.length > 0
  property string previewState: "idle"
  property string previewMessage: ""
  property string ipcPreviewMessage: ""
  property var previewReply: null

  property var alertReply: null
  property var alertQueue: []
  property var currentAlert: null
  property bool alertWaitingForPreview: false

  signal actionFinished(string requestId, string kind, bool ok, string message, var result)

  readonly property var currentTask: snapshot ? snapshot.currentTask || null : null
  readonly property var todayTasks: Model.chronologicalHierarchy(
    snapshot && Array.isArray(snapshot.todayTasks) ? snapshot.todayTasks : [])
  readonly property var nextScheduledTask: scheduleContextFresh
    ? Model.nextScheduledTask(todayTasks, clockMs) : null
  readonly property double nextScheduledStartMs: nextScheduledTask ? Number(nextScheduledTask.dueWithTime) : 0
  readonly property string nextScheduledTitle: nextScheduledTask
    ? String(nextScheduledTask.title || nextScheduledTask.name || tr("common.untitledTask")) : ""
  readonly property real estimateMs: currentTask ? numberField(currentTask, "timeEstimate", 0) : 0
  readonly property real spentMs: currentTask ? numberField(currentTask, "timeSpent", 0) : 0
  readonly property real signedRemainingMs: currentTask
    ? signedAtSample - Math.max(0, clockMs - sampledAtMs)
    : 0
  readonly property real remainingMs: Math.max(0, signedRemainingMs)
  readonly property real overtimeMs: Math.max(0, -signedRemainingMs)
  readonly property bool timerExpired: currentTask !== null && estimateMs > 0 && signedRemainingMs <= 0
  readonly property int pollSeconds: intSetting("pollSeconds", 5, 2, 30)
  readonly property bool alertEnabled: boolSetting("alertEnabled", true)
  readonly property bool soundEnabled: boolSetting("soundEnabled", true)
  readonly property string soundPath: String(setting("soundPath", "") || "")
  readonly property int alertVolume: volumeSetting()
  readonly property bool autoStartNext: boolSetting("autoStartNext", false)
  readonly property int autoNextWindowMinutes: Actions.strictIntegerSetting(
    configEntry(), "autoNextWindowMinutes", 30, 1, 1440)
  readonly property bool quickAddSwitch: Actions.quickAddSwitch(
    setting("quickAddSwitch", undefined), setting("quickAddEnterAction", ""))
  readonly property bool startAfterAddDefault: quickAddSwitch
  readonly property string notificationUrgency: urgencySetting()

  function tr(key, args) {
    return I18n.translate(localeName, key, args || {})
  }

  function warningDisplay(codes) {
    return I18n.joinSentences(codes.map(function(code) { return I18n.warningText(localeName, code) }))
  }

  function setError(key, args) {
    errorText = key ? tr(key, args) : ""
    ipcErrorText = key ? I18n.translate("en", key, args || {}) : ""
  }

  function setPreviewMessage(key) {
    previewMessage = key ? tr(key) : ""
    ipcPreviewMessage = key ? I18n.translate("en", key) : ""
  }

  function numberField(object, key, fallback) {
    var number = object ? Number(object[key]) : NaN
    return isFinite(number) ? number : fallback
  }

  function taskId(task) {
    return String(task && (task.id !== undefined ? task.id : task._id) || "")
  }

  function entriesIn(config) {
    var groups = []
    if (config && config.bar && config.bar.layout) {
      var regions = ["left", "center", "right"]
      for (var i = 0; i < regions.length; i++) {
        var list = config.bar.layout[regions[i]]
        if (list && typeof list.length === "number") groups.push(list)
      }
    }
    if (config && config.plugins && typeof config.plugins.length === "number") groups.push(config.plugins)
    return groups
  }

  function configEntry() {
    var config = shell && shell.shellConfig ? shell.shellConfig : null
    var groups = entriesIn(config)
    for (var group = 0; group < groups.length; group++) {
      for (var index = 0; index < groups[group].length; index++) {
        var entry = groups[group][index]
        if (entry && String(entry.id || "") === pluginId) return entry
      }
    }
    return null
  }

  function setting(name, fallback) {
    return Actions.settingValue(configEntry(), name, fallback)
  }

  function intSetting(name, fallback, minimum, maximum) {
    var value = parseInt(String(setting(name, fallback)), 10)
    if (!isFinite(value)) value = fallback
    return Math.max(minimum, Math.min(maximum, value))
  }

  function boolSetting(name, fallback) {
    var value = setting(name, fallback)
    if (typeof value === "string") return value.toLowerCase() !== "false" && value !== "0"
    return !!value
  }

  function volumeSetting() {
    return Actions.integerSetting(configEntry(), "alertVolume", 100, 0, 100)
  }

  function urgencySetting() {
    var value = String(setting("notificationUrgency", "critical"))
    return value === "low" || value === "normal" || value === "critical" ? value : "critical"
  }

  function parseObject(text) {
    try {
      var value = JSON.parse(String(text || "").trim())
      return value && typeof value === "object" && !Array.isArray(value) ? value : null
    } catch (error) {
      return null
    }
  }

  function validTaskId(value) {
    return Actions.validTaskId(value)
  }

  function parseBoolean(value, fallback) {
    if (value === undefined || value === null || value === "") return { ok: true, value: fallback }
    if (value === true || value === "true" || value === "1") return { ok: true, value: true }
    if (value === false || value === "false" || value === "0") return { ok: true, value: false }
    return { ok: false, error: "invalid-boolean" }
  }

  function statusIsValid(response, normalized) {
    return Actions.validRawStatus(response)
      && normalized && normalized.ok !== false
      && Object.prototype.hasOwnProperty.call(normalized, "currentTask")
      && Array.isArray(normalized.todayTasks)
      && (normalized.currentTask === null || isFinite(Number(normalized.signedRemainingMs)))
      && isFinite(Number(normalized.fetchedAt))
  }

  function applyStatus(response) {
    try {
      if (!Actions.validRawStatus(response)) throw new Error("invalid raw status")
      var normalized = Model.normalizeStatus(response)
      if (!statusIsValid(response, normalized)) throw new Error("invalid status")
      var freshScheduleContext = Actions.hasFreshScheduleContext(normalized)
      var schedule = { state: scheduleState, alerts: [] }
      if (freshScheduleContext) {
        schedule = Model.reduceSchedule(
          scheduleState, normalized.scheduledTasks, normalized.todayFetchedAt, normalized.currentTask)
      }
      if (!schedule || !schedule.state || !Array.isArray(schedule.alerts)) throw new Error("invalid schedule")
      normalized = Actions.mergeStatus(snapshot, normalized)
      var now = Date.now()
      var projected = normalized.currentTask
        ? Model.projectSignedRemaining(normalized.signedRemainingMs, normalized.fetchedAt, now)
        : 0
      var transition = Model.advanceExpiry(expiryState, normalized.currentTask, projected)
      if (!transition || !transition.state) throw new Error("invalid expiry")

      snapshot = normalized
      signedAtSample = projected
      sampledAtMs = now
      clockMs = now
      lastTickMs = now
      fetchedAt = Number(normalized.fetchedAt)
      localZeroRefreshRequested = projected <= 0
      expiryState = transition.state
      scheduleState = schedule.state
      scheduleContextFresh = freshScheduleContext
      authoritativeExpired = !!transition.expired
      var warnings = normalized.context && Array.isArray(normalized.context.warnings)
        ? normalized.context.warnings : []
      contextWarning = warnings.join(", ")
      contextWarningText = warningDisplay(warnings)
      setError("")
      if (transition.shouldAlert) attemptAlert(normalized.currentTask, "timer")
      if (schedule.alerts.length > 0)
        attemptAlert({ title: tr("notification.scheduledNow", { title: String(schedule.alerts[0].title || tr("common.untitledTask")) }) }, "scheduled")
      return true
    } catch (error) {
      setError("service.invalidStatus")
      return false
    }
  }

  function refresh() {
    if (statusProcess.running || mutationBusy) {
      refreshPending = true
      return
    }
    refreshPending = false
    refreshing = true
    statusReply = null
    statusProcess.launchEpoch = mutationEpoch
    statusProcess.completed = false
    statusProcess.command = [helperPath, "status"]
    statusProcess.running = true
  }

  function finishStatus(code) {
    if (statusProcess.completed) return
    statusProcess.completed = true
    refreshing = false
    var stale = statusProcess.launchEpoch !== mutationEpoch || mutationBusy
    if (!stale) {
      if (code !== 0) setError("service.statusFailed", { exitCode: code })
      else if (!statusReply) setError("service.unreadableStatus")
      else applyStatus(statusReply)
    }
    if (refreshPending && !mutationBusy) Qt.callLater(refresh)
  }

  function acceptance(request) {
    var queued = Actions.enqueue(actionQueue, currentAction, request)
    if (!queued.accepted) return { accepted: false, error: queued.error }
    actionQueue = queued.queue
    startNextAction()
    return { accepted: true, requestId: request.id }
  }

  function makeRequest(kind, taskIdentifier, args) {
    var id = Actions.requestId(serviceStartedAt, nextActionCounter++)
    return { id: id, kind: kind, taskId: taskIdentifier || "", args: args || [], queuedAt: Date.now() }
  }

  function add(shorthand, startAfter) {
    var text = String(shorthand === undefined || shorthand === null ? "" : shorthand)
    if (!text.trim() || /[\u0000-\u001f\u007f]/.test(text)) return { accepted: false, error: "invalid-shorthand" }
    var parsed = parseBoolean(startAfter, startAfterAddDefault)
    if (!parsed.ok) return { accepted: false, error: parsed.error }
    var args = [helperPath, "add", text]
    if (parsed.value) args.push("--start")
    return acceptance(makeRequest("add", "", args))
  }

  function startTask(id) {
    var value = String(id === undefined || id === null ? "" : id)
    if (!validTaskId(value)) return { accepted: false, error: "invalid-task-id" }
    return acceptance(makeRequest("start", value, [helperPath, "start", value]))
  }

  function stopTask(id) {
    var value = String(id === undefined || id === null ? "" : id)
    if (!validTaskId(value)) return { accepted: false, error: "invalid-task-id" }
    return acceptance(makeRequest("stop", value, [helperPath, "stop", value]))
  }

  function completeTask(id, autoNext) {
    var value = String(id === undefined || id === null ? "" : id)
    if (!validTaskId(value)) return { accepted: false, error: "invalid-task-id" }
    var parsed = parseBoolean(autoNext, autoStartNext)
    if (!parsed.ok) return { accepted: false, error: parsed.error }
    var args = Actions.completeCommand(helperPath, value, parsed.value, autoNextWindowMinutes)
    return acceptance(makeRequest("complete", value, args))
  }

  function completeListedTask(id) {
    var value = String(id === undefined || id === null ? "" : id)
    if (!validTaskId(value)) return { accepted: false, error: "invalid-task-id" }
    return acceptance(makeRequest("complete-list", value, [helperPath, "complete-task", value]))
  }

  function extendTask(id, minutes) {
    var value = String(id === undefined || id === null ? "" : id)
    var minuteText = String(minutes === undefined || minutes === null ? "" : minutes)
    if (!validTaskId(value)) return { accepted: false, error: "invalid-task-id" }
    if (!/^\d+$/.test(minuteText) || Number(minuteText) < 1 || Number(minuteText) > 1440)
      return { accepted: false, error: "invalid-minutes" }
    return acceptance(makeRequest("extend", value, [helperPath, "extend", value, minuteText]))
  }

  function recordResult(result) {
    actionResults = Actions.retain(actionResults, result, Date.now())
    mutationEpoch += 1
    refreshPending = true
    actionFinished(result.requestId, result.kind, result.ok, result.message, result)
  }

  function startNextAction() {
    if (actionProcess.running || currentAction) return
    var taken = Actions.takeNext(actionQueue, Date.now())
    actionQueue = taken.queue
    for (var index = 0; index < taken.expired.length; index++) recordResult(taken.expired[index])
    if (!taken.request) {
      if (refreshPending) Qt.callLater(refresh)
      return
    }
    currentAction = taken.request
    actionReply = null
    actionProcess.completed = false
    actionProcess.command = currentAction.args
    actionProcess.running = true
  }

  function finishAction(code, launchFailed) {
    if (!currentAction || actionProcess.completed) return
    actionProcess.completed = true
    var completed = currentAction
    var reply = actionReply
    if (launchFailed) reply = {
      kind: String(completed.kind), targetTaskId: completed.taskId ? String(completed.taskId) : null,
      state: "failed", stage: "dispatch", mutationApplied: false,
      expectedCurrentId: null, observedCurrentId: null, finalCurrentId: null,
      raceDetected: false, createdTaskId: null,
      message: "Super Productivity helper could not be started",
      messageKey: "helper-start-failed"
    }
    var result = Actions.normalizeResult(completed, reply, code, Date.now())
    currentAction = null
    recordResult(result)
    Qt.callLater(startNextAction)
  }

  function action(id) {
    actionResults = Actions.retain(actionResults, null, Date.now())
    return Actions.lookup(String(id), actionQueue, currentAction, actionResults, Date.now())
  }

  function show() {
    if (showProcess.running) return { accepted: false, error: "show-busy" }
    showBusy = true
    showMessage = ""
    showReply = null
    showProcess.command = [helperPath, "show"]
    showProcess.running = true
    return { accepted: true }
  }

  function testNotification() {
    if (testProcess.running) return { accepted: false, error: "test-busy" }
    testNotificationBusy = true
    testNotificationState = "running"
    testNotificationMessage = ""
    ipcTestNotificationMessage = ""
    testReply = null
    testProcess.completed = false
    testProcess.command = [
      helperPath, "test-notification", "--urgency", notificationUrgency,
      "--notification-title", tr("notification.title"),
      "--body", tr("notification.testBody")
    ]
    testProcess.running = true
    return { accepted: true }
  }

  function finishTestNotification(code, launchFailed) {
    if (testProcess.completed) return
    testProcess.completed = true
    testNotificationBusy = false
    testNotificationState = launchFailed ? "failed" : Model.sideEffectState(code, testReply)
    var diagnostic = testReply && (testReply.message || testReply.error)
    if (diagnostic) {
      testNotificationMessage = String(diagnostic)
      ipcTestNotificationMessage = String(diagnostic)
    } else {
      var key = launchFailed ? "service.helperStartFailed"
                             : (code === 0 ? "notification.sent" : "notification.testFailed")
      testNotificationMessage = tr(key)
      ipcTestNotificationMessage = I18n.translate("en", key)
    }
  }

  function previewSound(volume) {
    var parsed = Actions.previewVolume(volume, alertVolume)
    if (!parsed.ok) return { accepted: false, error: parsed.error }
    previewQueue = previewQueue.concat([parsed.value])
    previewState = "running"
    setPreviewMessage("")
    previewReply = null
    drainPreviews()
    return { accepted: true }
  }

  function drainPreviews() {
    if (previewProcess.running || previewQueue.length === 0 || alertWaitingForPreview) return
    var volume = previewQueue[0]
    previewQueue = previewQueue.slice(1)
    previewReply = null
    setPreviewMessage("")
    previewState = "running"
    previewProcess.completed = false
    var args = [helperPath, "preview-sound"]
    if (soundPath !== "") args.push("--sound", soundPath)
    args.push("--volume", String(volume))
    previewProcess.command = args
    previewProcess.running = true
  }

  function attemptAlert(task, kind) {
    if (!alertEnabled) return
    alertQueue = Model.enqueueAlert(alertQueue, {
      title: String(task && (task.title || task.name) || tr("notification.timerExpired")),
      kind: kind || "timer",
      queuedAt: Date.now()
    }, 16)
    var cancelledPreview = previewProcess.running || previewQueue.length > 0
    previewQueue = []
    if (cancelledPreview) {
      previewState = "failed"
      setPreviewMessage("sound.previewCancelled")
    }
    if (previewProcess.running) {
      alertWaitingForPreview = true
      previewProcess.running = false
      previewStopFallback.restart()
    } else {
      drainAlerts()
    }
  }

  function drainAlerts() {
    if (alertWaitingForPreview || alertProcess.running || currentAlert || alertQueue.length === 0) return
    var taken = Model.takeNextAlert(alertQueue, Date.now())
    currentAlert = taken.alert
    alertQueue = taken.queue
    if (!currentAlert) return
    var args = [helperPath, "alert", "--urgency", notificationUrgency]
    args.push("--volume", String(alertVolume))
    if (!soundEnabled) args.push("--silent")
    else if (soundPath !== "") args.push("--sound", soundPath)
    args.push("--notification-title", tr("notification.title"))
    args.push("--", currentAlert.title)
    alertReply = null
    alertProcess.command = args
    alertProcess.running = true
  }

  function finishAlert(code) {
    if (!currentAlert) return
    if (code !== 0 || !alertReply || alertReply.ok === false) {
      if (alertReply && (alertReply.error || alertReply.message)) {
        alertError = String(alertReply.error || alertReply.message)
        ipcAlertError = alertError
      } else {
        alertError = tr("service.alertFailed", { exitCode: code })
        ipcAlertError = I18n.translate("en", "service.alertFailed", { exitCode: code })
      }
    } else {
      alertError = ""
      ipcAlertError = ""
    }
    currentAlert = null
    Qt.callLater(drainAlerts)
  }

  function summon(method) {
    if (!shell || typeof shell[method] !== "function") return "unavailable"
    shell[method](pluginId, "{}")
    return "ok"
  }

  Timer {
    interval: 1000
    running: true
    repeat: true
    onTriggered: {
      var now = Date.now()
      var suspended = now - root.lastTickMs > 2500
      root.lastTickMs = now
      root.clockMs = now
      if (suspended) {
        root.refresh()
      } else if (root.timerExpired && !root.localZeroRefreshRequested) {
        root.localZeroRefreshRequested = true
        root.refresh()
      }
    }
  }

  Timer {
    interval: root.pollSeconds * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    id: previewStopFallback
    interval: 500
    repeat: false
    onTriggered: {
      if (!root.alertWaitingForPreview) return
      previewProcess.completed = true
      previewProcess.signal(9)
      root.previewState = "failed"
      root.setPreviewMessage("sound.previewCleanupTimeout")
      root.alertWaitingForPreview = false
      root.drainAlerts()
    }
  }

  Process {
    id: statusProcess
    property bool launched: false
    property bool completed: false
    property double launchEpoch: 0
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.statusReply = root.parseObject(text) }
    onStarted: launched = true
    onRunningChanged: {
      if (running) launched = false
      else if (!launched && !completed) {
        root.setError("service.helperStartFailed")
        root.finishStatus(-1)
      }
    }
    onExited: function(code) { root.finishStatus(code) }
  }

  Process {
    id: actionProcess
    property bool launched: false
    property bool completed: false
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.actionReply = root.parseObject(text) }
    onStarted: launched = true
    onRunningChanged: {
      if (running) launched = false
      else if (!launched && root.currentAction && !completed) root.finishAction(-1, true)
    }
    onExited: function(code) { root.finishAction(code, false) }
  }

  Process {
    id: showProcess
    property bool launched: false
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.showReply = root.parseObject(text) }
    onStarted: launched = true
    onRunningChanged: {
      if (running) launched = false
      else if (!launched && root.showBusy) {
        root.showBusy = false
        root.showMessage = root.tr("service.helperStartFailed")
      }
    }
    onExited: function(code) {
      root.showBusy = false
      var diagnostic = root.showReply && (root.showReply.message || root.showReply.error)
      var opened = I18n.translate("en", "service.opened")
      var openFailed = I18n.translate("en", "service.openFailed")
      root.showMessage = diagnostic === opened ? root.tr("service.opened")
        : (diagnostic === openFailed ? root.tr("service.openFailed")
        : (diagnostic ? String(diagnostic) : root.tr(code === 0 ? "service.opened" : "service.openFailed")))
    }
  }

  Process {
    id: testProcess
    property bool launched: false
    property bool completed: false
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.testReply = root.parseObject(text) }
    onStarted: launched = true
    onRunningChanged: {
      if (running) launched = false
      else if (!launched && root.testNotificationBusy && !completed)
        root.finishTestNotification(-1, true)
    }
    onExited: function(code) { root.finishTestNotification(code, false) }
  }

  Process {
    id: previewProcess
    property bool launched: false
    property bool completed: false
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.previewReply = root.parseObject(text) }
    onStarted: launched = true
    onRunningChanged: {
      if (running) launched = false
      else if (!launched && command.length > 0 && !completed) {
        completed = true
        root.previewState = "failed"
        root.previewMessage = root.tr("service.helperStartFailed")
        root.ipcPreviewMessage = I18n.translate("en", "service.helperStartFailed")
        if (root.alertWaitingForPreview) {
          previewStopFallback.stop()
          root.alertWaitingForPreview = false
          root.drainAlerts()
        } else root.drainPreviews()
      }
    }
    onExited: function(code) {
      if (completed) return
      completed = true
      if (root.alertWaitingForPreview) {
        root.previewState = "failed"
        if (!root.previewMessage) root.setPreviewMessage("sound.previewCancelled")
      } else {
        root.previewState = Model.sideEffectState(code, root.previewReply)
        var diagnostic = root.previewReply && (root.previewReply.message || root.previewReply.error)
        if (diagnostic) {
          root.previewMessage = String(diagnostic)
          root.ipcPreviewMessage = String(diagnostic)
        } else root.setPreviewMessage(code === 0 ? "sound.previewFinished" : "sound.previewFailed")
      }
      if (root.alertWaitingForPreview) {
        previewStopFallback.stop()
        root.alertWaitingForPreview = false
        root.drainAlerts()
      } else root.drainPreviews()
    }
  }

  Process {
    id: alertProcess
    property bool launched: false
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.alertReply = root.parseObject(text) }
    onStarted: launched = true
    onRunningChanged: {
      if (running) launched = false
      else if (!launched && root.currentAlert) root.finishAlert(-1)
    }
    onExited: function(code) { root.finishAlert(code) }
  }

  IpcHandler {
    target: "patrickfanella.superproductivity"
    function open(): string { return root.summon("summon") }
    function close(): string { return root.summon("hide") }
    function toggle(): string { return root.summon("toggle") }
    function refresh(): string { root.refresh(); return "ok" }
    function show(): string { return JSON.stringify(root.show()) }
    function start(id: string): string { return JSON.stringify(root.startTask(id)) }
    function stop(id: string): string { return JSON.stringify(root.stopTask(id)) }
    function complete(id: string): string { return JSON.stringify(root.completeTask(id)) }
    function completeTask(id: string): string { return JSON.stringify(root.completeListedTask(id)) }
    function extend(id: string, minutes: string): string { return JSON.stringify(root.extendTask(id, minutes)) }
    function add(shorthand: string, startAfter: string): string { return JSON.stringify(root.add(shorthand, startAfter)) }
    function testNotification(): string { return JSON.stringify(root.testNotification()) }
    function previewSound(): string { return JSON.stringify(root.previewSound()) }
    function action(requestId: string): string { return JSON.stringify(root.action(requestId)) }
    function status(): string {
      return JSON.stringify({
        refreshing: root.refreshing,
        error: root.ipcErrorText,
        contextWarning: root.contextWarning,
        alertError: root.ipcAlertError,
        alertVolume: root.alertVolume,
        autoNextWindowMinutes: root.autoNextWindowMinutes,
        task: root.currentTask,
        todayCount: root.todayTasks.length,
        mutationBusy: root.mutationBusy,
        mutationKind: root.mutationKind,
        mutationTaskId: root.mutationTaskId,
        signedRemainingMs: root.signedRemainingMs,
        remainingMs: root.remainingMs,
        overtimeMs: root.overtimeMs,
        timerExpired: root.timerExpired,
        scheduleContextFresh: root.scheduleContextFresh,
        nextScheduled: root.nextScheduledTask ? {
          taskId: root.taskId(root.nextScheduledTask),
          title: root.nextScheduledTitle,
          startMs: root.nextScheduledStartMs,
          startTime: Model.formatStartTime(root.nextScheduledStartMs)
        } : null,
        previewBusy: root.previewBusy,
        previewState: root.previewState,
        previewMessage: root.ipcPreviewMessage,
        testNotificationBusy: root.testNotificationBusy,
        testNotificationState: root.testNotificationState,
        testNotificationMessage: root.ipcTestNotificationMessage
      })
    }
  }
}
