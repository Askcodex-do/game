"""A textured, vectorised raycaster.

Rather than stepping a DDA loop per ray (far too slow in pure Python), every
ray is intersected with *all* grid boundaries at once using numpy. For a 64x64
map that is at most 64+64 candidates per ray, so a frame costs a handful of
array operations instead of thousands of interpreter steps.

Rendering order per frame:
  1. floor + ceiling (per-row projection, vectorised across the row)
  2. walls (per-column intersections, pre-shaded textures from TextureLibrary)
  3. sprites (billboards, depth-tested against the wall z-buffer)
"""

import math

import numpy as np
import pygame

from ..config import (COLUMN_WIDTH, HALF_FOV, MAX_DEPTH, NUM_RAYS,
                      RENDER_H, RENDER_W)
from ..utils import clamp
from .textures import SHADE_LEVELS, TEX_SIZE, TextureLibrary

TAN_HALF_FOV = math.tan(HALF_FOV)
PROJ = (RENDER_W * 0.5) / TAN_HALF_FOV
HORIZON = RENDER_H * 0.5

# Smallest ray parameter we accept, so a player never sees the inside of the
# wall they are standing next to.
EPSILON = 0.02


class Camera:
    """Player view state: position plus vertical pitch offset in pixels."""

    __slots__ = ("x", "y", "angle", "eye_z", "pitch")

    def __init__(self, x=0.0, y=0.0, angle=0.0, eye_z=0.62, pitch=0.0):
        self.x = x
        self.y = y
        self.angle = angle
        self.eye_z = eye_z
        self.pitch = pitch


