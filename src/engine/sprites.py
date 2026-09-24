"""Billboard sprite system plus the procedural pixel art behind it.

Sprites are plain world-space billboards: they always face the camera, and the
rotation the player perceives comes from swapping between pre-rendered views
(front / three-quarter / side / back). That is cheap and looks believable.

Every character, vehicle and prop is drawn here from primitives, so there are
no external art assets.
"""

import math

import numpy as np

from ..utils import dist_sq, normalise_angle
from .textures import RNG

# ------------------------------------------------------------------ canvas ---
# Colours as (r, g, b) floats. Alpha starts at 0 for a transparent canvas.
ALPHA_IDX = 3


def _canvas(w, h):
    return np.zeros((h, w, 4), dtype=np.float32)


def _fill(img, colour, alpha=255.0):
    img[:, :, 0] = colour[0]
    img[:, :, 1] = colour[1]
    img[:, :, 2] = colour[2]
    img[:, :, ALPHA_IDX] = alpha
    return img


def _rect(img, x, y, w, h, colour, alpha=255.0):
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(img.shape[1], int(x + w)), min(img.shape[0], int(y + h))
    if x1 <= x0 or y1 <= y0:
        return img
    img[y0:y1, x0:x1, 0] = colour[0]
    img[y0:y1, x0:x1, 1] = colour[1]
    img[y0:y1, x0:x1, 2] = colour[2]
    img[y0:y1, x0:x1, ALPHA_IDX] = alpha
    return img


def _shade_rect(img, x, y, w, h, factor):
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(img.shape[1], int(x + w)), min(img.shape[0], int(y + h))
    if x1 <= x0 or y1 <= y0:
        return img
    img[y0:y1, x0:x1, 0:3] *= factor
    return img


def _ellipse(img, cx, cy, rx, ry, colour, alpha=255.0):
    h, w = img.shape[0], img.shape[1]
    ys, xs = np.mgrid[0:h, 0:w]
    mask = ((xs - cx) / max(rx, 1e-6)) ** 2 + ((ys - cy) / max(ry, 1e-6)) ** 2 <= 1.0
    img[mask, 0] = colour[0]
    img[mask, 1] = colour[1]
    img[mask, 2] = colour[2]
    img[mask, ALPHA_IDX] = alpha
    return img


def _line(img, x0, y0, x1, y1, colour, width=1, alpha=255.0):
    length = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    xs = np.linspace(x0, x1, length)
    ys = np.linspace(y0, y1, length)
    h, w = img.shape[0], img.shape[1]
    half = width / 2.0
    for px, py in zip(xs, ys):
        xa, xb = int(px - half), int(px + half) + 1
        ya, yb = int(py - half), int(py + half) + 1
        xa, xb = max(0, xa), min(w, xb)
        ya, yb = max(0, ya), min(h, yb)
        if xb > xa and yb > ya:
            img[ya:yb, xa:xb, 0] = colour[0]
            img[ya:yb, xa:xb, 1] = colour[1]
            img[ya:yb, xa:xb, 2] = colour[2]
            img[ya:yb, xa:xb, ALPHA_IDX] = alpha
    return img


def _outline(img, colour=(12, 12, 16)):
    """Darken opaque pixels that border transparency, for readable silhouettes."""
    alpha = img[:, :, ALPHA_IDX]
    opaque = alpha > 128
    neighbour_gap = np.zeros_like(opaque)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        shifted = np.roll(np.roll(opaque, dy, axis=0), dx, axis=1)
        neighbour_gap |= opaque & ~shifted
    img[neighbour_gap, 0] = colour[0]
    img[neighbour_gap, 1] = colour[1]
    img[neighbour_gap, 2] = colour[2]
    return img


def _add_grain(img, amount=6.0):
    h, w = img.shape[:2]
    noise = RNG.uniform(-amount, amount, (h, w, 1))
    img[:, :, 0:3] = np.clip(img[:, :, 0:3] + noise, 0, 255)
    return img


def _finalise(img, outline=True, grain=5.0):
    if grain > 0:
        _add_grain(img, grain)
    if outline:
        _outline(img)
    return img


