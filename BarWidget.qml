import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "patrickfanella.superproductivity"

  readonly property var engine: bar && bar.shell && typeof bar.shell.serviceFor === "function"
    ? bar.shell.serviceFor(moduleName)
    : null
  readonly property var task: engine ? engine.currentTask : null
  readonly property var nextScheduledTask: engine ? engine.nextScheduledTask : null
  readonly property real nextScheduledStartMs: engine && isFinite(Number(engine.nextScheduledStartMs))
    ? Number(engine.nextScheduledStartMs) : 0
  readonly property string nextScheduledTitle: String(engine && engine.nextScheduledTitle
    || nextScheduledTask && (nextScheduledTask.title || nextScheduledTask.name)
    || "Untitled task").replace(/\s+/g, " ").trim()
  readonly property bool hasNextScheduled: !task && !!nextScheduledTask && nextScheduledStartMs > 0
  readonly property string nextScheduledTime: hasNextScheduled
    ? Model.formatStartTime(nextScheduledStartMs) : ""
  readonly property real remainingMs: engine ? engine.remainingMs : 0
  readonly property real overtimeMs: engine ? engine.overtimeMs : 0
  readonly property real estimateMs: engine && isFinite(Number(engine.estimateMs))
    ? Number(engine.estimateMs)
    : Number(task && task.timeEstimate || 0)
  readonly property bool hasEstimate: !!task && estimateMs > 0
  readonly property string errorText: engine ? engine.errorText : "Super Productivity service is not loaded"
  readonly property bool timerExpired: engine ? engine.timerExpired === true && hasEstimate : false
  readonly property int maxWidth: Math.max(120, Math.min(520, Number(setting("maxTitleWidth", 300))))
  readonly property bool showIdle: setting("showIdle", true) !== false
  readonly property string labelText: timerExpired
    ? "⏰  " + (task ? Model.displayTitle(task, 52) + "  " : "") + Model.formatOvertime(overtimeMs)
    : (errorText !== ""
      ? "󰅙  SP"
      : (task ? (hasEstimate
        ? Model.barLabel(task, remainingMs)
        : "󰄬  " + Model.displayTitle(task, 52) + "  No estimate")
      : (hasNextScheduled
        ? "󰥔  Next " + nextScheduledTime + " · " + nextScheduledTitle
        : "󰄬  Focus clear")))
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    target.bar = root.bar
    target.settings = root.settings
    target.anchorItem = button
    target.hostWidget = root
    target.engine = root.engine
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  visible: !!task || hasNextScheduled || showIdle || errorText !== ""

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()
  onEngineChanged: injectPanel()

  TextMetrics {
    id: labelMetrics
    font.family: root.bar ? root.bar.fontFamily : Style.font.family
    font.pixelSize: Style.font.body
    text: root.labelText
  }

  Loader {
    id: panelLoader
    active: true
    visible: false
    source: Qt.resolvedUrl("Panel.qml")
    onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    fixedWidth: Math.min(root.maxWidth, labelMetrics.width + Style.space(20))
    active: root.timerExpired || root.errorText !== ""
    tooltipText: root.timerExpired
      ? "Timer expired" + (root.task ? ": " + Model.displayTitle(root.task, 100) : "") + ". Overtime " + Model.formatOvertime(root.overtimeMs)
      : (root.errorText !== ""
        ? root.errorText
        : (root.task ? Model.displayTitle(root.task, 100) + " · " + (root.hasEstimate ? Model.formatRemaining(root.remainingMs) + " left" : "No estimate")
                     : (root.hasNextScheduled
                       ? "Next at " + root.nextScheduledTime + " local time: " + root.nextScheduledTitle
                       : "No current task")))
    Accessible.name: root.timerExpired
      ? "Super Productivity: timer expired" + (root.task ? " for " + Model.displayTitle(root.task, 100) : "") + ", overtime " + Model.formatOvertime(root.overtimeMs)
      : (root.errorText !== ""
        ? "Super Productivity unavailable: " + root.errorText
        : (root.task ? "Super Productivity: " + Model.displayTitle(root.task, 100) + ", " + (root.hasEstimate ? Model.formatRemaining(root.remainingMs) + " left" : "No estimate")
                     : (root.hasNextScheduled
                       ? "Super Productivity: next at " + root.nextScheduledTime + " local time, " + root.nextScheduledTitle
                       : "Super Productivity: no current task")))
    Accessible.role: Accessible.Button
    Accessible.onPressAction: root.toggle()

    onPressed: function(code) {
      if (code === Qt.MiddleButton) { if (root.engine) root.engine.refresh() }
      else if (code === Qt.RightButton) { if (root.engine) root.engine.show() }
      else root.toggle()
    }

    Text {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(9)
      anchors.rightMargin: Style.space(9)
      text: root.labelText
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: root.timerExpired || root.errorText !== "" ? (root.bar ? root.bar.urgent : Color.urgent)
                                                        : (root.bar ? root.bar.barForeground : Color.foreground)
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
      renderType: Text.NativeRendering
    }
  }
}
