"""The shape of the notch, and the numbers that make the window sit inside it.

The trick that makes this look built in rather than stuck on: the window's top
edge is placed at the very top of the screen, over the camera cutout, and filled
with pure black. The physical notch is also pure black, so the two are one shape
with no seam. Closed, the window is exactly the size of the notch and therefore
invisible. Opening it grows the same shape downward.

The outline follows the notch shape used by Atoll, boring.notch and
DynamicNotchKit: concave shoulders at the top that flare out to full width, then
straight sides and a rounded bottom. Matching those curves is what stops the
window from reading as a black rectangle taped under the camera.
"""

from __future__ import annotations

from AppKit import NSBezierPath
from Foundation import NSMakePoint

# Fallback width for the closed state when the screen will not report its notch.
DEFAULT_NOTCH_WIDTH = 185.0

OPEN_WIDTH = 360.0        # width once opened
OPEN_HANG = 44.0          # how far the opened shape hangs below the notch
FEED_WIDTH = 420.0        # width of the activity card
FEED_ROW_HEIGHT = 22.0
FEED_MAX_ROWS = 7         # rows shown at once, newest kept

# (top, bottom) corner radii. Closed matches the physical notch exactly. Open is
# gentler: the same tight shoulders on a wider shape read as hooks carved out of
# empty screen.
RADII_CLOSED = (6.0, 14.0)
RADII_OPEN = (11.0, 20.0)

# On a screen with no notch there is nothing to merge with, so the pill becomes a
# small floating capsule you can drag anywhere.
FLOAT_HEIGHT = 30.0
FLOAT_CLOSED_WIDTH = 66.0


def quad_curve(path, start, end, control):
    """Append a quadratic curve to an NSBezierPath, which only speaks cubic.

    The shape is defined with quadratic curves, so each one is converted using
    the standard control point lift: two thirds of the way from each endpoint
    toward the quadratic's single control point.
    """
    first = (
        start[0] + 2 / 3 * (control[0] - start[0]),
        start[1] + 2 / 3 * (control[1] - start[1]),
    )
    second = (
        end[0] + 2 / 3 * (control[0] - end[0]),
        end[1] + 2 / 3 * (control[1] - end[1]),
    )
    path.curveToPoint_controlPoint1_controlPoint2_(
        NSMakePoint(*end), NSMakePoint(*first), NSMakePoint(*second)
    )
    return end


def notch_path(bounds, top_radius: float, bottom_radius: float):
    """The notch outline for `bounds`, in a flipped (top left origin) view."""
    min_x, min_y = 0.0, 0.0
    max_x, max_y = bounds.size.width, bounds.size.height
    path = NSBezierPath.bezierPath()
    point = (min_x, min_y)
    path.moveToPoint_(NSMakePoint(*point))

    # Left shoulder curving inward, down the left side, out along the bottom,
    # up the right side, then the right shoulder back to the top edge.
    point = quad_curve(path, point, (min_x + top_radius, min_y + top_radius),
                       (min_x + top_radius, min_y))
    path.lineToPoint_(NSMakePoint(min_x + top_radius, max_y - bottom_radius))
    point = (min_x + top_radius, max_y - bottom_radius)
    point = quad_curve(path, point, (min_x + top_radius + bottom_radius, max_y),
                       (min_x + top_radius, max_y))
    path.lineToPoint_(NSMakePoint(max_x - top_radius - bottom_radius, max_y))
    point = (max_x - top_radius - bottom_radius, max_y)
    point = quad_curve(path, point, (max_x - top_radius, max_y - bottom_radius),
                       (max_x - top_radius, max_y))
    path.lineToPoint_(NSMakePoint(max_x - top_radius, min_y + top_radius))
    point = (max_x - top_radius, min_y + top_radius)
    quad_curve(path, point, (max_x, min_y), (max_x - top_radius, min_y))
    path.lineToPoint_(NSMakePoint(min_x, min_y))
    path.closePath()
    return path


def measure_notch_width(screen) -> float:
    """The width of the physical notch, from the gap between the two top areas.

    macOS exposes the usable strips either side of the camera housing. The space
    between them is the notch. Anything outside a believable range means the
    screen did not really answer, so the fallback is used.
    """
    try:
        left = screen.auxiliaryTopLeftArea()
        right = screen.auxiliaryTopRightArea()
        width = right.origin.x - (left.origin.x + left.size.width)
    except (AttributeError, TypeError):
        return DEFAULT_NOTCH_WIDTH
    if 60.0 < width < 400.0:
        return width
    return DEFAULT_NOTCH_WIDTH


def notch_height(screen) -> float:
    """Height of the notch on this screen, or 0 when there is none."""
    try:
        return float(screen.safeAreaInsets().top)
    except (AttributeError, TypeError):
        return 0.0
