# Security

This app turns a sentence you say out loud into a Claude Code run with tool
access. That is the point of it, and it is also the whole risk, so here is
exactly what it can do and what stops it.

## What it can reach

- Your microphone, while you hold the button.
- The `claude` command, which runs with your permissions, in the working
  directory of the chat you picked.
- Whatever that Claude Code session can reach: files, shell commands, the
  network, and any MCP server you have configured.

There is no API key, no account, and no server belonging to this project.
Nothing is uploaded to me, and there is nothing to upload it to.

## The three modes

Settings, **What Claude may do**:

| Mode | What happens | Stored as |
|---|---|---|
| Ask me on screen | Every action pops a dialog showing the actual command before it runs. This is the default. | `prompt` |
| Answer only, no actions | No approval route is offered at all, so anything needing one is refused. | `ask` |
| Run anything, never ask | Passes `--dangerously-skip-permissions`. No dialogs. | `auto` |

Auto mode is behind a confirmation dialog you have to click through, and while
it is on the pill says so instead of showing the chat name. A setting that
dangerous should not be something you forget you turned on.

## How approval works

In `prompt` mode the app starts its own MCP server (`voiceisland/approver.py`)
and hands Claude Code `--permission-prompt-tool mcp__approver__approval_prompt`.
Claude then has to ask that server before using a tool, and the server asks you.

Four decisions in there are deliberate:

**It fails closed.** Every path that is not a click on the allow button returns
deny: the timeout, Escape, a dialog that cannot open, an exception, a malformed
message. Two minutes of no answer is a no.

**The command is never built into the script.** The dialog text goes to
AppleScript as an argument, not as part of the script source. Pasting a shell
command into a script you are about to execute would mean a quote in that
command could change what the script does, which is a strange way to build the
thing whose job is asking whether that command should run at all.

**Truncation is visible.** If a command is too long for the dialog, the dialog
says how many characters are hidden. Approving a command whose tail you cannot
see is not approval.

**It has no dependencies.** The JSON-RPC is hand-written so the approver pulls
in no third-party code. Roughly a hundred and fifty lines, readable in one
sitting.

## Tools that skip the dialog

`safe_tools` in the config lists tools that run without asking. The default is:

```json
["Read", "Glob", "Grep", "TodoWrite"]
```

These are read-only, and prompting for each one makes the app unusable: a single
question can read a dozen files. That trade is real, and worth being clear
about. `Read` can open any file the running user can open, including private
keys and `.env` files, and it is on this list.

If that is not the trade you want, remove it:

```json
"safe_tools": ["Glob", "Grep", "TodoWrite"]
```

Set it to `[]` and everything asks. Nothing else in the app changes.

## What is not protected against

- A malicious Claude Code MCP server you configured yourself. This app hands
  approval decisions to you, not to a policy engine, and a tool call that looks
  reasonable in a dialog is approved if you approve it.
- Someone with physical access to your unlocked Mac. They can talk to it.
- Anything you say in a directory where you did not want that to happen. The app
  runs in the working directory of the chat you picked, which is worth a glance
  before a long session.

## What it deliberately avoids

- No transcripts in the log unless you turn on `log_transcripts`.
- No settings, logs or generated config inside the repository, so a clone or a
  screen share never shows your data.
- System binaries are called by absolute path (`/usr/bin/osascript`,
  `/usr/bin/say`, `/usr/bin/afplay`, `/bin/launchctl`), so a directory earlier in
  PATH cannot answer for them.
- The approver subprocess is given a minimal environment rather than an
  inherited one.
- The single-instance check takes a lock rather than running `pkill` against a
  process name, which on someone else's machine could match anything.

## Reporting something

Open an issue at
https://github.com/clickspider/claude-voice-island/issues. If it is a real
vulnerability rather than a bug, say so in the title and leave out the details,
and I will get you somewhere private to send them.
