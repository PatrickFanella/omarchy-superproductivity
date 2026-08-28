import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model
import "I18n.js" as I18n

BarWidget {
  id: root
  moduleName: "patrickfanella.superproductivity"

  readonly property var engine: bar && bar.shell && typeof bar.shell.serviceFor === "function"
    ? bar.shell.serviceFor(moduleName)
    : null
  readonly property var task: engine ? engine.currentTask : null
  readonly property string localeName: engine && engine.localeName
    ? engine.localeName : I18n.resolveLocale(Qt.locale().name)
  readonly property var formattingLocale: Qt.locale()
  readonly property var nextScheduledTask: engine ? engine.nextScheduledTask : null
  readonly property real nextScheduledStartMs: engine && isFinite(Number(engine.nextScheduledStartMs))
    ? Number(engine.nextScheduledStartMs) : 0
  readonly property string nextScheduledTitle: Model.displayTitle({
    title: engine && engine.nextScheduledTitle
      || nextScheduledTask && (nextScheduledTask.title || nextScheduledTask.name)
  }, 1000, tr("common.untitledTask"))
  readonly property bool hasNextScheduled: !task && !!nextScheduledTask && nextScheduledStartMs > 0
  readonly property string nextScheduledTime: hasNextScheduled
    ? formattingLocale.toString(
        new Date(nextScheduledStartMs),
        formattingLocale.timeFormat(Locale.ShortFormat))
    : ""
  readonly property real remainingMs: engine ? engine.remainingMs : 0
  readonly property real overtimeMs: engine ? engine.overtimeMs : 0
  readonly property real estimateMs: engine && isFinite(Number(engine.estimateMs))
    ? Number(engine.estimateMs)
    : Number(task && task.timeEstimate || 0)
  readonly property bool hasEstimate: !!task && estimateMs > 0
  readonly property string errorText: engine ? engine.errorText : tr("service.notLoaded")
  readonly property bool timerExpired: engine ? engine.timerExpired === true && hasEstimate : false
  readonly property int maxWidth: Math.max(120, Math.min(520, Number(setting("maxTitleWidth", 300))))
  readonly property bool showIdle: setting("showIdle", true) !== false
  readonly property string labelText: timerExpired
    ? "⏰  " + (task ? Model.displayTitle(task, 52, tr("common.untitledTask")) + "  " : "") + Model.formatOvertime(overtimeMs)
    : (errorText !== ""
      ? "󰅙  SP"
      : (task ? (hasEstimate
        ? Model.barLabel(task, remainingMs, tr("common.untitledTask"))
        : "󰄬  " + tr("bar.taskNoEstimate", { title: Model.displayTitle(task, 52, tr("common.untitledTask")) }))
      : (hasNextScheduled
        ? "󰥔  " + tr("bar.next", { time: nextScheduledTime, title: nextScheduledTitle })
        : "󰄬  " + tr("bar.focusClear"))))
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function tr(key, args) { return I18n.translate(localeName, key, args || {}) }

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
      ? (root.task ? root.tr("bar.timerExpired", { title: Model.displayTitle(root.task, 100, root.tr("common.untitledTask")), overtime: Model.formatOvertime(root.overtimeMs) }) : root.tr("bar.timerExpiredNoTask", { overtime: Model.formatOvertime(root.overtimeMs) }))
      : (root.errorText !== ""
        ? root.errorText
        : (root.task ? (root.hasEstimate ? root.tr("bar.taskLeft", { title: Model.displayTitle(root.task, 100, root.tr("common.untitledTask")), remaining: Model.formatRemaining(root.remainingMs) }) : root.tr("bar.taskNoEstimate", { title: Model.displayTitle(root.task, 100, root.tr("common.untitledTask")) }))
                     : (root.hasNextScheduled
                       ? root.tr("bar.nextTooltip", { time: root.nextScheduledTime, title: root.nextScheduledTitle })
                       : root.tr("bar.noCurrentTask"))))
    Accessible.name: root.timerExpired
      ? (root.task ? root.tr("bar.a11yExpired", { title: Model.displayTitle(root.task, 100, root.tr("common.untitledTask")), overtime: Model.formatOvertime(root.overtimeMs) }) : root.tr("bar.a11yExpiredNoTask", { overtime: Model.formatOvertime(root.overtimeMs) }))
      : (root.errorText !== ""
        ? root.tr("bar.a11yUnavailable", { error: root.errorText })
        : (root.task ? (root.hasEstimate ? root.tr("bar.a11yTaskLeft", { title: Model.displayTitle(root.task, 100, root.tr("common.untitledTask")), remaining: Model.formatRemaining(root.remainingMs) }) : root.tr("bar.a11yTaskNoEstimate", { title: Model.displayTitle(root.task, 100, root.tr("common.untitledTask")) }))
                     : (root.hasNextScheduled
                       ? root.tr("bar.a11yNext", { time: root.nextScheduledTime, title: root.nextScheduledTitle })
                       : root.tr("bar.a11yNoCurrentTask"))))
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
