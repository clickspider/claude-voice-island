from __future__ import annotations

import pytest

from voiceisland import singleton


def test_the_first_caller_gets_the_lock():
    handle = singleton.acquire()
    try:
        assert not handle.closed
    finally:
        handle.close()


def test_a_second_caller_is_told_to_go_away():
    first = singleton.acquire()
    try:
        with pytest.raises(singleton.AlreadyRunningError):
            singleton.acquire()
    finally:
        first.close()


def test_the_lock_is_free_again_once_released():
    singleton.acquire().close()
    second = singleton.acquire()
    second.close()


def test_the_lock_file_records_the_process_that_holds_it():
    handle = singleton.acquire()
    try:
        contents = (singleton.config.app_dir() / "island.lock").read_text()
        assert contents.strip().isdigit()
    finally:
        handle.close()