# ------------------------------------------------------------------ palette --
UNIFORM = (58, 64, 50)          # dark olive fatigues
UNIFORM_DARK = (40, 45, 36)
UNIFORM_LIGHT = (72, 79, 62)
VEST = (44, 48, 42)
BOOTS = (28, 28, 30)
SKIN = (196, 156, 120)
SKIN_DARK = (150, 116, 88)
HELMET = (52, 56, 48)
HELMET_DARK = (34, 37, 32)
GUNMETAL = (46, 48, 52)
GUNMETAL_LIGHT = (78, 80, 86)
WOOD = (96, 68, 40)
CANVAS = (86, 84, 62)
CANVAS_DARK = (62, 60, 44)
TYRE = (24, 24, 26)
TRUCK_BODY = (56, 70, 48)
TRUCK_DARK = (38, 48, 34)
GLASS = (70, 92, 104)
RED = (196, 44, 40)
AMBER = (232, 178, 68)
LAMP = (255, 236, 190)


# ---------------------------------------------------------------- soldier ----
def _soldier(pose, walk_phase, has_rifle=True, officer=False):
    """Draw one soldier frame.

    `pose` selects the view: 0 front, 1 front-3/4, 2 side, 3 back-3/4, 4 back.
    `walk_phase` is 0..2 and shifts the legs.
    """
    W, H = 34, 62
    img = _canvas(W, H)
    uniform = (72, 70, 52) if officer else UNIFORM
    uniform_dark = (52, 50, 38) if officer else UNIFORM_DARK

    # Leg swing: -1, 0, +1 by phase.
    swing = (-1, 0, 1)[walk_phase % 3]
    leg_y = 40
    leg_h = 18

    # --- legs ---
    if pose in (2, 1, 3):
        # side/three-quarter: legs read as one front, one back
        back_off = swing * 3
        _rect(img, 13 + back_off, leg_y, 6, leg_h, uniform_dark)
        _rect(img, 16 - back_off, leg_y, 6, leg_h, uniform)
        _rect(img, 12 + back_off, leg_y + leg_h - 3, 8, 4, BOOTS)
        _rect(img, 15 - back_off, leg_y + leg_h - 3, 8, 4, BOOTS)
    else:
        spread = 1 + abs(swing)
        _rect(img, 11 - spread, leg_y, 6, leg_h, uniform_dark)
        _rect(img, 18 + spread - 1, leg_y, 6, leg_h, uniform)
        _rect(img, 10 - spread, leg_y + leg_h - 3, 8, 4, BOOTS)
        _rect(img, 18 + spread - 1, leg_y + leg_h - 3, 8, 4, BOOTS)

    # --- torso ---
    _rect(img, 11, 22, 13, 20, uniform)
    _shade_rect(img, 11, 22, 5, 20, 0.86)     # left side in shadow
    # tactical vest
    _rect(img, 12, 25, 11, 13, VEST)
    _rect(img, 13, 27, 4, 3, (58, 62, 54))    # pouch
    _rect(img, 18, 30, 4, 5, (58, 62, 54))    # pouch
    if officer:
        # rank tabs / map case
        _rect(img, 13, 24, 9, 2, AMBER)
        _rect(img, 20, 26, 3, 3, (70, 60, 44))

    # --- head ---
    head_cx = 17
    if pose == 2:
        head_cx = 18
    elif pose in (1, 3):
        head_cx = 18 if pose == 1 else 16
    _ellipse(img, head_cx, 16, 5, 6, SKIN)
    _ellipse(img, head_cx - 1, 17, 3, 3, SKIN_DARK)
    # helmet
    _ellipse(img, head_cx, 13, 6, 4, HELMET if not officer else (60, 54, 40))
    _rect(img, head_cx - 6, 13, 12, 3, HELMET_DARK)
    if pose in (2,):
        _rect(img, head_cx - 1, 15, 6, 4, SKIN_DARK)   # nose profile

    # --- arms + weapon ---
    if has_rifle:
        if pose in (0, 4):
            # rifle held across the body, muzzle towards viewer (foreshortened)
            _rect(img, 19, 28, 5, 6, uniform)
            _rect(img, 12, 28, 5, 6, uniform_dark)
            _rect(img, 15, 33, 4, 10, GUNMETAL)
            _rect(img, 15, 42, 4, 3, GUNMETAL_LIGHT)
            if pose == 4:
                _shade_rect(img, 11, 22, 13, 20, 0.82)
        elif pose == 2:
            # classic side profile: rifle horizontal at the hip
            _rect(img, 15, 28, 5, 5, uniform)
            _rect(img, 19, 30, 12, 3, GUNMETAL)
            _rect(img, 28, 30, 4, 2, GUNMETAL_LIGHT)   # barrel
            _rect(img, 18, 33, 4, 6, GUNMETAL)         # magazine
            _rect(img, 14, 30, 3, 3, WOOD)             # stock
        else:
            # three-quarter: diagonal rifle
            _rect(img, 19, 27, 5, 6, uniform)
            _line(img, 15, 36, 26, 28, GUNMETAL, width=3)
            _line(img, 24, 30, 29, 27, GUNMETAL_LIGHT, width=2)
            _rect(img, 17, 34, 3, 5, GUNMETAL)
    else:
        _rect(img, 10, 24, 4, 12, uniform_dark)
        _rect(img, 21, 24, 4, 12, uniform)

    if pose in (3, 4):
        _shade_rect(img, 10, 20, 15, 24, 0.9)
    return _finalise(img)


