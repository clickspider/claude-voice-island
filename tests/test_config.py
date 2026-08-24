from __future__ import annotations

import json

from voiceisland import config


def test_defaults_when_nothing_is_stored():
    settings = config.load()
    assert settings["permissions"] == "prompt"
    assert settings["log_transcripts"] is False
    assert settings["safe_tools"] == ["Glob", "Grep", "TodoWrite"]


def test_reading_a_file_is_not_pre_approved():
    # Read opens any file the user can open, including keys and .env files, so
    # it has to go through a dialog that shows the path.
    assert "Read" not in config.load()["safe_tools"]


def test_save_merges_instead_of_replacing():
    config.save({"voice": "en-GB-RyanNeural"})
    config.save({"ptt": "option"})
    settings = config.load()
    assert settings["voice"] == "en-GB-RyanNeural"
    assert settings["ptt"] == "option"


def test_unknown_keys_survive_a_round_trip():
    config.save({"experiment": 42})
    assert config.load()["experiment"] == 42


def test_stored_file_is_readable_json():
    config.save({"narrate": True})
    stored = json.loads(config.config_path().read_text())
    assert stored["narrate"] is True


def test_a_corrupt_file_falls_back_to_defaults():
    config.config_path().write_text("{ this is not json")
    assert config.load()["permissions"] == "prompt"


def test_partial_config_is_completed_by_defaults():
    config.config_path().write_text(json.dumps({"voice": "custom"}))
    settings = config.load()
    assert settings["voice"] == "custom"
    assert settings["tts_engine"] == "edge"


def test_save_leaves_no_temporary_files_behind():
    config.save({"voice": "one"})
    config.save({"voice": "two"})
    leftovers = [p.name for p in config.app_dir().iterdir() if p.name.startswith(".config-")]
    assert leftovers == []
