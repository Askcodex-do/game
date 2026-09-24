"""Procedural wall/floor textures.

All artwork is generated at import time from seeded noise, so the repository
ships no image files and the memory footprint is a few hundred kilobytes.
Textures are kept at 64x64 and pre-shaded into a small number of brightness
levels, which lets the raycaster pick a ready-darkened surface per column
instead of alpha-blending every frame.
"""

import numpy as np
import pygame

TEX_SIZE = 64
SHADE_LEVELS = 14

RNG = np.random.default_rng(0xBADC0DE)

# Base colours (RGB) used by the tint helper.
NIGHT_TINT = np.array([0.42, 0.48, 0.62])      # cool blue night cast
LAMP_TINT = np.array([1.18, 1.06, 0.82])       # warm sodium light cast


def _base(rgb, size=TEX_SIZE):
    return np.tile(np.array(rgb, dtype=np.float64), (size, size, 1))


def _noise(amount, size=TEX_SIZE):
    return RNG.uniform(-amount, amount, (size, size, 1))


def _speckle(img, count, radius, colour, bright=0.0):
    size = img.shape[0]
    for _ in range(count):
        cx = RNG.integers(0, size)
        cy = RNG.integers(0, size)
        r = max(1, int(RNG.integers(1, radius + 1)))
        x0, x1 = max(0, cx - r), min(size, cx + r)
        y0, y1 = max(0, cy - r), min(size, cy + r)
        patch = img[y0:y1, x0:x1]
        delta = np.array(colour, dtype=np.float64)
        patch += delta * (1.0 + bright)
    return img


def _vignette(img, strength=0.18):
    size = img.shape[0]
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1)
    edge = np.maximum(np.abs(xx - 0.5), np.abs(yy - 0.5)) * 2.0
    img *= (1.0 - strength * edge ** 2)[..., None]
    return img


def _lines(img, spacing, colour, axis=0, width=1, strength=1.0):
    size = img.shape[0]
    delta = np.array(colour, dtype=np.float64) * strength
    for i in range(0, size, spacing):
        if axis == 0:
            img[i:i + width, :, :] += delta
        else:
            img[:, i:i + width, :] += delta
    return img


# --------------------------------------------------------------- wall types --
def tex_concrete():
    img = _base((104, 106, 110)) + _noise(14)
    img = _speckle(img, 90, 2, (18, 18, 20), bright=0.4)
    img = _speckle(img, 40, 1, (34, 34, 36), bright=0.2)
    img = _lines(img, 32, (-16, -16, -16), axis=0, width=1)
    img = _lines(img, 64, (-10, -10, -10), axis=1, width=1)
    # damp streaks running down the wall
    for _ in range(6):
        x = int(RNG.integers(0, TEX_SIZE))
        w = int(RNG.integers(1, 3))
        length = int(RNG.integers(18, 56))
        img[0:length, x:x + w] *= 0.86
    return _vignette(img)