def soldier_frames(frames_per_view=3, rifle=True, officer=False):
    """Return {view_index: [frame, ...]} for the 5 base views."""
    art = {}
    for view in range(5):
        art[view] = [_soldier(view, phase, rifle, officer)
                     for phase in range(frames_per_view)]
    return art


# ------------------------------------------------------------------ truck ----
def _truck(pose):
    """Army cargo truck billboard.

    pose 0 = side, 1 = three-quarter front, 2 = front, 3 = three-quarter back,
    4 = back.
    """
    W, H = 104, 52
    img = _canvas(W, H)
    body = TRUCK_BODY
    dark = TRUCK_DARK

    if pose == 0:
        # long side view
        _rect(img, 6, 12, 70, 24, body)
        _rect(img, 6, 12, 70, 4, dark)
        # canvas cargo cover
        _rect(img, 22, 6, 54, 8, CANVAS)
        _rect(img, 22, 6, 54, 2, CANVAS_DARK)
        for x in range(26, 74, 9):
            _rect(img, x, 7, 2, 7, CANVAS_DARK)
        # cab
        _rect(img, 4, 10, 22, 26, body)
        _rect(img, 4, 10, 22, 3, dark)
        _rect(img, 7, 13, 12, 8, GLASS)
        _rect(img, 7, 22, 16, 5, dark)
        # wheels
        for cx in (16, 40, 62):
            _ellipse(img, cx, 40, 9, 8, TYRE)
            _ellipse(img, cx, 40, 4, 4, (70, 70, 72))
        # fuel tanks strapped to the bed
        _rect(img, 84, 20, 14, 14, (110, 92, 44))
        _rect(img, 84, 20, 14, 3, (140, 118, 56))
        _rect(img, 84, 29, 14, 2, (150, 128, 62))
        _rect(img, 0, 36, 18, 5, dark)
    elif pose == 2:
        # head-on: cab, windscreen, grille
        _rect(img, 26, 8, 52, 30, body)
        _rect(img, 26, 8, 52, 4, dark)
        _rect(img, 32, 12, 40, 10, GLASS)
        _rect(img, 32, 24, 40, 8, dark)
        for x in range(34, 72, 6):
            _rect(img, x, 25, 4, 5, (76, 78, 82))
        _ellipse(img, 38, 22, 4, 4, (240, 232, 200))   # headlights
        _ellipse(img, 66, 22, 4, 4, (240, 232, 200))
        for cx in (36, 68):
            _ellipse(img, cx, 40, 8, 9, TYRE)
            _ellipse(img, cx, 40, 3, 3, (70, 70, 72))
        _rect(img, 20, 36, 12, 5, dark)
        _rect(img, 72, 36, 12, 5, dark)
    elif pose == 4:
        # tailgate view
        _rect(img, 26, 6, 52, 34, body)
        _rect(img, 26, 6, 52, 3, dark)
        _rect(img, 30, 10, 44, 24, CANVAS_DARK)
        for y in range(12, 32, 7):
            _rect(img, 30, y, 44, 2, (52, 50, 38))
        _ellipse(img, 34, 34, 4, 4, (190, 60, 50))
        _ellipse(img, 70, 34, 4, 4, (190, 60, 50))
        for cx in (36, 68):
            _ellipse(img, cx, 42, 8, 8, TYRE)
    elif pose == 1:
        # three-quarter front: foreshortened side + cab face
        _rect(img, 10, 12, 64, 24, body)
        _rect(img, 10, 12, 64, 4, dark)
        _rect(img, 26, 6, 48, 8, CANVAS)
        _rect(img, 26, 6, 48, 2, CANVAS_DARK)
        _rect(img, 8, 8, 26, 30, body)
        _rect(img, 10, 12, 12, 9, GLASS)
        _rect(img, 8, 8, 26, 3, dark)
        for cx in (20, 44, 64):
            _ellipse(img, cx, 40, 8, 8, TYRE)
            _ellipse(img, cx, 40, 3, 3, (70, 70, 72))
        _rect(img, 74, 20, 12, 14, (110, 92, 44))
    else:
        # three-quarter back
        _rect(img, 10, 12, 64, 24, body)
        _rect(img, 10, 12, 64, 4, dark)
        _rect(img, 16, 8, 56, 8, CANVAS)
        _rect(img, 16, 8, 56, 2, CANVAS_DARK)
        _rect(img, 62, 10, 26, 26, body)
        _rect(img, 74, 14, 14, 22, CANVAS_DARK)
        for cx in (24, 50, 72):
            _ellipse(img, cx, 40, 8, 8, TYRE)
        _ellipse(img, 66, 32, 4, 4, (190, 60, 50))
    return _finalise(img, grain=4.0)


