# Security

This app turns a sentence you say out loud into a Claude Code run with tool
access. That's the point of it, and it's also the whole risk, so here's exactly
what it can do and what stops it.

## What it can reach

- Your microphone, while you hold the button.
- The `claude` command, which runs with your permissions, in the working
  directory of the chat you picked.
- Whatever that Claude Code session can reach: files, shell commands, the
  network, and any MCP server you've configured.

There's no API key, no account, and no server belonging to this project. Nothing
gets uploaded to me, and there's nothing to upload it to.

## The three modes

Settings, **What Claude may do**:

| Mode | What happens | Stored as |
|---|---|---|
| Ask me on screen | Every action pops a dialog showing the actual command before it runs. This is the default. | `prompt` |
| Answer only, no actions | No approval route gets offered at all, so anything needing one is refused. | `ask` |
| Run anything, never ask | Passes `--dangerously-skip-permissions`. No dialogs. | `auto` |

Auto mode sits behind a confirmation dialog you have to click through, and while
it's on the pill says so instead of showing the chat name. A setting that
dangerous shouldn't be something you forget you turned on.

## How approval works

In `prompt` mode the app starts its own MCP server (`voiceisland/approver.py`)
and hands Claude Code `--permission-prompt-tool mcp__approver__approval_prompt`.
Claude then has to ask that server before using a tool, and the server asks you.

Four decisions in there are deliberate.

**It fails closed.** Every path that isn't a click on the allow button returns
deny: the timeout, Escape, a dialog that can't open, an exception, a malformed
message. Two minutes of no answer is a no.

**The command never gets built into the script.** The dialog text goes to
AppleScript as an argument, not as part of the script source. Pasting a shell
command into a script you're about to execute would mean a quote in that command
could change what the script does, which is a strange way to build the thing
whose job is asking whether that command should run at all.

**Truncation is visible.** If a command is too long for the dialog, the dialog
says how many characters are hidden. Approving a command whose tail you can't see
isn't approval.

**It has no dependencies.** The JSON-RPC is hand-written, so the approver pulls
in no third-party code at all.

## Tools that skip the dialog

`safe_tools` in the config lists tools that run without asking. The default:

```json
["Glob", "Grep", "TodoWrite"]
```

Those three tell you a file exists, or that a string appears in it. They don't
hand over contents, and one spoken question triggers enough of them that
prompting for each would make the app unusable.

`Read` is deliberately not on that list, even though it's read-only in the sense
that it changes nothing. It opens any file the running user can open, which
includes `~/.ssh/id_rsa`, `.env`, and every password sitting in a note somewhere.
A file being read is worth one dialog with the path in it.

If you'd rather have fewer prompts and you know what you're pointing this at, add
it back:

```json
"safe_tools": ["Read", "Glob", "Grep", "TodoWrite"]
```

Set it to `[]` and everything asks, including searches. Nothing else in the app
changes either way.

## What it doesn't protect against

- A malicious MCP server you configured yourself. This app hands approval
  decisions to you, not to a policy engine, and a tool call that looks reasonable
  in a dialog is approved if you approve it.
- Someone with physical access to your unlocked Mac. They can talk to it.
- Anything you say in a directory where you didn't want that to happen. It runs
  in the working directory of the chat you picked, which is worth a glance before
  a long session.

## What it deliberately avoids

- No transcripts in the log unless you turn on `log_transcripts`.
- No settings, logs or generated config inside the repository, so a clone or a
  screen share never shows your data.
- System binaries get called by absolute path (`/usr/bin/osascript`,
  `/usr/bin/say`, `/usr/bin/afplay`, `/bin/launchctl`), so a directory earlier in
  PATH can't answer for them.
- The approver subprocess gets a minimal environment rather than an inherited
  one.
- The single-instance check takes a lock instead of running `pkill` against a
  process name, which on someone else's machine could match anything.

## Reporting something

Open an issue at
https://github.com/clickspider/claude-voice-island/issues. If it's a real
vulnerability rather than a bug, say so in the title and leave out the details,
and I'll get you somewhere private to send them.
