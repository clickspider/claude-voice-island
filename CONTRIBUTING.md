# Contributing

Issues and pull requests are welcome. It's a small project, so this is short.

## Getting set up

```bash
./scripts/setup.sh
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/python -m pytest
./venv/bin/ruff check .
```

Both have to pass before a pull request gets reviewed, and CI runs the same two
commands on macOS.

## Running it while you work on it

```bash
VOICE_ISLAND_VERBOSE=1 ./venv/bin/python -m voiceisland
```

That mirrors the log to your terminal instead of only writing it to
`~/Library/Logs/ClaudeVoiceIsland/island.log`.

`VOICE_ISLAND_HOME` moves settings and logs somewhere else, which is handy for
trying a change without touching the setup you actually use:

```bash
VOICE_ISLAND_HOME=/tmp/island-test ./venv/bin/python -m voiceisland
```

## What tests are expected

Anything testable without a microphone, a screen, or the network should be
tested. In practice that means pure functions: parsing, text handling, argv
building, the approver's decisions. Those live in modules of their own precisely
so they can be tested, and `tests/` shows the pattern.

Changes to the drawing code are hard to test and get reviewed by looking at them.
Say in the pull request what you checked by eye.

## How a pull request gets merged

`main` is protected, so nothing lands on it directly. The path is: branch, push,
open a pull request, and it merges as a single squashed commit once the gates
below are green.

- CI has to pass on Python 3.11, 3.12 and 3.13. Those three checks are required,
  not advisory, and a red one blocks the merge button.
- CodeQL runs on every pull request. A new alert is worth a comment even if you
  think it is a false positive.
- The branch has to be up to date with `main` before it merges, which keeps the
  history linear and means the commit that CI tested is the commit that lands.
- One review from the code owner, and every review thread resolved. Pushing new
  commits dismisses an approval, so the code that got read is the code that ships.

If you opened the pull request from a fork, CI will sit and wait until a
maintainer approves the run. That is not a comment on your change. Every job here
runs on a macOS runner, which bills at ten times the Linux rate, so no fork gets
to start one unattended.

Small and focused merges quickly. A pull request that renames things, fixes a
bug and adds a feature at once will get asked to split, because there is no way
to accept a third of it.

## Things worth knowing before you change something

**PyObjC method names are Objective-C selectors.** `drawRect_`, `mouseDown_`,
`initWithFrame_`. They can't be renamed to look like Python, and they each carry
a `# noqa: N802` rather than the rule being switched off for the project.

**Anything that draws runs on the main thread.** Work off the main thread hands
results back with `AppHelper.callAfter`. Every worker also carries the generation
it was started for and stops when it no longer matches, which is what makes
interrupting a reply work instead of producing two overlapping answers.

**The approver fails closed, and should stay that way.** If you touch
`approver.py` or `dialogs.py`, the tests in `tests/test_approver.py` and
`tests/test_dialogs.py` are the specification. Anything other than a click on the
allow button is a no.

**Broad excepts have to justify themselves.** Ruff has `BLE` enabled, so
`except Exception` needs a `# noqa: BLE001` and a comment saying why swallowing it
is the right call. Usually the answer is that losing the voice shouldn't lose the
turn.

## Style

Ruff settings are in `pyproject.toml`. Beyond that: comments explain why, not
what, and a comment that restates the line above it is worse than no comment.

If a change alters what leaves the machine, what runs without asking, or what
gets written to disk, say so in the pull request and update
[SECURITY.md](SECURITY.md) in the same change.