def truck_frames():
    return {pose: [_truck(pose)] for pose in range(5)}


# ----------------------------------------------------------------- camera ----
def _camera(state):
    """state: 0 idle, 1 sweeping, 2 alert, 3 destroyed."""
    W, H = 22, 20
    img = _canvas(W, H)
    body = (92, 96, 100) if state != 3 else (56, 58, 60)
    # pole mount
    _rect(img, 9, 8, 4, 12, (70, 74, 78))
    _rect(img, 9, 12, 3, 8, (52, 56, 60))
    # housing
    _rect(img, 3, 2, 16, 8, body)
    _rect(img, 3, 2, 16, 2, (120, 124, 128) if state != 3 else (70, 72, 74))
    if state == 3:
        # broken: dangling lens, sparks suggested by bright frayed wires
        _rect(img, 4, 8, 6, 6, (40, 40, 42))
        _line(img, 8, 8, 12, 14, (200, 200, 210), width=1)
        _line(img, 12, 8, 16, 16, (180, 180, 190), width=1)
        _ellipse(img, 6, 12, 2, 2, (255, 220, 140))
    else:
        # lens barrel facing the viewer
        _rect(img, 4, 3, 8, 6, (30, 32, 36))
        _ellipse(img, 8, 6, 3, 3, (26, 34, 44))
        _ellipse(img, 7, 5, 1.2, 1.2, (150, 190, 210))
        # status LED: green idle, amber sweeping, red alert
        led = (60, 200, 90) if state == 0 else ((230, 180, 60) if state == 1 else RED)
        _ellipse(img, 17, 4, 1.6, 1.6, led)
        if state == 2:
            _ellipse(img, 17, 4, 3.0, 3.0, led, alpha=90)
    return _finalise(img, grain=3.0)


def camera_frames():
    return {state: [_camera(state)] for state in range(4)}


# ------------------------------------------------------------------ props ----
def _barrel():
    W, H = 22, 30
    img = _canvas(W, H)
    _rect(img, 3, 3, 16, 26, (128, 62, 40))
    _shade_rect(img, 3, 3, 5, 26, 0.8)
    _rect(img, 3, 3, 16, 3, (150, 78, 48))
    for y in (8, 15, 22):
        _rect(img, 2, y, 18, 2, (86, 42, 28))
    _ellipse(img, 11, 4, 8, 3, (140, 70, 44))
    _ellipse(img, 11, 4, 5, 2, (96, 48, 30))
    return _finalise(img)


def _crate():
    W, H = 30, 30
    img = _canvas(W, H)
    _rect(img, 1, 4, 28, 25, (122, 88, 50))
    _shade_rect(img, 1, 4, 6, 25, 0.84)
    for y in range(6, 28, 5):
        _rect(img, 1, y, 28, 1, (86, 60, 32))
    _rect(img, 1, 4, 28, 3, (74, 52, 28))
    _rect(img, 1, 26, 28, 3, (74, 52, 28))
    _rect(img, 1, 4, 3, 25, (74, 52, 28))
    _rect(img, 26, 4, 3, 25, (74, 52, 28))
    _rect(img, 12, 12, 6, 8, (100, 96, 70))     # stencil plate
    return _finalise(img)


