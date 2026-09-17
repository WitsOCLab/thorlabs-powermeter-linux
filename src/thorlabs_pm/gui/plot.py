"""Plot drawing shared by the meter and the alignment window.

The charts were bare polylines with a number in each corner. Instrument software draws a grid
on round values, labels the axes, and marks the extremes - Thorlabs' graph and statistics
panels are the reference. Pure cairo, no dependency, and no widget: callers hand it a context.
"""

from __future__ import annotations

import math
import time


def nice_step(span: float, target: int = 4) -> float:
    """A 1, 2 or 5 times a power of ten step that puts about `target` lines across `span`."""
    if span <= 0 or not math.isfinite(span):
        return 1.0
    raw = span / max(target, 1)
    power = 10.0 ** math.floor(math.log10(raw))
    for multiple in (1.0, 2.0, 5.0, 10.0):
        if raw <= multiple * power:
            return multiple * power
    return 10.0 * power


def ticks(lo: float, hi: float, target: int = 4) -> list[float]:
    """Round values between lo and hi, for gridlines that land on numbers a person would pick."""
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return []
    step = nice_step(hi - lo, target)
    first = math.ceil(lo / step) * step
    out, value = [], first
    while value <= hi + step * 1e-6 and len(out) < 40:
        out.append(value)
        value += step
    return out


def _rgba(cr, colour, alpha):
    cr.set_source_rgba(colour.red, colour.green, colour.blue, alpha)


def draw_grid(cr, width, height, colour, *, rows=4, columns=6):
    _rgba(cr, colour, 0.10)
    cr.set_line_width(1.0)
    for i in range(1, rows):
        y = round(height * i / rows) + 0.5
        cr.move_to(0, y)
        cr.line_to(width, y)
    for i in range(1, columns):
        x = round(width * i / columns) + 0.5
        cr.move_to(x, 0)
        cr.line_to(x, height)
    cr.stroke()


def draw_frame(cr, width, height, colour):
    _rgba(cr, colour, 0.06)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    _rgba(cr, colour, 0.25)
    cr.set_line_width(1.0)
    cr.rectangle(0.5, 0.5, width - 1, height - 1)
    cr.stroke()


def label(cr, colour, x, y, text, *, alpha=0.65, size=10.5):
    _rgba(cr, colour, alpha)
    cr.set_font_size(size)
    cr.move_to(x, y)
    cr.show_text(text)


def draw_series(cr, width, height, points, *, colour, accent=None, window_s=120.0,
                format_value=lambda v: f"{v:.3g}", now=None, fill=True, mark_max=True):
    """`points` is a sequence of (unix time, value). Returns (lo, hi) of the drawn range."""
    draw_frame(cr, width, height, colour)
    values = [v for _, v in points]
    if len(values) < 2:
        label(cr, colour, 8, height / 2, "waiting for readings", alpha=0.45)
        return (0.0, 0.0)

    lo, hi = min(values), max(values)
    span = (hi - lo) or abs(hi) or 1.0
    lo, hi = lo - 0.08 * span, hi + 0.08 * span
    t_now = now if now is not None else points[-1][0]

    # gridlines on round values, labelled on the left
    for value in ticks(lo, hi, 4):
        y = height * (1 - (value - lo) / (hi - lo))
        if y < 12 or y > height - 4:
            continue
        _rgba(cr, colour, 0.10)
        cr.set_line_width(1.0)
        cr.move_to(0, round(y) + 0.5)
        cr.line_to(width, round(y) + 0.5)
        cr.stroke()
        label(cr, colour, 6, y - 3, format_value(value), alpha=0.45, size=10)

    # time gridlines every round number of seconds back from now
    step = nice_step(window_s, 5)
    seconds = step
    while seconds < window_s:
        x = width * (1 - seconds / window_s)
        _rgba(cr, colour, 0.08)
        cr.move_to(round(x) + 0.5, 0)
        cr.line_to(round(x) + 0.5, height)
        cr.stroke()
        label(cr, colour, x + 4, height - 5, f"-{seconds:g}s", alpha=0.35, size=9.5)
        seconds += step

    def place(t, v):
        return (width * (1 - (t_now - t) / window_s), height * (1 - (v - lo) / (hi - lo)))

    if fill:
        cr.move_to(*place(points[0][0], lo))
        for t, v in points:
            cr.line_to(*place(t, v))
        cr.line_to(*place(points[-1][0], lo))
        cr.close_path()
        _rgba(cr, accent or colour, 0.12)
        cr.fill()

    _rgba(cr, accent or colour, 0.95)
    cr.set_line_width(1.6)
    for i, (t, v) in enumerate(points):
        (cr.move_to if i == 0 else cr.line_to)(*place(t, v))
    cr.stroke()

    if mark_max:
        peak_t, peak_v = max(points, key=lambda p: p[1])
        x, y = place(peak_t, peak_v)
        _rgba(cr, colour, 0.5)
        cr.set_line_width(1.0)
        cr.arc(x, y, 2.5, 0, 2 * math.pi)
        cr.stroke()

    # the latest point, which is what the eye follows
    x, y = place(*points[-1])
    _rgba(cr, accent or colour, 1.0)
    cr.arc(x, y, 3.0, 0, 2 * math.pi)
    cr.fill()
    return (lo, hi)


def draw_gauge(cr, width, height, fraction, *, colour, accent, label_text="", span_deg=120.0):
    """A needle against an arc: the tuning display alignment work actually wants, where the
    direction of change matters more than the digits."""
    # The arc spans span_deg about straight up, so it reaches (radius * sin(span/2)) sideways and
    # (radius * (1 - cos(span/2))) below the top of its sweep. Size the radius from whichever of
    # those the box runs out of first, or the arc clips - which it did at 92 px tall.
    # The needle pivots at the bottom of the box and the arc rises span_deg about straight up,
    # so the radius is limited by the half-width it needs sideways and by the height itself.
    # Sizing it from the arc's vertical extent alone put the pivot below the widget.
    half = math.radians(span_deg) / 2
    margin = 10.0
    cx, cy = width / 2, height - margin
    radius = min((width / 2 - margin) / max(math.sin(half), 1e-6), height - 2 * margin)
    start = math.radians(180 + (180 - span_deg) / 2)
    end = start + math.radians(span_deg)

    _rgba(cr, colour, 0.25)
    cr.set_line_width(6)
    cr.arc(cx, cy, radius, start, end)
    cr.stroke()

    for i in range(11):
        angle = start + (end - start) * i / 10
        inner = radius - (10 if i % 5 == 0 else 5)
        _rgba(cr, colour, 0.5 if i % 5 == 0 else 0.3)
        cr.set_line_width(1.5)
        cr.move_to(cx + inner * math.cos(angle), cy + inner * math.sin(angle))
        cr.line_to(cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        cr.stroke()

    fraction = min(max(fraction, 0.0), 1.0)
    angle = start + (end - start) * fraction
    _rgba(cr, accent, 1.0)
    cr.set_line_width(2.5)
    cr.move_to(cx, cy)
    cr.line_to(cx + (radius - 8) * math.cos(angle), cy + (radius - 8) * math.sin(angle))
    cr.stroke()
    cr.arc(cx, cy, 4, 0, 2 * math.pi)
    cr.fill()
    if label_text:
        label(cr, colour, 6, 14, label_text, alpha=0.6)
