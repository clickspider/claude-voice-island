## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem, not the patch. If it fixes an issue, write "Fixes #123". -->

## How it was checked

<!-- Say what you actually ran. "Held the key down and watched the pill" is a
     real answer for the drawing code. -->

- [ ] `./venv/bin/python -m pytest` passes
- [ ] `./venv/bin/ruff check .` is clean
- [ ] Tried it on a real macOS machine, not only in CI

## Anything a reviewer should look at twice

<!-- Delete if there isn't any. -->

---

Before you open this, please read `CONTRIBUTING.md`. Two things trip people up
most often: this is a macOS-only project, so CI cannot check a change that only
matters on another platform, and anything testable without a microphone, a
screen, or the network is expected to come with a test.