def _sandbag_stack():
    W, H = 40, 26
    img = _canvas(W, H)
    rows = ((0, 22, 16), (6, 15, 15), (12, 8, 12))
    for yy, hh, width in rows:
        x = (W - width) // 2
        _rect(img, x, yy, width, hh - 3, (124, 116, 88))
        _rect(img, x, yy, width, 3, (140, 132, 100))
        for k in range(x + 8, x + width, 8):
            _rect(img, k, yy, 1, hh - 3, (100, 94, 72))
    return _finalise(img)


def _lamp_post():
    W, H = 16, 78
    img = _canvas(W, H)
    _rect(img, 6, 6, 4, 70, (62, 66, 70))
    _rect(img, 6, 6, 2, 70, (44, 48, 52))
    _rect(img, 4, 2, 10, 5, (58, 62, 66))
    _ellipse(img, 9, 5, 4, 3, LAMP)
    _ellipse(img, 9, 5, 7, 5, LAMP, alpha=70)
    _rect(img, 3, 74, 10, 4, (52, 56, 60))
    return _finalise(img, grain=2.0)


def _generator():
    W, H = 34, 26
    img = _canvas(W, H)
    _rect(img, 2, 6, 30, 18, (72, 76, 80))
    _rect(img, 2, 6, 30, 3, (92, 96, 100))
    for x in range(5, 30, 5):
        _rect(img, x, 8, 3, 14, (56, 60, 64))
    _rect(img, 22, 10, 8, 6, (40, 42, 46))
    _ellipse(img, 26, 13, 2, 2, (180, 70, 60))
    _rect(img, 4, 22, 26, 3, (50, 54, 58))
    return _finalise(img)


def _intel_laptop():
    W, H = 26, 20
    img = _canvas(W, H)
    _rect(img, 2, 12, 22, 7, (64, 66, 70))
    _rect(img, 3, 13, 20, 2, (80, 82, 86))
    # screen, tilted up
    _rect(img, 3, 2, 20, 11, (48, 50, 54))
    _rect(img, 5, 4, 16, 7, (60, 150, 170))
    for y in range(5, 11, 2):
        _rect(img, 6, y, 12, 1, (120, 220, 230))
    _ellipse(img, 13, 14, 4, 2, (60, 150, 170), alpha=90)
    return _finalise(img, grain=2.0)


def _ammo_box():
    W, H = 22, 15
    img = _canvas(W, H)
    _rect(img, 1, 3, 20, 11, (62, 74, 50))
    _rect(img, 1, 3, 20, 2, (80, 94, 66))
    _rect(img, 4, 6, 14, 1, (48, 58, 40))
    _rect(img, 4, 9, 14, 1, (48, 58, 40))
    _rect(img, 8, 5, 6, 5, (170, 160, 90))
    return _finalise(img)


def _medkit():
    W, H = 20, 15
    img = _canvas(W, H)
    _rect(img, 1, 2, 18, 12, (188, 188, 190))
    _rect(img, 1, 2, 18, 2, (210, 210, 212))
    _rect(img, 8, 4, 4, 9, RED)
    _rect(img, 5, 7, 10, 3, RED)
    return _finalise(img)


def _objective_marker():
    """Glowing waypoint diamond, drawn emissive."""
    W, H = 20, 28
    img = _canvas(W, H)
    for i in range(10):
        inset = i
        alpha = 200 - i * 18
        _rect(img, 10 - inset, 3 + i, inset * 2 + 1, 1, AMBER, alpha=max(0, alpha))
        _rect(img, 10 - inset, 24 - i, inset * 2 + 1, 1, AMBER, alpha=max(0, alpha))
    _line(img, 10, 2, 10, 26, (255, 240, 200), width=1, alpha=180)
    return _finalise(img, outline=False, grain=0.0)


