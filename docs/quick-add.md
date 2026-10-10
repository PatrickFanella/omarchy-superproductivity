# Quick Add

Quick Add creates a Super Productivity task without opening the full application. The modal uses the same parser, task queue, and Add & switch setting as the inline field in the plugin panel.

## Open the modal

Middle-click the Super Productivity bar widget, or run:

```bash
omarchy-shell patrickfanella.superproductivity quickAdd
```

The modal appears in the center of the screen that hosts the selected bar widget. Its task field receives focus immediately. The header sits above a full-width input, with the syntax hint, Add & switch checkbox, and submit button below.

The modal requests 840 theme-scaled units of width, twice the full panel's 420, and a 68-unit input height. The popup fits its dimensions to the available screen. These sizes follow the active Omarchy theme's scale.

## Add a task

Type a title, optionally followed by shorthand:

```text
Write report 30m +Work #focus @tomorrow
```

Press Enter or select **Add**. Enable **Add & switch** to create the task and then attempt to start tracking it. This setting persists and also applies to the inline field. It defaults to off.

The [README shorthand reference](../README.md#quick-add-controls) covers estimates, spent time, projects, existing tags, and schedules.

A successful add clears the field and closes the modal. Failed, partial, conflict, and unknown results stay visible. If a partial result includes a created task ID, the field clears because the task already exists. Check the result and Today before entering it again. The plugin does not retry a mutation automatically.

Escape or an outside click dismisses the modal without submitting the draft. Reopening preserves that draft while the plugin remains loaded. Drafts are not saved across shell restarts. Dismissing a pending request does not cancel it.

Left-click opens the full panel, which keeps its inline Quick Add field above Today. Use that panel for task controls, status refresh, and settings.

## Add an Omarchy hotkey

Check your current bindings first:

```bash
hyprctl binds
```

If Super + Shift + U is unused, add this line to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + SHIFT + U", "Super Productivity Quick Add", "omarchy-shell patrickfanella.superproductivity quickAdd")
```

If the combination already has a binding, choose another unused key or deliberately remove the old binding with `hl.unbind` before replacing it. Installing the plugin does not change keybindings automatically.

Apply the configuration and check for errors:

```bash
hyprctl reload
hyprctl configerrors
```

Remove the binding and run those commands again to uninstall the hotkey.

## Troubleshooting

If IPC reports `Function not found`, confirm that the installed plugin includes `quickAdd()` in `Service.qml` and that `TaskPopup.qml` is present beside `Panel.qml`. A checkout update alone does not update a separate installed copy. Restart the shell with `omarchy restart shell` after installing the updated plugin if its service has not reloaded.

If the hotkey does nothing, test the IPC command directly and check `hyprctl binds` for the registered combination. Confirm that the plugin is enabled and has a widget in the bar layout.

If the modal stays under the bar, check that the installed `Panel.qml` uses `TaskPopup` with `centerOnScreen: root.quickAddOnly`. The standard Omarchy keyboard popup centers along the bar, not on both screen axes.

For contributor checks and safe synthetic fixtures, see [Contributing](../CONTRIBUTING.md#test-quick-add-ui-changes).
