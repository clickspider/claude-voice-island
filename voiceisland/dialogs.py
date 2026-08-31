"""Native macOS yes/no dialogs.

The text shown in a dialog can contain anything Claude decided to do: a shell
command, a file path, a JSON blob. So it is passed to AppleScript as an argument
rather than pasted into the script source. Building a script by string
concatenation would mean a quote or a newline in a command could change what the
script does, which is exactly the mistake this dialog exists to prevent.

Every path that fails, times out, or cannot show a dialog returns False. A
question nobody answered is a no.
"""

from __future__ import annotations

import logging
import subprocess

_log = logging.getLogger("voiceisland.dialogs")

# Absolute path on purpose. This is the component that asks permission, so it
# should not be possible to answer for it by putting something called osascript
# earlier in PATH.
OSASCRIPT = "/usr/bin/osascript"

# Runs the dialog with all values taken from argv, so nothing is interpolated
# into the script text.
#
# The dialog's answer is bound to a name rather than read from AppleScript's
# implicit `result`. Inside an `on run` handler `result` is not reliably set, and
# reading it raises "The variable result is not defined", which this code treated
# as a failed dialog and therefore a no. Every click of Allow was a deny.
_SCRIPT = """
on run argv
    set theTitle to item 1 of argv
    set theBody to item 2 of argv
    set denyLabel to item 3 of argv
    set allowLabel to item 4 of argv
    set limit to (item 5 of argv) as integer
    set answer to display dialog theBody with title theTitle ¬
        buttons {denyLabel, allowLabel} default button denyLabel ¬
        with icon caution giving up after limit
    if gave up of answer then return "__timeout__"
    return button returned of answer
end run
"""


def ask_yes_no(
    title: str,
    body: str,
    allow_label: str = "Allow",
    deny_label: str = "Deny",
    timeout_s: int = 120,
) -> bool:
    """Show a two-button dialog. True only when the allow button was pressed.

    The deny button is the default, so pressing Return or Escape denies, and
    walking away denies once `timeout_s` passes.
    """
    args = [
        OSASCRIPT,
        "-e",
        _SCRIPT,
        title,
        body,
        deny_label,
        allow_label,
        str(int(timeout_s)),
    ]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_s + 10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        _log.warning("dialog failed to run, denying", exc_info=True)
        return False
    if result.returncode != 0:
        # A non-zero exit is the user pressing Escape, or AppleScript refusing.
        return False
    return (result.stdout or "").strip() == allow_label
