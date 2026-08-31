# Security

This app turns a sentence you say out loud into a Claude Code run with tool
access. That's the point of it, and it's also the whole risk, so here's exactly
what it can do, what stops it, and where the stopping ends.

Everything here was checked against Claude Code 2.1.251. Some of it is this
app's behaviour and some of it is the CLI's, which is a distinction worth
keeping: the second kind can change under you when the CLI updates, and this app
doesn't get a vote.

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
| Ask me on screen | Actions get routed to a dialog showing the actual command before it runs. Not every action; see below. This is the default. | `prompt` |
| Answer only, no actions | Claude Code runs in `dontAsk`, which refuses anything needing permission. The `safe_tools` list still runs. | `ask` |
| Run anything, never ask | Passes `--dangerously-skip-permissions`. Nothing is consulted. | `auto` |

Anything else in that field, a typo or a value written by some later version,
is treated as `prompt`. `config.json` is a file people hand-edit, and a
misspelling there shouldn't be the thing that decides whether you get asked.

Auto mode sits behind a confirmation dialog you have to click through, and while
it's on the pill says so instead of showing the chat name. A setting that
dangerous shouldn't be something you forget you turned on.

## How approval works

In `prompt` mode the app starts its own MCP server (`voiceisland/approver.py`)
and hands Claude Code three flags:

```
--permission-mode default
--mcp-config <written at startup>
--permission-prompt-tool mcp__approver__approval_prompt
```

All three matter, and the first one is the one that's easy to leave out. Without
it, Claude Code takes its permission mode from `permissions.defaultMode` in your
own `~/.claude/settings.json`. On a machine where that says `auto`, the approver
still starts, still connects, still advertises its tool, and is never called
once. Nothing on screen looks any different. The gate is there, it's wired up,
and it's decoration.

That was this app's behaviour until recently, and it's worth being blunt about
because it's the failure mode this whole file is about: a permission system that
looks correct from the outside is worse than no permission system, because you
act like you have one. Reproduced both ways with an approver that denies
everything and a command that creates a file: without the flag the file was
created and the approver was never consulted, with it the approver was consulted,
the denial held, and the file was not created.

Four decisions inside the approver are deliberate.

**It fails closed.** Every path that isn't a click on the allow button returns
deny: the timeout, Escape, a dialog that can't open, an exception. Two minutes of
no answer is a no. A handler that crashes part-way through answers deny too,
rather than just logging and moving on, because Claude Code is blocked on that
request: an unanswered permission question doesn't deny anything, it stops the
turn dead with no dialog and no error.

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

## What reaches the dialog, and what doesn't

This is the CLI's behaviour rather than this app's, and it's the part worth
knowing before you lean on any of the above.

Claude Code decides some tool calls are harmless and runs them without ever
consulting the permission-prompt tool. Observed on 2.1.251, in `prompt` mode,
with the approver connected and denying everything:

| The call | Did it reach the dialog? |
|---|---|
| `Bash: touch <a file>` | Yes, and the denial held: no file. |
| `Bash: echo hello` | No. It just ran. |
| `Read` a file inside the chat's working directory | No. It just ran, and the contents came back. |
| `Read /etc/hosts`, outside that directory | Yes, and the denial held. |

The shape of it: things that change something, and things that reach outside the
directory the chat runs in, come to you. Read-only pokes inside the project
don't. That's a defensible line to draw, and it is not the line "every action
pops a dialog before it runs" describes, which is what this file used to say.

Two consequences. A tool call that runs without a dialog is indistinguishable,
from the app's side, from one you approved: the app never hears about it. And
the directory the chat runs in is doing more of the work than the permission
mode is, which makes it worth a glance before a long session.

## Tools that skip the dialog

`safe_tools` in the config lists tools this app pre-approves with
`--allowedTools`, so they run without asking. The default:

```json
["Glob", "Grep", "TodoWrite"]
```

Those three tell you a file exists, or that a string appears in it. They don't
hand over contents, and one spoken question triggers enough of them that
prompting for each would make the app unusable.

`Read` is deliberately not on that list. The reasoning was that it opens any file
the running user can open, including `~/.ssh/id_rsa`, `.env`, and every password
sitting in a note somewhere. Half of that holds up. A read outside the chat's
working directory does come to the dialog with the path in it. A read inside that
directory doesn't, whatever the file contains, because Claude Code has already
decided it's fine. So leaving `Read` off this list buys you the first case and
nothing for the second, and if the project directory holds a `.env` you care
about, what's protecting it is which directory you pointed the chat at.

If you'd rather have fewer prompts and you know what you're pointing this at, add
it back:

```json
"safe_tools": ["Read", "Glob", "Grep", "TodoWrite"]
```

Set it to `[]` and this app pre-approves nothing. Whether a given search then
reaches you is Claude Code's call, per the table above, not this app's.

In `ask` mode the same list still applies: "Answer only, no actions" means
nothing that needs permission is granted any, but the pre-approved searches do
still run. Set `safe_tools` to `[]` if you want that mode to mean the strictest
thing it can mean here.

## Hiding what you typed

The chat picker names every chat after the first thing you said to it, because
that's the only way to recognise one. It's also a list of your private business,
one click under the notch, on the screen you're about to share.

Settings, **Hide chat names**, replaces those names with a position in the list,
four characters of the session id, and how long ago you last spoke to it. The
project name is left out as well: a directory gets named after a person, a case,
or a diagnosis about as often as after a repository.

What it doesn't hide is the turn happening right now. The pill shows what it
heard and what came back, and the activity list under it shows the tool calls of
the running turn. The setting is for the record of everything you've ever said
to this thing, not for the sentence you just said out loud in the room.

## What it doesn't protect against

- The CLI's own idea of what's harmless, above. It's a moving target across
  versions, and this app can't tell an approved call from one that never asked.
- A malicious MCP server you configured yourself. This app hands approval
  decisions to you, not to a policy engine, and a tool call that looks reasonable
  in a dialog is approved if you approve it.
- Someone with physical access to your unlocked Mac. They can talk to it.
- Anything you say in a directory where you didn't want that to happen. It runs
  in the working directory of the chat you picked, which is worth a glance before
  a long session.
- A `claude` that spells the modes differently. `--permission-mode default` is
  accepted by 2.1.251 but isn't in the list its own `--help` prints (`acceptEdits`,
  `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`). If a version drops it,
  the run fails with a usage error and the pill says "Claude did not reply" with
  the error attached. Nothing runs, which is the right direction to fail, but it's
  worth knowing what that message means.

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