def _extraction_marker():
    W, H = 24, 32
    img = _canvas(W, H)
    for i in range(12):
        inset = i
        alpha = 210 - i * 16
        _rect(img, 12 - inset, 4 + i, inset * 2 + 1, 1, (90, 210, 120), alpha=max(0, alpha))
        _rect(img, 12 - inset, 27 - i, inset * 2 + 1, 1, (90, 210, 120), alpha=max(0, alpha))
    _rect(img, 6, 12, 12, 8, (70, 180, 100), alpha=120)
    return _finalise(img, outline=False, grain=0.0)


def _body_bag():
    W, H = 36, 14
    img = _canvas(W, H)
    _ellipse(img, 18, 8, 16, 5, (38, 38, 40))
    _rect(img, 4, 4, 28, 8, (46, 46, 48))
    _rect(img, 4, 4, 28, 2, (60, 60, 62))
    for x in range(10, 32, 8):
        _rect(img, x, 4, 1, 9, (30, 30, 32))
    return _finalise(img)


def _muzzle_flash():
    W, H = 22, 22
    img = _canvas(W, H)
    _ellipse(img, 11, 11, 8, 8, (255, 240, 190), alpha=150)
    _ellipse(img, 11, 11, 5, 5, (255, 250, 225))
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        _line(img, 11, 11, 11 + math.cos(rad) * 9, 11 + math.sin(rad) * 9,
              (255, 226, 150), width=2, alpha=200)
    return _finalise(img, outline=False, grain=0.0)


def _smoke_puff():
    W, H = 24, 24
    img = _canvas(W, H)
    _ellipse(img, 12, 12, 10, 10, (150, 150, 150), alpha=110)
    _ellipse(img, 9, 10, 6, 6, (180, 180, 180), alpha=90)
    _ellipse(img, 15, 14, 5, 5, (120, 120, 120), alpha=80)
    return _finalise(img, outline=False, grain=0.0)


def _fireball():
    W, H = 30, 30
    img = _canvas(W, H)
    _ellipse(img, 15, 15, 14, 14, (200, 90, 30), alpha=200)
    _ellipse(img, 15, 15, 10, 10, (245, 160, 50), alpha=225)
    _ellipse(img, 15, 15, 6, 6, (255, 236, 190))
    return _finalise(img, outline=False, grain=0.0)


def _tower():
    W, H = 60, 96
    img = _canvas(W, H)
    # legs
    for x in (8, 46):
        _rect(img, x, 30, 6, 64, (64, 68, 60))
    _line(img, 11, 34, 49, 92, (56, 60, 54), width=3)
    _line(img, 49, 34, 11, 92, (56, 60, 54), width=3)
    # cabin
    _rect(img, 6, 14, 48, 20, (70, 74, 64))
    _rect(img, 6, 14, 48, 3, (52, 56, 48))
    _rect(img, 10, 18, 40, 9, (48, 66, 72))
    _rect(img, 10, 18, 40, 2, (66, 88, 96))
    # roof + spotlight
    _rect(img, 4, 10, 52, 5, (58, 62, 54))
    _ellipse(img, 30, 8, 6, 4, LAMP)
    _ellipse(img, 30, 8, 9, 6, LAMP, alpha=60)
    return _finalise(img, grain=4.0)


def _helipad():
    W, H = 64, 20
    img = _canvas(W, H)
    _rect(img, 0, 6, 64, 14, (62, 64, 68))
    _rect(img, 0, 6, 64, 2, (78, 80, 84))
    _rect(img, 20, 8, 4, 10, (200, 200, 120))
    _rect(img, 40, 8, 4, 10, (200, 200, 120))
    _rect(img, 20, 12, 24, 3, (200, 200, 120))
    return _finalise(img)


PROP_BUILDERS = {
    "barrel": _barrel,
    "crate": _crate,
    "sandbags": _sandbag_stack,
    "lamp": _lamp_post,
    "generator": _generator,
    "laptop": _intel_laptop,
    "ammo": _ammo_box,
    "medkit": _medkit,
    "waypoint": _objective_marker,
    "extraction": _extraction_marker,
    "bodybag": _body_bag,
    "flash": _muzzle_flash,
    "smoke": _smoke_puff,
    "fireball": _fireball,
    "tower": _tower,
    "helipad": _helipad,
}