class Raycaster:
    def __init__(self, textures=None, render_floor=True, low_detail=False):
        self.textures = textures or TextureLibrary()
        self.frame = np.zeros((RENDER_H, RENDER_W, 3), dtype=np.uint8)
        self.z_buffer = np.full(NUM_RAYS, MAX_DEPTH, dtype=np.float32)
        self.render_floor = render_floor
        self.low_detail = low_detail
        # Projection state, recomputed each frame so scoping can magnify cleanly.
        self.view_zoom = 1.0
        self.proj = PROJ
        self.horizon = HORIZON
        self._ray_offsets = None
        self._cos_correct = None
        self._cam_x = np.linspace(-TAN_HALF_FOV, TAN_HALF_FOV, RENDER_W,
                                  dtype=np.float64)
        self._star_grid = None
        self._set_zoom(1.0)
        self._surface = pygame.Surface((RENDER_W, RENDER_H))
        # Filled in by the level: index 0 is unused, ids map to texture names.
        self.tile_textures = ["concrete", "concrete"]

    def _set_zoom(self, zoom):
        """Recompute ray angles and projection for a magnification factor.

        `zoom` shrinks the angular span the rays cover, so the same number of
        columns samples a narrower slice of the world. Wall heights and sprite
        sizes scale with the resulting projection distance, which is exactly the
        behaviour of a magnifying optic.
        """
        zoom = max(0.15, min(1.0, zoom))
        if zoom == self.view_zoom and self._ray_offsets is not None:
            return
        self.view_zoom = zoom
        effective_half = HALF_FOV * zoom
        tan_half = math.tan(effective_half)
        self.proj = (RENDER_W * 0.5) / max(tan_half, 1e-6)
        offsets = -effective_half + (np.arange(NUM_RAYS) + 0.5) * (
            (effective_half * 2.0) / NUM_RAYS)
        self._ray_offsets = offsets
        self._cos_correct = np.cos(offsets).astype(np.float64)
        self._cam_x = np.linspace(-tan_half, tan_half, RENDER_W,
                                  dtype=np.float64)

    def _precompute_rays(self):
        # Each ray's offset from the camera centre, in radians.
        self._set_zoom(1.0)

    # ------------------------------------------------------------ geometry ----
    def _cast_walls(self, cam, grid):
        """Return per-column (distance, texture_u, tile, no_hit, side_darken).

        Every ray is tested against all horizontal and all vertical grid lines
        at once. Each axis is then reduced to its nearest hit, and the two are
        compared to pick the true first wall.
        """
        num_rays = NUM_RAYS
        map_h, map_w = grid.shape

        angles = cam.angle + self._ray_offsets
        dir_x = np.cos(angles)
        dir_y = np.sin(angles)
        dy_pos = dir_y > 0.0
        dx_pos = dir_x > 0.0

        # --- intersections with horizontal grid lines (constant y) ---
        rows = np.arange(0, map_h + 1, dtype=np.float64)          # (R,)
        with np.errstate(divide="ignore", invalid="ignore"):
            t_h = (rows[None, :] - cam.y) / dir_y[:, None]        # (N, R)
        t_h = np.where((t_h > EPSILON) & (t_h < MAX_DEPTH), t_h, np.inf)
        x_h = cam.x + dir_x[:, None] * np.where(np.isfinite(t_h), t_h, 0.0)
        cell_x = np.floor(x_h).astype(np.int32)
        cell_y = np.where(dy_pos[:, None], rows[None, :], rows[None, :] - 1.0).astype(np.int32)
        inside = ((cell_x >= 0) & (cell_x < map_w) &
                  (cell_y >= 0) & (cell_y < map_h))
        tex_h = np.where(inside,
                         grid[np.clip(cell_y, 0, map_h - 1), np.clip(cell_x, 0, map_w - 1)],
                         0)
        t_h = np.where(inside & (tex_h > 0), t_h, np.inf)

        # --- intersections with vertical grid lines (constant x) ---
        cols = np.arange(0, map_w + 1, dtype=np.float64)          # (C,)
        with np.errstate(divide="ignore", invalid="ignore"):
            t_v = (cols[None, :] - cam.x) / dir_x[:, None]        # (N, C)
        t_v = np.where((t_v > EPSILON) & (t_v < MAX_DEPTH), t_v, np.inf)
        y_v = cam.y + dir_y[:, None] * np.where(np.isfinite(t_v), t_v, 0.0)
        cell_yv = np.floor(y_v).astype(np.int32)
        cell_xv = np.where(dx_pos[:, None], cols[None, :], cols[None, :] - 1.0).astype(np.int32)
        inside_v = ((cell_xv >= 0) & (cell_xv < map_w) &
                    (cell_yv >= 0) & (cell_yv < map_h))
        tex_v = np.where(inside_v,
                         grid[np.clip(cell_yv, 0, map_h - 1), np.clip(cell_xv, 0, map_w - 1)],
                         0)
        t_v = np.where(inside_v & (tex_v > 0), t_v, np.inf)

        # --- nearest hit on each axis, then nearest of the two ---
        hit_h = t_h.min(axis=1)
        hit_v = t_v.min(axis=1)
        arg_h = t_h.argmin(axis=1)
        arg_v = t_v.argmin(axis=1)

        use_h = hit_h <= hit_v
        t_hit = np.where(use_h, hit_h, hit_v)
        no_hit = ~np.isfinite(t_hit)
        t_hit = np.where(no_hit, MAX_DEPTH, t_hit)

        tex_h_pick = tex_h[np.arange(num_rays), arg_h]
        tex_v_pick = tex_v[np.arange(num_rays), arg_v]
        tile = np.where(use_h, tex_h_pick, tex_v_pick).astype(np.int32)

        # Perpendicular distance removes the fisheye bulge.
        perp = np.maximum(t_hit * self._cos_correct, 1e-4)

        # Texture coordinate along the wall face.
        wall_x = np.where(use_h,
                          cam.x + dir_x * t_hit,
                          cam.y + dir_y * t_hit)
        frac = wall_x - np.floor(wall_x)
        # Flip so textures are not mirrored when viewed from the other side.
        flip = np.where(use_h, ~dy_pos, dx_pos)
        u = np.where(flip, 1.0 - frac, frac)
        tex_u = np.clip((u * TEX_SIZE).astype(np.int32), 0, TEX_SIZE - 1)

        # Horizontal faces are lit slightly differently from vertical ones.
        side_darken = np.where(use_h, 0, 2)
        return perp, tex_u, tile, no_hit, side_darken

    # ---------------------------------------------------------- floor/sky ----
    def _render_flat(self, cam, grid, floor_name, ceil_name, floor_col):
        """Per-row floor and sky/ceiling casting.

        For a given screen row the world distance is constant, so one row is a
        single vectorised computation across all 480 columns. Rows above the
        horizon show the night sky (this is an outdoor depot, so a roof would
        look wrong); rows below show the ground texture.
        """
        frame = self.frame
        horizon = HORIZON + cam.pitch
        proj = self.proj
        floor_arr = pygame.surfarray.array3d(self.textures.get(floor_name))
        floor_arr = np.transpose(floor_arr, (1, 0, 2)).astype(np.uint8)

        cos_a = math.cos(cam.angle)
        sin_a = math.sin(cam.angle)
        # Camera-space x direction for every column, then rotated into world.
        dir_x = cos_a - self._cam_x * sin_a
        dir_y = sin_a + self._cam_x * cos_a

        step = 2 if self.low_detail else 1
        eye_z = cam.eye_z

        y_top = 0
        y_bot = RENDER_H

        for y in range(y_top, y_bot, step):
            dy = y - horizon
            rows = slice(y, min(y + step, RENDER_H))
            if dy < -0.5:
                # Sky: a vertical gradient from deep blue at the top to a
                # lighter haze at the horizon, so the world reads as a night
                # operation rather than a black void.
                frame[rows, :, :] = self._sky_colour(y)
                continue
            if dy <= 0.5:
                # Exactly on the horizon: one row of haze.
                frame[rows, :, :] = self._sky_colour(RENDER_H)
                continue
            row_dist = min(proj * eye_z / dy, MAX_DEPTH * 2)
            wx = cam.x + dir_x * row_dist
            wy = cam.y + dir_y * row_dist
            tx = np.clip((wx % 1.0 * TEX_SIZE).astype(np.int32), 0, TEX_SIZE - 1)
            ty = np.clip((wy % 1.0 * TEX_SIZE).astype(np.int32), 0, TEX_SIZE - 1)
            colour = floor_arr[ty, tx] * self._flat_shade(row_dist, ceil=False)
            frame[rows, :, :] = colour

    def _sky_colour(self, y):
        """Night-sky gradient sampled by screen row, including a star field.

        Stars are baked into a per-row lookup the first time each row is drawn,
        so the cost is paid once per frame rather than per pixel.
        """
        t = clamp(y / max(RENDER_H, 1), 0.0, 1.0)
        # Top: near-black navy. Horizon: a dim haze from the depot lamps.
        top = np.array([7.0, 9.0, 16.0])
        mid = np.array([16.0, 20.0, 34.0])
        horizon_haze = np.array([30.0, 30.0, 38.0])
        if t < 0.6:
            k = t / 0.6
            row = top + (mid - top) * k
        else:
            k = (t - 0.6) / 0.4
            row = mid + (horizon_haze - mid) * k
        # Stars: a stable pseudo-random pattern, only in the upper sky.
        if t < 0.62:
            grid = self._star_grid
            if grid is None:
                grid = self._build_star_grid()
            row = row + grid[y]
        return np.clip(row, 0, 255).astype(np.uint8)

    def _build_star_grid(self):
        """One star-field row table, generated once and cached."""
        rng = np.random.default_rng(0x5A17)
        grid = np.zeros((RENDER_H, RENDER_W, 3), dtype=np.float64)
        star_count = 420
        xs = rng.integers(0, RENDER_W, star_count)
        ys = rng.integers(0, int(RENDER_H * 0.6), star_count)
        brightness = rng.uniform(18.0, 95.0, star_count)
        for x, y, b in zip(xs, ys, brightness):
            grid[y, x] += b
            if x + 1 < RENDER_W:
                grid[y, x + 1] += b * 0.35
            if y + 1 < RENDER_H:
                grid[y + 1, x] += b * 0.35
        self._star_grid = grid
        return grid

    @staticmethod
    def _flat_shade(distance, ceil=False):
        """Distance-based dimming for the ground plane, as a float multiplier.

        A night scene still needs to be readable, so ambient sits fairly high
        and distance fog does the work of conveying depth.
        """
        fog = 1.0 - min(0.72, distance / (MAX_DEPTH * 1.25))
        base = 0.78 + fog * 0.42
        if ceil:
            base *= 0.72
        return base

    # --------------------------------------------------------------- walls ----
    def _render_walls(self, cam, perp, tex_u, tile, no_hit, side_darken):
        horizon = HORIZON + cam.pitch
        eye_z = cam.eye_z
        proj = self.proj

        heights = proj / perp
        wall_top = horizon - heights * (1.0 - eye_z)
        wall_bot = horizon + heights * eye_z

        # Texture lookup tables per tile id are resolved by the level, which
        # sets `self.tile_textures` to a list of texture names.
        names = self.tile_textures

        # Group columns by tile so we can use one vectorised slice per texture.
        for tile_id in np.unique(tile):
            if tile_id <= 0:
                continue
            mask = (tile == tile_id) & (~no_hit)
            if not mask.any():
                continue
            name = names[tile_id] if tile_id < len(names) else names[-1]
            cols = np.nonzero(mask)[0]
            self._draw_textured_columns(
                name, cols, tex_u[cols], perp[cols],
                wall_top[cols], wall_bot[cols], side_darken[cols],
            )

    def _draw_textured_columns(self, name, cols, tex_u, perp,
                               wall_top, wall_bot, side_darken):
        """Draw pre-shaded 1px-wide texture strips for a set of columns."""
        frame = self.frame
        shades = self.textures.shaded.get(name)
        if shades is None:
            shades = self.textures.shaded.get("concrete")

        # Bucket columns by shading level so each level's strip is fetched once.
        levels = self.textures.shade_level_for_distance(perp, side_darken)
        levels = np.clip(levels, 0, SHADE_LEVELS - 1)

        for level in np.unique(levels):
            sub = cols[levels == level]
            if sub.size == 0:
                continue
            strip = shades[int(level)]
            strip_arr = pygame.surfarray.array3d(strip)
            strip_arr = np.transpose(strip_arr, (1, 0, 2))

            # Precompute the vertical texture index for every (column, row)
            # interval in this bucket using a shared row grid.
            for i, col in enumerate(sub):
                top = wall_top[i]
                bot = wall_bot[i]
                start = int(max(0, math.floor(top)))
                end = int(min(RENDER_H, math.ceil(bot)))
                if end <= start:
                    continue
                tex_x = int(tex_u[i])
                row_tex = (np.arange(start, end) - top) / max(bot - top, 1e-6)
                tex_y = np.clip((row_tex * TEX_SIZE).astype(np.int32), 0, TEX_SIZE - 1)
                x0 = col * COLUMN_WIDTH
                x1 = min(RENDER_W, x0 + COLUMN_WIDTH)
                frame[start:end, x0:x1, :] = strip_arr[tex_y, tex_x][:, None, :]

    # ------------------------------------------------------------- sprites ----
    def _render_sprites(self, cam, sprites):
        """Billboard sprites, depth tested per column against the z-buffer."""
        if not sprites:
            return
        frame = self.frame
        horizon = HORIZON + cam.pitch
        proj = self.proj
        cos_a = math.cos(cam.angle)
        sin_a = math.sin(cam.angle)

        # Sort far to near so nearer sprites overwrite correctly.
        ordered = sorted(sprites, key=lambda s: -s.distance_sq(cam))
        for sprite in ordered:
            sprite.prepare_for_render(cam)
            dx = sprite.x - cam.x
            dy = sprite.y - cam.y
            # Transform into camera space.
            depth = dx * cos_a + dy * sin_a
            if depth <= 0.12 or depth > MAX_DEPTH:
                continue
            lateral = -dx * sin_a + dy * cos_a

            screen_x = (lateral / depth) * proj + RENDER_W * 0.5
            height = (sprite.height * proj) / depth
            width = (sprite.width * proj) / depth
            if height < 1 or width < 1:
                continue

            bottom = horizon + ((cam.eye_z - sprite.z_base) * proj) / depth
            top = bottom - height

            x0 = int(screen_x - width * 0.5)
            x1 = int(screen_x + width * 0.5)
            y0 = int(top)
            y1 = int(bottom)
            if x1 <= 0 or x0 >= RENDER_W or y1 <= 0 or y0 >= RENDER_H:
                continue

            art = sprite.image_array()
            if art is None:
                continue
            art_h, art_w = art.shape[0], art.shape[1]
            alpha = sprite.alpha_array()

            cx0 = max(0, x0)
            cx1 = min(RENDER_W, x1)
            cy0 = max(0, y0)
            cy1 = min(RENDER_H, y1)
            if cx1 <= cx0 or cy1 <= cy0:
                continue

            # Map destination pixels back into the sprite's own pixel grid.
            src_x = ((np.arange(cx0, cx1) - x0 + 0.5) / max(x1 - x0, 1) * art_w).astype(np.int32)
            src_y = ((np.arange(cy0, cy1) - y0 + 0.5) / max(y1 - y0, 1) * art_h).astype(np.int32)
            src_x = np.clip(src_x, 0, art_w - 1)
            src_y = np.clip(src_y, 0, art_h - 1)

            patch = art[src_y][:, src_x]
            # Depth test: compare against the wall distance for those columns.
            col_start = cx0 // COLUMN_WIDTH
            col_end = min(NUM_RAYS, (cx1 + COLUMN_WIDTH - 1) // COLUMN_WIDTH)
            if col_end <= col_start:
                continue
            zbuf = self._repeat_columns(self.z_buffer[col_start:col_end], cx0, cx1)
            depth_ok = (depth + 0.02) < zbuf[None, :]

            if alpha is not None:
                a = alpha[src_y][:, src_x] * sprite.opacity
                mask = (a > 0.02) & depth_ok
                if not mask.any():
                    continue
                blend = a[..., None]
                dst = frame[cy0:cy1, cx0:cx1, :].astype(np.float32)
                lit = self._apply_lighting(patch, depth, sprite)
                frame[cy0:cy1, cx0:cx1, :] = np.where(
                    mask[..., None],
                    dst * (1.0 - blend) + lit * blend,
                    dst,
                ).astype(np.uint8)
            else:
                mask = depth_ok
                if not mask.any():
                    continue
                lit = self._apply_lighting(patch, depth, sprite)
                region = frame[cy0:cy1, cx0:cx1, :]
                region[:] = np.where(mask[..., None], lit, region)

    @staticmethod
    def _repeat_columns(cols, x0, x1):
        """Expand a per-ray column array to a per-pixel-wide array."""
        idx = np.arange(x0, x1)
        ray_idx = np.clip(idx // COLUMN_WIDTH - (x0 // COLUMN_WIDTH), 0, cols.size - 1)
        return cols[ray_idx]

    @staticmethod
    def _apply_lighting(patch, depth, sprite):
        fog = 1.0 - min(0.8, depth / (MAX_DEPTH * 1.1))
        factor = (0.42 + fog * 0.58) * sprite.brightness
        lit = patch.astype(np.float32) * factor
        if sprite.emit > 0.0:
            # Emissive sprites (lamps, muzzle flashes) resist the distance fog.
            lit = np.maximum(lit, patch.astype(np.float32) * sprite.emit)
        return np.clip(lit, 0, 255)

    # ------------------------------------------------------------- top level --
    def render(self, cam, grid, floor_name, ceil_name, sprites, zoom=None):
        """Render a complete frame into `self.frame`.

        `zoom` < 1.0 magnifies the view (used by the sniper scope).
        """
        if zoom is not None:
            self._set_zoom(zoom)
        if self.render_floor:
            self._render_flat(cam, grid, floor_name, ceil_name, 0)
        else:
            self.frame[:] = np.array([24, 26, 34], dtype=np.uint8)

        perp, tex_u, tile, no_hit, hit_h = self._cast_walls(cam, grid)
        self.z_buffer[:] = perp
        self._render_walls(cam, perp, tex_u, tile, no_hit, hit_h)
        self._render_sprites(cam, sprites)

    def present(self, target, scale):
        """Copy the frame into a pygame surface and scale to the window."""
        pygame.surfarray.blit_array(self._surface, np.transpose(self.frame, (1, 0, 2)))
        if scale == 1:
            target.blit(self._surface, (0, 0))
        else:
            pygame.transform.scale(self._surface, target.get_size(), target)
