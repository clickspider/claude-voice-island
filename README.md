# Claude Voice Island

Hold the notch. Talk. Let go. Claude answers out loud.

It is a push-to-talk button that lives inside the black cutout at the top of a
MacBook screen. Press and hold it, say what you want, release. Your speech is
transcribed on your own machine, sent into a real Claude Code chat with all of
its history, and the answer comes back in a voice while you keep doing whatever
you were doing.

```
  ╭──────────────────────────────╮
  │ ●  refactor the parser     ⌄ │   the pill, open
  ╰──────────────────────────────╯

     grey idle · red listening · amber working · green speaking
```

When nothing is happening the window shrinks to exactly the size of the physical
notch and fills it with black, so it disappears into the hardware. Move your
pointer up there and it grows back out.

No API key. It drives the `claude` command you already have, so it runs on your
Claude Code subscription and costs nothing extra.

## Why I built it

I kept losing my place. Half the questions I ask Claude while I am working are
one sentence long, and typing a one sentence question means leaving the file I
am reading, finding the terminal, typing, waiting, and coming back with the
thread of what I was doing already gone.

Voice fixes that, but only if it talks to the session that already knows what I
am working on. A voice assistant that starts a fresh conversation every time is
useless for this. So it resumes the actual chat, in the actual project
directory, with the actual history, which is why the picker lists your real
chats by the first thing you typed in them.

The notch was the other half. There is a strip of dead black glass at the top of
every modern MacBook, and everything I tried that used it was a floating panel
sitting near it rather than in it. Getting a window to merge with the notch
cleanly turned out to be the most interesting part of the whole project.

## What people use it for

- Asking about the code on screen without leaving the code on screen.
- Thinking out loud. Explaining a problem to something that answers is faster
  than writing the problem down.
- Hands busy. Sketching, wiring something up, holding coffee, walking around.
- Long agent runs, with **Say each action out loud** turned on, so you hear when
  it needs you instead of watching a terminal.
- Typing less on days when typing hurts.

## Install

