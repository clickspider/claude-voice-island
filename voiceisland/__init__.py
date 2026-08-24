"""Claude Voice Island: a push-to-talk voice interface for Claude Code.

Hold the pill under the MacBook notch, speak, release. Speech is transcribed
locally, sent to a real Claude Code session, and the reply is spoken back.

Layout:
    config       settings, paths, logging
    audio        microphone capture
    speech       speech to text, text to speech
    claude       the bridge to the `claude` CLI
    sessions     lists the Claude Code chats you can continue
    approver     MCP server that asks permission before any tool runs
    activity     turns tool calls into a line a human can read
    dialogs      native macOS yes/no prompts
    ui           the floating pill, its menu, and the app entry point
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
