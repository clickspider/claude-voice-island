"""Starting the app: one window, one view, one event loop.

The window is an NSPanel rather than an NSWindow because a panel can be shown
without ever taking focus. Clicking the pill must not pull you out of whatever
you were typing in, which is the whole point of talking to it instead.

It sits above the menu bar, joins every Space, and ignores mouse events until the
pointer is actually near it.
"""

from __future__ import annotations

import logging
import sys

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationDidChangeScreenParametersNotification,
    NSBackingStoreBuffered,
    NSColor,
    NSMainMenuWindowLevel,
    NSPanel,
    NSScreen,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSMakeRect, NSNotificationCenter
from PyObjCTools import AppHelper

from voiceisland import claude, config, dialogs, singleton
from voiceisland.ui import notch
from voiceisland.ui.pill import PillView

_log = logging.getLogger("voiceisland.app")

# Three levels above the menu bar, so the pill stays visible over a full-screen
# window and over the menu bar itself.
_WINDOW_LEVEL = NSMainMenuWindowLevel + 3


def build_panel(rect) -> NSPanel:
    style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, style, NSBackingStoreBuffered, False
    )
    panel.setLevel_(_WINDOW_LEVEL)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setHasShadow_(True)
    panel.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
    )
    panel.setMovableByWindowBackground_(False)
    panel.setIgnoresMouseEvents_(True)
    return panel


def _closed_rect(screen):
    """The starting frame: exactly the notch, so the app opens invisible."""
    frame = screen.frame()
    height = notch.notch_height(screen)
    width = notch.measure_notch_width(screen) if height > 0 else notch.DEFAULT_NOTCH_WIDTH
    height = height if height > 0 else 24.0
    top = frame.origin.y + frame.size.height
    return NSMakeRect(
        frame.origin.x + (frame.size.width - width) / 2, top - height, width, height
    )


def _check_claude_installed() -> bool:
    try:
        claude.resolve_binary()
        return True
    except claude.ClaudeNotFoundError:
        dialogs.ask_yes_no(
            title="Claude Voice Island",
            body=(
                "The `claude` command was not found.\n\n"
                "Install Claude Code and sign in, then start this again."
            ),
            allow_label="OK",
            deny_label="Quit",
            timeout_s=30,
        )
        return False


def main() -> int:
    config.setup_logging()
    try:
        lock = singleton.acquire()
    except singleton.AlreadyRunningError:
        _log.info("another instance is already running, exiting")
        print("Claude Voice Island is already running.", file=sys.stderr)
        return 1

    if not _check_claude_installed():
        return 1
    claude.write_mcp_config()

    app = NSApplication.sharedApplication()
    # Accessory means no Dock icon and no menu bar of its own: it is a thing on
    # the screen, not an app you switch to.
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    screen = NSScreen.mainScreen()
    if screen is None:
        _log.error("no screen available")
        return 1

    rect = _closed_rect(screen)
    panel = build_panel(rect)
    view = PillView.alloc().initWithFrame_(NSMakeRect(0, 0, rect.size.width, rect.size.height))
    view.load_settings()
    panel.setContentView_(view)
    view.attach(panel)
    view.start_timers()
    NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        view, "screensChanged:", NSApplicationDidChangeScreenParametersNotification, None
    )
    panel.orderFrontRegardless()

    _log.info("started with %d chats available", len(view.sessions))
    try:
        AppHelper.runEventLoop()
    finally:
        lock.close()
    return 0