class SpriteArt:
    """Builds and caches all billboard art once per run."""

    def __init__(self):
        self.props = {}
        self.soldier = soldier_frames(3, rifle=True, officer=False)
        self.officer = soldier_frames(3, rifle=True, officer=True)
        self.civilian = soldier_frames(3, rifle=False, officer=False)
        self.trucks = truck_frames()
        self.cameras = camera_frames()
        self._build_props()

    def _build_props(self):
        for name, builder in PROP_BUILDERS.items():
            if name in ("flash", "smoke", "fireball", "waypoint", "extraction",
                        "lamp"):
                continue
            art = builder()
            self.props[name] = ([art], [art[:, :, 3] / 255.0])
        # Emissive overlays keep their alpha for additive-ish blending.
        for name in ("flash", "smoke", "fireball", "waypoint", "extraction", "lamp"):
            art = PROP_BUILDERS[name]()
            self.props[name] = ([art], [art[:, :, 3] / 255.0])

    def character(self, kind):
        table = {"soldier": self.soldier, "officer": self.officer,
                 "civilian": self.civilian}.get(kind, self.soldier)
        return table

    @staticmethod
    def to_rgb(frames):
        """Strip alpha into separate arrays for the renderer's fast path."""
        rgb = [np.ascontiguousarray(frame[:, :, 0:3].astype(np.uint8)) for frame in frames]
        alpha = [np.ascontiguousarray(frame[:, :, 3] / 255.0).astype(np.float32) for frame in frames]
        return rgb, alpha


class Sprite:
    """A world-space billboard.

    `views` maps a direction index to a list of frames. `facing` is the object's
    own heading in world radians; the renderer picks the view closest to the
    angle between the object's heading and the viewer.
    """

    __slots__ = ("x", "y", "z_base", "height", "width", "brightness", "emit",
                 "opacity", "tint", "views", "rgb_views", "alpha_views",
                 "view_count", "facing", "frame", "kind", "tag", "entity",
                 "attached", "_active_view", "view_override")

    def __init__(self, x, y, kind="prop", art_frames=None, height=1.0, width=1.0,
                 z_base=0.0, brightness=1.0, emit=0.0, facing=0.0, tag=None):
        self.x = float(x)
        self.y = float(y)
        self.z_base = float(z_base)
        self.height = float(height)
        self.width = float(width)
        self.brightness = float(brightness)
        self.emit = float(emit)
        self.opacity = 1.0
        self.tint = (1.0, 1.0, 1.0)
        self.kind = kind
        self.tag = tag
        self.facing = float(facing)
        self.frame = 0
        self.entity = None
        self.attached = None
        # When set, this view is used instead of the angle-derived one. Cameras
        # and corpses key their art by state, not by viewing direction.
        self.view_override = None
        self.views = art_frames if art_frames is not None else {}
        self._prepare()

    def _prepare(self):
        self.rgb_views = {}
        self.alpha_views = {}
        for view, frames in self.views.items():
            rgb, alpha = SpriteArt.to_rgb(frames)
            self.rgb_views[view] = rgb
            self.alpha_views[view] = alpha
        self.view_count = len(self.views)

    # ---------------------------------------------------------- accessors ----
    def distance_sq(self, cam):
        return dist_sq(self.x, self.y, cam.x, cam.y)

    def select_view(self, cam):
        """Choose the sprite view whose facing best matches the viewer's side."""
        if self.view_override is not None:
            if self.view_override in self.views:
                return self.view_override
        if self.view_count <= 1:
            return next(iter(self.views))
        angle_to_cam = math.atan2(cam.y - self.y, cam.x - self.x)
        rel = normalise_angle(angle_to_cam - self.facing)
        # 5 views cover the circle: front(0), 3/4(+-45), side(+-90),
        # back-3/4(+-135), back(180)
        idx = int(round(rel / (math.pi / 4.0))) % 8
        mapping = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 3, 6: 2, 7: 1}
        view = mapping.get(idx, 0)
        if view not in self.views:
            view = min(self.views, key=lambda k: abs(k - view))
        return view

    def image_array(self):
        view = self._active_view
        frames = self.rgb_views.get(view)
        if not frames:
            return None
        return frames[self.frame % len(frames)]

    def alpha_array(self):
        view = self._active_view
        frames = self.alpha_views.get(view)
        if not frames:
            return None
        return frames[self.frame % len(frames)]

    def set_active_view(self, cam):
        self._active_view = self.select_view(cam)

    # Called by the raycaster before drawing.
    def prepare_for_render(self, cam):
        self.set_active_view(cam)
