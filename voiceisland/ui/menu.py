"""The chevron menu: pick a chat, change a setting, quit.

Built fresh every time it opens so it always shows the real current state,
including settings another copy of the app or a hand edit may have changed. The
actions live on the view, because that is what AppKit sends a selector to.
"""

from __future__ import annotations

from AppKit import NSMenu, NSMenuItem

from voiceisland import config, launchagent, speech

_CHECKED = 1
_MAX_TITLE = 60

_PTT_CHOICES = [
    ("Mouse only (hold the pill)", "off"),
    ("⌥ Option", "option"),
    ("⌃ Control", "control"),
    ("⌘ Command", "command"),
]

_PERMISSION_CHOICES = [
    ("Ask me on screen", "prompt"),
    ("Run anything, never ask", "auto"),
    ("Answer only, no actions", "ask"),
]

_ENGINE_CHOICES = [
    ("Microsoft neural voices", "edge"),
    ("macOS voice (offline)", "say"),
]


def build(view) -> NSMenu:
    """The whole menu for `view`."""
    menu = NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)

    private = bool(config.load().get("private_titles", False))

    _add(menu, view, "New chat", "newChat:", key="n")
    menu.addItem_(NSMenuItem.separatorItem())
    for session in view.sessions:
        item = _add(menu, view, _shorten(session.label(private)), "selectSession:",
                    value=session.id)
        if view.current and session.id == view.current.id:
            item.setState_(_CHECKED)
    menu.addItem_(NSMenuItem.separatorItem())
    _add_settings(menu, view)
    _add(menu, view, "Refresh chats", "refresh:")
    _add(menu, view, "Quit", "quitApp:", key="q")
    return menu


def _add_settings(menu: NSMenu, view) -> None:
    settings = config.load()
    parent = menu.addItemWithTitle_action_keyEquivalent_("Settings", "", "")
    submenu = NSMenu.alloc().init()
    submenu.setAutoenablesItems_(False)

    handsfree = _add(submenu, view, "Hands-free (keep listening)", "toggleHandsFree:")
    if view.handsfree:
        handsfree.setState_(_CHECKED)
    submenu.addItem_(NSMenuItem.separatorItem())

    _add_choices(submenu, view, "Push-to-talk key", "setPTT:", _PTT_CHOICES, settings["ptt"])
    _add_choices(submenu, view, "Voice", "setVoice:",
                 [(label, voice_id) for label, voice_id, _macos in speech.VOICE_CHOICES],
                 settings["voice"])
    _add_choices(submenu, view, "Speech engine", "setEngine:",
                 _ENGINE_CHOICES, settings["tts_engine"])
    _add_choices(submenu, view, "What Claude may do", "setPermissions:",
                 _PERMISSION_CHOICES, settings["permissions"])

    narrate = _add(submenu, view, "Say each action out loud", "toggleNarrate:")
    if view.narrate:
        narrate.setState_(_CHECKED)

    private = _add(submenu, view, "Hide chat names (screen sharing)", "togglePrivateTitles:")
    if settings.get("private_titles", False):
        private.setState_(_CHECKED)

    if not view.notch_mode:
        _add(submenu, view, "Reset pill position", "resetPosition:")

    login = _add(submenu, view, "Start at login", "toggleLogin:")
    if launchagent.is_enabled():
        login.setState_(_CHECKED)

    parent.setSubmenu_(submenu)
    menu.addItem_(NSMenuItem.separatorItem())


def _add_choices(menu: NSMenu, view, title: str, action: str, choices, current) -> None:
    """A submenu of mutually exclusive options, with the active one ticked."""
    parent = menu.addItemWithTitle_action_keyEquivalent_(title, "", "")
    submenu = NSMenu.alloc().init()
    submenu.setAutoenablesItems_(False)
    for label, value in choices:
        item = _add(submenu, view, label, action, value=value)
        if value == current:
            item.setState_(_CHECKED)
    parent.setSubmenu_(submenu)


def _add(menu: NSMenu, view, title: str, action: str, key: str = "", value=None):
    item = menu.addItemWithTitle_action_keyEquivalent_(title, action, key)
    item.setTarget_(view)
    if value is not None:
        item.setRepresentedObject_(value)
    return item


def _shorten(title: str) -> str:
    return title if len(title) <= _MAX_TITLE else title[: _MAX_TITLE - 1] + "…"
