"""Small maths and geometry helpers shared across the game."""

import math


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def lerp(a, b, t):
    return a + (b - a) * t


def normalise_angle(angle):
    """Wrap an angle into (-pi, pi]."""
    while angle > math.pi:
        angle -= math.tau
    while angle <= -math.pi:
        angle += math.tau
    return angle


def angle_difference(a, b):
    """Signed shortest rotation from b to a."""
    return normalise_angle(a - b)


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def dist_sq(ax, ay, bx, by):
    dx = ax - bx
    dy = ay - by
    return dx * dx + dy * dy


def move_towards(current, target, max_delta):
    """Step `current` towards `target` by at most `max_delta`."""
    delta = target - current
    if abs(delta) <= max_delta:
        return target
    return current + math.copysign(max_delta, delta)


def rotate_towards(current, target, max_delta):
    """Rotate `current` towards `target` angle by at most `max_delta` radians."""
    delta = angle_difference(target, current)
    if abs(delta) <= max_delta:
        return target
    return current + math.copysign(max_delta, delta)


def ray_aabb(ox, oy, dx, dy, x0, y0, x1, y1):
    """Slab test. Returns entry distance or None."""
    inv_dx = 1.0 / dx if dx != 0.0 else 1e30
    inv_dy = 1.0 / dy if dy != 0.0 else 1e30
    tx0 = (x0 - ox) * inv_dx
    tx1 = (x1 - ox) * inv_dx
    if tx0 > tx1:
        tx0, tx1 = tx1, tx0
    ty0 = (y0 - oy) * inv_dy
    ty1 = (y1 - oy) * inv_dy
    if ty0 > ty1:
        ty0, ty1 = ty1, ty0
    entry = tx0 if tx0 > ty0 else ty0
    exit_ = tx1 if tx1 < ty1 else ty1
    if entry > exit_ or exit_ < 0.0:
        return None
    return entry if entry > 0.0 else 0.0


def segment_blocked(ax, ay, bx, by, blocked_fn, step=0.25):
    """Sample a segment and report whether `blocked_fn(x, y)` ever trips."""
    length = dist(ax, ay, bx, by)
    if length < 1e-6:
        return False
    steps = int(length / step) + 1
    for i in range(1, steps):
        t = i / steps
        if blocked_fn(ax + (bx - ax) * t, ay + (by - ay) * t):
            return True
    return False


def line_of_sight(ax, ay, bx, by, blocked_fn, step=0.3):
    return not segment_blocked(ax, ay, bx, by, blocked_fn, step)


def circle_aabb_overlap(cx, cy, radius, x0, y0, x1, y1):
    nearest_x = clamp(cx, x0, x1)
    nearest_y = clamp(cy, y0, y1)
    dx = cx - nearest_x
    dy = cy - nearest_y
    return dx * dx + dy * dy < radius * radius
