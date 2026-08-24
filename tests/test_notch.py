"""Geometry. These need AppKit, so they run on macOS and are skipped elsewhere."""

from __future__ import annotations

import types

import pytest

pytest.importorskip("AppKit")

from voiceisland.ui import notch


def screen(left_width=740.0, right_x=925.0, notch_height=32.0):
    """A stand-in for NSScreen, answering only what the code asks it."""
    return types.SimpleNamespace(
        auxiliaryTopLeftArea=lambda: types.SimpleNamespace(
            origin=types.SimpleNamespace(x=0.0), size=types.SimpleNamespace(width=left_width)
        ),
        auxiliaryTopRightArea=lambda: types.SimpleNamespace(
            origin=types.SimpleNamespace(x=right_x)
        ),
        safeAreaInsets=lambda: types.SimpleNamespace(top=notch_height),
    )


def test_the_notch_width_is_the_gap_between_the_two_top_areas():
    assert notch.measure_notch_width(screen()) == 185.0


def test_an_impossible_width_falls_back_to_the_default():
    assert notch.measure_notch_width(screen(right_x=741.0)) == notch.DEFAULT_NOTCH_WIDTH
    assert notch.measure_notch_width(screen(right_x=2000.0)) == notch.DEFAULT_NOTCH_WIDTH


def test_a_screen_that_answers_nothing_falls_back_to_the_default():
    assert notch.measure_notch_width(types.SimpleNamespace()) == notch.DEFAULT_NOTCH_WIDTH


def test_a_screen_with_no_notch_reports_zero_height():
    assert notch.notch_height(screen(notch_height=0.0)) == 0.0
    assert notch.notch_height(types.SimpleNamespace()) == 0.0


def test_the_shape_is_closed_and_covers_the_bounds():
    bounds = types.SimpleNamespace(size=types.SimpleNamespace(width=200.0, height=40.0))
    path = notch.notch_path(bounds, *notch.RADII_CLOSED)
    box = path.bounds()
    assert box.size.width == pytest.approx(200.0, abs=1.0)
    assert box.size.height == pytest.approx(40.0, abs=1.0)
    assert path.elementCount() > 4


def test_the_open_shape_is_gentler_than_the_closed_one():
    # The opened tab is wider than the notch, so the same tight shoulders would
    # read as hooks cut out of empty screen.
    assert notch.RADII_OPEN[0] > notch.RADII_CLOSED[0]
    assert notch.RADII_OPEN[1] > notch.RADII_CLOSED[1]
