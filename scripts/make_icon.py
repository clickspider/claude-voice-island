"""Draw the app icon and build the .icns file macOS wants.

    python scripts/make_icon.py [output-directory]

Writes icon_1024.png and icon.icns. Both are generated rather than committed, so
the icon has a source you can change instead of a binary you have to redraw.

The icon is a dark squircle with a white microphone and a blue waveform under
it, which is the pill's own vocabulary at Dock size.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationSourceAtop,
    NSCompositingOperationSourceOver,
    NSFontWeightSemibold,
    NSGradient,
    NSImage,
    NSImageSymbolConfiguration,
    NSMakeRect,
    NSRectFillUsingOperation,
)
from Foundation import NSZeroRect

SIZE = 1024.0
# Apple's continuous corner ratio. A plain rounded rectangle at this size reads
# as the wrong shape next to every other icon in the Dock.
CORNER_RATIO = 0.2237
INSET = 76.0
ACCENT = (0.25, 0.77, 1.0)

# The sizes a .icns must contain, as (pixels, name in the iconset).
_ICONSET = [
    (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
]


def draw() -> NSImage:
    image = NSImage.alloc().initWithSize_((SIZE, SIZE))
    image.lockFocus()

    side = SIZE - 2 * INSET
    squircle = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(INSET, INSET, side, side), side * CORNER_RATIO, side * CORNER_RATIO
    )
    NSGradient.alloc().initWithStartingColor_endingColor_(
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.15, 0.17, 1.0),
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.02, 0.02, 0.03, 1.0),
    ).drawInBezierPath_angle_(squircle, -90.0)

    _draw_microphone()
    _draw_waveform()

    image.unlockFocus()
    return image


def _draw_microphone() -> None:
    symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mic.fill", None)
    configuration = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        300.0, NSFontWeightSemibold
    )
    symbol = symbol.imageWithSymbolConfiguration_(configuration) or symbol
    symbol.setTemplate_(True)

    white = symbol.copy()
    size = white.size()
    white.lockFocus()
    NSColor.whiteColor().set()
    NSRectFillUsingOperation(
        NSMakeRect(0, 0, size.width, size.height), NSCompositingOperationSourceAtop
    )
    white.unlockFocus()

    scale = 500.0 / size.height
    width, height = size.width * scale, size.height * scale
    white.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
        NSMakeRect((SIZE - width) / 2, (SIZE - height) / 2 + 40, width, height),
        NSZeroRect, NSCompositingOperationSourceOver, 1.0, True, None,
    )


def _draw_waveform() -> None:
    NSColor.colorWithCalibratedRed_green_blue_alpha_(*ACCENT, 1.0).set()
    heights = [90, 150, 210, 150, 90]
    bar, gap = 34.0, 34.0
    total = len(heights) * bar + (len(heights) - 1) * gap
    x = (SIZE - total) / 2
    for height in heights:
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x, INSET + 150, bar, height), bar / 2, bar / 2
        ).fill()
        x += bar + gap


def write_png(image: NSImage, path: Path) -> None:
    representation = NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
    data = representation.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    data.writeToFile_atomically_(str(path), True)


def write_icns(png: Path, icns: Path) -> None:
    """Resize the master PNG into every size an .icns needs, then pack it."""
    with tempfile.TemporaryDirectory() as workspace:
        iconset = Path(workspace) / "icon.iconset"
        iconset.mkdir()
        for pixels, name in _ICONSET:
            subprocess.run(
                ["/usr/bin/sips", "-z", str(pixels), str(pixels), str(png),
                 "--out", str(iconset / name)],
                check=True, capture_output=True,
            )
        subprocess.run(
            ["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
            check=True, capture_output=True,
        )


def main(argv: list[str]) -> int:
    if not shutil.which("iconutil"):
        print("iconutil is missing, so this only runs on macOS", file=sys.stderr)
        return 1
    target = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    target.mkdir(parents=True, exist_ok=True)
    png = target / "icon_1024.png"
    icns = target / "icon.icns"
    write_png(draw(), png)
    write_icns(png, icns)
    print(f"wrote {png}")
    print(f"wrote {icns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