def tex_brick():
    img = _base((120, 62, 50)) + _noise(12)
    brick_w, brick_h = 16, 8
    for row in range(0, TEX_SIZE, brick_h):
        offset = (row // brick_h % 2) * (brick_w // 2)
        for col in range(-brick_w, TEX_SIZE, brick_w):
            x = col + offset
            x0, x1 = max(0, x), min(TEX_SIZE, x + brick_w - 1)
            y0, y1 = row, min(TEX_SIZE, row + brick_h - 1)
            if x1 <= x0 or y1 <= y0:
                continue
            tint = RNG.uniform(0.82, 1.14)
            img[y0:y1, x0:x1] *= tint
    # mortar joints
    img = _lines(img, brick_h, (52, 50, 48), axis=0, width=1, strength=0.9)
    for row in range(0, TEX_SIZE, brick_h):
        offset = (row // brick_h % 2) * (brick_w // 2)
        for col in range(-brick_w, TEX_SIZE, brick_w):
            x = (col + offset) % TEX_SIZE
            img[row:row + brick_h, x] = np.array([58, 56, 54])
    return _vignette(img, 0.14)


def tex_metal():
    img = _base((92, 96, 100)) + _noise(6)
    img = _lines(img, 2, (-6, -6, -6), axis=1, width=1, strength=1.0)
    img = _lines(img, 2, (5, 5, 5), axis=1, width=1, strength=1.0)
    # rivets
    for gy in range(8, TEX_SIZE, 20):
        for gx in range(8, TEX_SIZE, 20):
            img[gy - 1:gy + 2, gx - 1:gx + 2] += np.array([26, 26, 28])
            img[gy, gx] += np.array([40, 40, 44])
    return _vignette(img, 0.12)


def tex_crate():
    img = _base((122, 88, 50)) + _noise(10)
    # planks
    for i in range(0, TEX_SIZE, 10):
        img[i:i + 1, :] *= 0.78
        img[i + 1:i + 2, :] *= 1.06
    for _ in range(30):
        x0 = int(RNG.integers(0, TEX_SIZE))
        y0 = int(RNG.integers(0, TEX_SIZE))
        img[y0:y0 + int(RNG.integers(1, 3)), x0:x0 + int(RNG.integers(2, 6))] *= 0.9
    frame = np.array([74, 52, 28])
    img[0:3, :] = frame
    img[-3:, :] = frame
    img[:, 0:3] = frame
    img[:, -3:] = frame
    img = _lines(img, 32, (10, 8, 4), axis=1, width=2)
    return _vignette(img, 0.16)


def tex_sandbag():
    img = _base((124, 116, 88)) + _noise(12)
    bag_w, bag_h = 16, 8
    for row in range(0, TEX_SIZE, bag_h):
        offset = (row // bag_h % 2) * (bag_w // 2)
        for col in range(-bag_w, TEX_SIZE, bag_w):
            x = col + offset
            yy, xx = np.mgrid[0:bag_h, 0:bag_w]
            mask = ((xx - bag_w / 2) / (bag_w / 2)) ** 2 + ((yy - bag_h / 2) / (bag_h / 2)) ** 2 < 1.0
            x0, x1 = max(0, x), min(TEX_SIZE, x + bag_w)
            y0, y1 = row, min(TEX_SIZE, row + bag_h)
            if x1 <= x0 or y1 <= y0:
                continue
            sub = img[y0:y1, x0:x1]
            m = mask[:y1 - y0, :x1 - x0]
            sub[m] *= RNG.uniform(0.86, 1.12)
            sub[~m] *= 0.62
    return _vignette(img, 0.18)


def tex_fence():
    """Chain-link fence: alpha comes from a separate mask, colour is the wire."""
    img = _base((150, 152, 156))
    alpha = np.zeros((TEX_SIZE, TEX_SIZE), dtype=np.float64)
    # diamond mesh
    for i in range(-TEX_SIZE, TEX_SIZE * 2, 8):
        for j in range(-TEX_SIZE, TEX_SIZE * 2, 8):
            yy, xx = np.mgrid[0:TEX_SIZE, 0:TEX_SIZE]
            d1 = np.abs((xx + yy) - (i + j))
            d2 = np.abs((xx - yy) - (i - j))
            mask = (d1 < 1.0) | (d2 < 1.0)
            alpha[mask] = 1.0
    img = img * (1.0 + _noise(0.1))
    return img, alpha


def tex_fence_solid():
    """Opaque chain-link fence wall, so fence lines block movement and sight."""
    img = _base((140, 142, 146))
    alpha = np.zeros((TEX_SIZE, TEX_SIZE))
    for offset in range(-TEX_SIZE, TEX_SIZE * 2, 8):
        yy, xx = np.mgrid[0:TEX_SIZE, 0:TEX_SIZE]
        wire = (np.abs((xx + yy) - offset) < 1.2) | (np.abs((xx - yy) - offset) < 1.2)
        alpha[wire] = 1.0
    img = img * (1.0 + _noise(0.08))
    img = img * alpha[..., None] + (26, 30, 36) * (1.0 - alpha[..., None])
    # posts every 16 pixels
    img[:, 0:2] += np.array([10, 10, 10])
    img[0:2, :] += np.array([14, 14, 14])
    return img


def tex_painted_wall():
    img = _base((64, 78, 62)) + _noise(5)
    img = _lines(img, 24, (-12, -10, -10), axis=0, width=1)
    img = _speckle(img, 30, 2, (-14, -12, -12), bright=0.6)
    # scuffs near the floor line
    img[-12:, :] *= np.linspace(1.0, 0.72, 12)[:, None, None]
    return _vignette(img, 0.14)


def tex_door():
    img = _base((86, 92, 98)) + _noise(6)
    img[4:60, 6:58] *= 1.06
    frame = np.array([58, 62, 66])
    img[2:5, :] = frame
    img[-5:-2, :] = frame
    img[:, 2:5] = frame
    img[:, -5:-2] = frame
    for y in range(10, 56, 8):
        img[y:y + 1, 8:56] *= 0.88
    # handle
    img[30:34, 50:54] += np.array([80, 78, 70])
    return _vignette(img, 0.12)


def tex_tent():
    img = _base((92, 88, 66)) + _noise(9)
    for i in range(0, TEX_SIZE, 8):
        img[i:i + 1, :] *= 0.9
    img = _lines(img, 16, (14, 14, 10), axis=1, width=1)
    return _vignette(img, 0.2)


def tex_container():
    img = _base((58, 76, 88)) + _noise(6)
    for i in range(0, TEX_SIZE, 6):
        img[:, i:i + 1] *= 0.86
        img[:, i + 1:i + 2] *= 1.08
    img[0:4, :] = np.array([40, 54, 64])
    img[-4:, :] = np.array([40, 54, 64])
    return _vignette(img, 0.14)


def tex_truck_side():
    img = _base((52, 66, 46)) + _noise(5)
    img[20:56, 6:58] = _base((60, 74, 52))[20:56, 6:58] + _noise(4)[20:56, 6:58]
    img = _lines(img, 10, (-8, -8, -6), axis=0, width=1, strength=0.7)
    img[26:40, 12:20] += np.array([-14, -16, -12])
    img[0:6, :] *= 0.82
    return _vignette(img, 0.16)


def tex_barrel():
    img = _base((128, 62, 40)) + _noise(7)
    for i in range(0, TEX_SIZE, 6):
        img[i:i + 1, :] *= 0.9
    img = _lines(img, 16, (-22, -12, -8), axis=0, width=2)
    img = _speckle(img, 26, 2, (-30, -16, -10), bright=0.7)
    return _vignette(img, 0.18)


# ------------------------------------------------------------- floors/ceils --
def tex_floor_concrete():
    img = _base((72, 74, 78)) + _noise(10)
    img = _lines(img, 32, (-14, -14, -14), axis=0, width=1)
    img = _lines(img, 16, (-8, -8, -8), axis=1, width=1)
    img = _speckle(img, 60, 2, (12, 12, 12), bright=0.5)
    return img


def tex_floor_gravel():
    img = _base((78, 74, 66)) + _noise(22)
    img = _speckle(img, 120, 2, (20, 18, 14), bright=0.9)
    img = _speckle(img, 120, 2, (-20, -18, -14), bright=0.4)
    return img


def tex_floor_metal():
    img = _base((70, 74, 78)) + _noise(5)
    # tread plate diamonds
    for gy in range(0, TEX_SIZE, 12):
        for gx in range(0, TEX_SIZE, 12):
            img[gy:gy + 4, gx:gx + 2] += np.array([16, 16, 18])
            img[gy + 6:gy + 10, gx + 6:gx + 8] += np.array([16, 16, 18])
    img = _lines(img, 16, (-8, -8, -8), axis=0, width=1)
    return img


def tex_ceiling():
    img = _base((46, 48, 54)) + _noise(6)
    img = _lines(img, 24, (-10, -10, -10), axis=1, width=1)
    img = _speckle(img, 22, 3, (-10, -10, -10), bright=0.5)
    return img


# ----------------------------------------------------------------- registry --
def _to_surface(rgb):
    arr = np.clip(rgb, 0, 255).astype(np.uint8)
    surface = pygame.Surface((arr.shape[1], arr.shape[0]))
    # pygame expects an (w, h, 3) array when using surfarray.blit_array.
    pygame.surfarray.blit_array(surface, np.transpose(arr, (1, 0, 2)))
    return surface


def _make_shaded(builders):
    """Build solid textures and their pre-darkened column cache."""
    solid = {}
    walls = {}
    for name, builder in builders.items():
        rgb = builder()
        surface = _to_surface(rgb)
        solid[name] = surface
        shades = []
        for level in range(SHADE_LEVELS):
            factor = 1.0 - level / (SHADE_LEVELS - 1) * 0.74
            tinted = rgb * factor
            # Fog/night cast grows as the level darkens.
            mix = level / (SHADE_LEVELS - 1)
            tinted = tinted * (1.0 - mix * 0.26) + (NIGHT_TINT * 32.0) * (mix * 0.26)
            shades.append(_to_surface(tinted))
        walls[name] = shades
    return solid, walls


class TextureLibrary:
    """Holds every texture, its shaded variants and the transparent overlays."""

    def __init__(self):
        self.solid = {}
        self.shaded = {}
        self.alpha = {}
        self._build()

    def _build(self):
        wall_builders = {
            "concrete": tex_concrete,
            "brick": tex_brick,
            "metal": tex_metal,
            "crate": tex_crate,
            "sandbag": tex_sandbag,
            "fence": tex_fence_solid,
            "painted": tex_painted_wall,
            "door": tex_door,
            "tent": tex_tent,
            "container": tex_container,
            "truck": tex_truck_side,
            "barrel": tex_barrel,
        }
        self.solid, self.shaded = _make_shaded(wall_builders)

        floor_builders = {
            "floor_concrete": tex_floor_concrete,
            "floor_gravel": tex_floor_gravel,
            "floor_metal": tex_floor_metal,
            "ceiling": tex_ceiling,
        }
        for name, builder in floor_builders.items():
            self.solid[name] = _to_surface(builder())

        # Transparent overlay (fence) with per-pixel alpha.
        fence_rgb, fence_alpha = tex_fence()
        fence = _to_surface(fence_rgb).convert_alpha()
        alpha_arr = np.clip(fence_alpha * 255.0, 0, 255).astype(np.uint8)
        pygame.surfarray.pixels_alpha(fence)[:] = np.transpose(alpha_arr)
        self.alpha["fence"] = fence

    def get(self, name):
        return self.solid[name]

    def get_shaded(self, name, level):
        shades = self.shaded.get(name)
        if shades is None:
            return self.solid[name]
        return shades[max(0, min(SHADE_LEVELS - 1, int(level)))]

    @staticmethod
    def shade_level_for_distance(distance, side_darken=0):
        """Map world distance to a pre-shaded brightness level.

        Accepts either a scalar or a numpy array so callers can shade a whole
        batch of columns at once.
        """
        level = (np.asarray(distance) / 4.2).astype(np.int32) + side_darken
        if np.ndim(level) == 0:
            return max(0, min(SHADE_LEVELS - 1, int(level)))
        return np.clip(level, 0, SHADE_LEVELS - 1)
