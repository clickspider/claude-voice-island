"""Drawing SF Symbols, tinted and cached.

The pill redraws thirty times a second while it animates, and every frame draws
the same handful of glyphs in the same handful of colours. Loading and tinting a
symbol is not free, so both steps are cached by (name, size) and by colour. The
key space is tiny and fixed by the code, so the caches cannot grow without
bound.

Every function here returns False rather than raising when a symbol is missing,
so an older macOS without one glyph loses a glyph, not the pill.
"""

from __future__ import annotations

from AppKit import (
    NSColor,
    NSCompositingOperationSourceAtop,
    NSCompositingOperationSourceOver,
    NSFontWeightMedium,
    NSImage,
    NSImageSymbolConfiguration,
    NSRectFillUsingOperation,
)
from Foundation import NSMakeRect, NSZeroRect

_images: dict[tuple[str, float], object] = {}
_tinted: dict[tuple, object] = {}


def image(name: str, point_size: float = 15.0):
    """A template NSImage for an SF Symbol, or None if this macOS lacks it."""
    key = (name, point_size)
    if key in _images:
        return _images[key]
    symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if symbol is not None:
        configuration = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
            point_size, NSFontWeightMedium
        )
        symbol = symbol.imageWithSymbolConfiguration_(configuration) or symbol
        symbol.setTemplate_(True)
    _images[key] = symbol
    return symbol


def draw(name: str, center_x: float, center_y: float, rgb, point_size: float = 15.0) -> bool:
    """Draw a symbol centred at a point, in `rgb`. False when it is unavailable."""
    base = image(name, point_size)
    if base is None:
        return False
    key = (name, point_size, round(rgb[0], 2), round(rgb[1], 2), round(rgb[2], 2))
    symbol = _tinted.get(key)
    if symbol is None:
        symbol = base.copy()
        size = symbol.size()
        symbol.lockFocus()
        NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb, 1.0).set()
        # Source-atop paints the colour only where the glyph already is, which is
        # what turns a template image into a coloured one.
        NSRectFillUsingOperation(
            NSMakeRect(0, 0, size.width, size.height), NSCompositingOperationSourceAtop
        )
        symbol.unlockFocus()
        _tinted[key] = symbol
    size = symbol.size()
    symbol.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
        NSMakeRect(
            center_x - size.width / 2, center_y - size.height / 2, size.width, size.height
        ),
        NSZeroRect,
        NSCompositingOperationSourceOver,
        1.0,
        True,
        None,
    )
    return True