You need macOS 13 or newer, Python 3.10 or newer, and
[Claude Code](https://claude.com/claude-code) installed and signed in.

```bash
git clone https://github.com/clickspider/claude-voice-island.git
cd claude-voice-island
./scripts/setup.sh
```

Then start it:

```bash
./start.command
```

Or build a real app you can double-click and add to your login items:

```bash
./scripts/make_app.sh          # creates ~/Applications/Claude Voice Island.app
```

The first time you hold to talk, macOS asks for microphone access. Allow it, and
hold again. If you miss the prompt, it is in System Settings, Privacy and
Security, Microphone.

## Using it

| What you do | What happens |
|---|---|
| Hold the pill, talk, release | The turn runs |
| Tap while it is speaking | It stops mid-sentence |
| Hold while it is speaking | It stops and listens to you instead |
| Click the ⌄ | Pick a chat, start a new one, change settings |
| Hover while it works | The activity list opens under the pill |

Prefer a key to a click? Settings, **Push-to-talk key** binds Option, Control or
Command as a hold-to-talk key that works from any app. macOS asks for
Accessibility permission the first time, because watching a key outside your own
app is exactly the kind of thing it should ask about.

**Hands-free** keeps the microphone open, sends when you stop talking, and
reopens it after Claude finishes, so you can hold a conversation without
touching anything.

## How it works

```
  hold                release
    │                     │
    ▼                     ▼
 microphone ──► faster-whisper ──► claude -p --resume <chat>
                 (on your Mac)              │
                                            │ stream of events
                                            ▼
                                     the activity list
                                            │
                                            ▼
                                   text to speech ──► out loud
```

Four things are worth knowing.

**It resumes real chats.** Claude Code stores every session as a JSONL file
under `~/.claude/projects/`. The picker reads the head of each one for the
working directory and the first thing you typed, which is how the menu can list
"fix the login bug" instead of a UUID. Picking one and speaking runs
`claude -p --resume <id>` inside that project directory.

**Nothing runs without you saying yes.** By default the app starts a small MCP
server of its own and hands Claude Code
`--permission-prompt-tool mcp__approver__approval_prompt`, so every action it
wants to take becomes a dialog on your screen showing the actual command before
anything happens. That server is about a hundred lines and has no dependencies,
which is on purpose: the component whose whole job is saying no should be small
enough to read in one sitting. See [SECURITY.md](SECURITY.md).

**You can watch it work.** The run is read as a stream, so each tool call
becomes a row in the activity list as it happens: `Run: pytest -q`,
`Edit parser.py`, `Browsing the web`. Turn on **Say each action out loud** and
you hear those instead.

**It gets out of the way.** While closed, the window ignores mouse events
entirely, so the app underneath behaves as if it were not there. It only takes
clicks once your pointer is actually near it, or while a turn is running.

## What leaves your Mac

Being precise about this, because "local" is a word people stretch.

| Step | Where it happens |
|---|---|
| Speech to text | On your Mac. The recording is never uploaded. The model file is downloaded once, on first use. |
| The question and the answer | Claude Code, on your subscription, the same as typing it. |
| Text to speech, `edge` | Sent to Microsoft's speech service, which is how those voices work. |
| Text to speech, `say` | On your Mac. Nothing leaves. |

The default is the Microsoft voice because it sounds far better. If you would
rather nothing leave the machine at all, Settings, **Speech engine**, macOS
voice.

What you say is not written to the log unless you turn on `log_transcripts`. The
log records lengths and timings instead. Settings live in
`~/Library/Application Support/ClaudeVoiceIsland/`, logs in
`~/Library/Logs/ClaudeVoiceIsland/`, and neither is inside this repository, so a
clone never collects anything personal.

## Settings

Everything in the ⌄ menu writes to
`~/Library/Application Support/ClaudeVoiceIsland/config.json`. A few things are
only in the file:

| Key | Default | What it does |
|---|---|---|
| `whisper_model` | `base.en` | `small.en` is more accurate and slower |
| `safe_tools` | `Read, Glob, Grep, TodoWrite` | Tools allowed to run without a dialog |
| `log_transcripts` | `false` | Write what you said and what Claude replied to the log |

## Limits

- macOS only, and the notch behaviour needs a Mac that has one. On any other
  screen it becomes a small pill you can drag wherever you want.
- Replies are read in full, so it is built for short spoken turns rather than
  long explanations. Claude is asked to answer in two sentences.
- Every turn starts a `claude` process, so there is a few seconds of thinking
  before it speaks.
- English only, because it uses the English speech model.

## Layout

```
voiceisland/
  config.py       settings, paths, logging
  audio.py        microphone capture
  speech.py       speech to text, text to speech
  claude.py       the bridge to the claude CLI
  sessions.py     reads your Claude Code chats
  approver.py     the MCP server that asks before anything runs
  activity.py     turns tool calls into a readable line
  dialogs.py      native yes/no prompts
  singleton.py    one instance at a time
  launchagent.py  start at login
  ui/
    app.py        the window and the event loop
    pill.py       the view, the state machine, the recording
    notch.py      the notch shape and the numbers behind it
    menu.py       the ⌄ menu
    symbols.py    cached, tinted SF Symbols
```

## Development

```bash
./venv/bin/python -m pytest      # 93 tests, no microphone needed
./venv/bin/ruff check .
```

The tests cover the parts where being wrong is expensive: what the approver
does when a dialog fails, what argv is built for each permission mode, how chat
files are parsed, and what text the speech engine is handed. Nothing there
touches your real settings, a microphone, or the network.

Pull requests welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Credit

The notch shape follows the approach taken by
[Atoll](https://github.com/Renset/Atoll),
[boring.notch](https://github.com/TheBoredTeam/boring.notch) and
[DynamicNotchKit](https://github.com/MrKai77/DynamicNotchKit). Concave shoulders
flaring to full width, straight sides, rounded bottom. Getting those curves
right is the difference between a window that belongs to the hardware and a
black rectangle taped underneath the camera.

Speech recognition is [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
Voices are [edge-tts](https://github.com/rany2/edge-tts).

## License

MIT. See [LICENSE](LICENSE).
