"""Heads-up display: crosshair, health, ammo, minimap, objectives, messages.

Everything is drawn with pygame primitives onto the scaled window surface, so
the HUD stays crisp regardless of the internal render resolution. Layout is
data-driven from `config` so the whole thing scales with the window size.
"""

import math

import pygame

from ..config import (C_AMBER, C_CYAN, C_GREEN, C_GREY, C_RED,
                      C_WHITE, WINDOW_H, WINDOW_W)
from ..utils import clamp

FONT_CACHE = {}


def get_font(size, bold=False):
    key = (size, bold)
    font = FONT_CACHE.get(key)
    if font is None:
        font = pygame.font.SysFont("consolas,couriernew,monospace", size, bold=bold)
        FONT_CACHE[key] = font
    return font


class HUD:
    """Draws every on-screen overlay element.

    The HUD is told about the world through a plain dict each frame, which
    keeps it decoupled from the game objects.
    """

    def __init__(self, width=WINDOW_W, height=WINDOW_H):
        self.width = width
        self.height = height
        self.font_small = get_font(13)
        self.font_med = get_font(16)
        self.font_big = get_font(24, bold=True)
        self.font_huge = get_font(46, bold=True)
        self.message_queue = []
        self.current_message = None
        self.message_timer = 0.0
        self.objective_toast = None
        self.objective_toast_timer = 0.0
        self.hit_marker_timer = 0.0
        self.kill_feed = []
        self.scanline_offset = 0.0

    # ------------------------------------------------------------- messages --
    def push_message(self, text, duration=3.5, colour=C_WHITE):
        self.message_queue.append((text, duration, colour))

    def show_objective(self, text, duration=4.0):
        self.objective_toast = text
        self.objective_toast_timer = duration

    def notify_hit(self):
        self.hit_marker_timer = 0.22

    def notify_kill(self, name):
        self.kill_feed.append([name, 3.0])
        if len(self.kill_feed) > 4:
            self.kill_feed.pop(0)

    def update(self, dt):
        self.hit_marker_timer = max(0.0, self.hit_marker_timer - dt)
        self.scanline_offset = (self.scanline_offset + dt * 30.0) % 4.0
        for entry in self.kill_feed:
            entry[1] -= dt
        self.kill_feed = [e for e in self.kill_feed if e[1] > 0.0]

        if self.objective_toast_timer > 0.0:
            self.objective_toast_timer = max(0.0, self.objective_toast_timer - dt)
            if self.objective_toast_timer == 0.0:
                self.objective_toast = None

        if self.current_message is None and self.message_queue:
            text, duration, colour = self.message_queue.pop(0)
            self.current_message = (text, colour)
            self.message_timer = duration
        elif self.current_message is not None:
            self.message_timer -= dt
            if self.message_timer <= 0.0:
                self.current_message = None

    # ----------------------------------------------------------------- draw --
    def draw(self, surface, state):
        """Render the whole HUD. `state` carries the per-frame game snapshot."""
        self._draw_vignette(surface, state)
        self._draw_crosshair(surface, state)
        self._draw_bottom_bar(surface, state)
        self._draw_objectives(surface, state)
        self._draw_minimap(surface, state)
        self._draw_messages(surface, state)
        self._draw_alert_banner(surface, state)
        self._draw_scope(surface, state)
        if state.get("show_debug"):
            self._draw_debug(surface, state)

    def _draw_vignette(self, surface, state):
        # Red pulse when hurt, amber flicker while alarm is active.
        damage = state.get("damage_flash", 0.0)
        if damage > 0.01:
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            alpha = int(clamp(damage, 0.0, 1.0) * 130)
            pygame.draw.rect(overlay, (150, 20, 20, alpha), overlay.get_rect())
            surface.blit(overlay, (0, 0))
        if state.get("alarm_active"):
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            pulse = 40 + int(30 * (0.5 + 0.5 * math.sin(state.get("time", 0.0) * 6.0)))
            pygame.draw.rect(overlay, (170, 40, 30, pulse), overlay.get_rect())
            surface.blit(overlay, (0, 0))

    def _draw_crosshair(self, surface, state):
        cx = self.width // 2
        cy = self.height // 2
        if state.get("scoped", 0.0) > 0.5:
            return
        spread = state.get("crosshair_spread", 6.0)
        gap = int(2 + spread)
        length = 7
        colour = C_WHITE if not state.get("alarm_active") else (240, 190, 190)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            x0 = cx + dx * gap
            y0 = cy + dy * gap
            x1 = cx + dx * (gap + length)
            y1 = cy + dy * (gap + length)
            pygame.draw.line(surface, colour, (x0, y0), (x1, y1), 2)
        pygame.draw.circle(surface, colour, (cx, cy), 1)
        if self.hit_marker_timer > 0.0:
            for angle in (45, 135, 225, 315):
                rad = math.radians(angle)
                x0 = cx + math.cos(rad) * 6
                y0 = cy + math.sin(rad) * 6
                x1 = cx + math.cos(rad) * 12
                y1 = cy + math.sin(rad) * 12
                pygame.draw.line(surface, C_RED, (x0, y0), (x1, y1), 2)

    def _draw_bottom_bar(self, surface, state):
        bar_h = 62
        top = self.height - bar_h
        panel = pygame.Surface((self.width, bar_h), pygame.SRCALPHA)
        panel.fill((8, 10, 14, 190))
        surface.blit(panel, (0, top))

        # ---- health ----
        health = clamp(state.get("health", 100.0), 0.0, 100.0)
        armor = clamp(state.get("armor", 0.0), 0.0, 100.0)
        self._bar(surface, 18, top + 12, 172, 14, health / 100.0,
                  (60, 190, 80), "HEALTH", f"{int(health)}")
        self._bar(surface, 18, top + 34, 172, 10, armor / 100.0,
                  (80, 150, 220), "ARMOR", f"{int(armor)}")

        # ---- weapon + ammo ----
        weapon_name = state.get("weapon_name", "-")
        mag = state.get("mag", 0)
        reserve = state.get("reserve", 0)
        melee = state.get("melee", False)
        text = self.font_med.render(weapon_name, True, C_WHITE)
        surface.blit(text, (250, top + 12))
        if melee:
            ammo_text = "--"
        elif reserve < 0:
            ammo_text = f"{mag}"
        else:
            ammo_text = f"{mag} / {reserve}"
            if mag == 0 and reserve == 0:
                ammo_text = "EMPTY"
        colour = C_RED if (mag == 0 and not melee) else C_WHITE
        ammo = self.font_big.render(ammo_text, True, colour)
        surface.blit(ammo, (250, top + 32))
        if state.get("reloading"):
            reload_text = self.font_small.render("RELOADING...", True, C_AMBER)
            surface.blit(reload_text, (400, top + 40))

        # ---- stance / grenades ----
        stance = state.get("stance", "STAND")
        stance_colour = C_AMBER if stance != "STAND" else C_GREY
        st = self.font_small.render(f"STANCE: {stance}", True, stance_colour)
        surface.blit(st, (400, top + 12))

        grenades = state.get("grenades", 0)
        if grenades > 0:
            gr = self.font_small.render(f"GRENADES: {grenades}", True, C_GREEN)
            surface.blit(gr, (400, top + 26))

        # ---- stamina ----
        stamina = clamp(state.get("stamina", 100.0), 0.0, 100.0)
        self._bar(surface, self.width - 190, top + 12, 172, 8, stamina / 100.0,
                  (200, 190, 90), None, None)

        # ---- time and suspects ----
        clock = state.get("time", 0.0)
        mins = int(clock // 60)
        secs = int(clock % 60)
        time_text = self.font_small.render(f"TIME {mins:02d}:{secs:02d}", True, C_GREY)
        surface.blit(time_text, (self.width - 190, top + 30))
        hostiles = state.get("hostiles", 0)
        hc = C_RED if hostiles else C_GREEN
        ht = self.font_small.render(f"HOSTILES: {hostiles}", True, hc)
        surface.blit(ht, (self.width - 190, top + 44))

    def _bar(self, surface, x, y, w, h, ratio, colour, label, value):
        pygame.draw.rect(surface, (30, 32, 38), (x, y, w, h))
        fill_w = int(w * clamp(ratio, 0.0, 1.0))
        if fill_w > 0:
            pygame.draw.rect(surface, colour, (x, y, fill_w, h))
        pygame.draw.rect(surface, (90, 94, 100), (x, y, w, h), 1)
        if label:
            text = self.font_small.render(f"{label} {value}", True, C_WHITE)
            surface.blit(text, (x + 5, y - 1))

    def _draw_objectives(self, surface, state):
        objectives = state.get("objectives", [])
        if not objectives:
            return
        x = 16
        y = 14
        title = self.font_med.render("OBJECTIVES", True, C_CYAN)
        surface.blit(title, (x, y))
        y += 22
        for obj in objectives:
            done = obj.get("done", False)
            primary = obj.get("primary", True)
            mark = "[X]" if done else "[ ]"
            colour = C_GREEN if done else (C_WHITE if primary else C_GREY)
            label = obj.get("text", "")
            line = self.font_small.render(f"{mark} {label}", True, colour)
            surface.blit(line, (x, y))
            if done:
                pygame.draw.line(surface, C_GREEN, (x + 20, y + 7),
                                 (x + 20 + line.get_width() - 22, y + 7), 1)
            y += 17

        if self.objective_toast:
            text = self.font_big.render(self.objective_toast, True, C_AMBER)
            rect = text.get_rect(center=(self.width // 2, 88))
            bg = pygame.Surface((rect.width + 30, rect.height + 14), pygame.SRCALPHA)
            bg.fill((10, 12, 18, 200))
            surface.blit(bg, (rect.x - 15, rect.y - 7))
            pygame.draw.rect(surface, C_AMBER, (rect.x - 15, rect.y - 7,
                                                rect.width + 30, rect.height + 14), 2)
            surface.blit(text, rect)

    def _draw_minimap(self, surface, state):
        mini = state.get("minimap")
        if mini is None:
            return
        size = 168
        x = self.width - size - 16
        y = 16
        panel = pygame.Surface((size, size), pygame.SRCALPHA)
        panel.fill((6, 8, 12, 200))
        surface.blit(panel, (x, y))
        pygame.draw.rect(surface, (80, 90, 100), (x, y, size, size), 1)

        scale = mini.get("scale", 2.5)
        origin = mini.get("origin", (0, 0))

        def to_screen(wx, wy):
            sx = x + 4 + (wx - origin[0]) * scale
            sy = y + 4 + (wy - origin[1]) * scale
            return sx, sy

        # Walls as a coarse dot grid (cheap and readable).
        for gx, gy in mini.get("walls", []):
            sx, sy = to_screen(gx, gy)
            if x + 4 <= sx < x + size - 4 and y + 4 <= sy < y + size - 4:
                pygame.draw.rect(surface, (70, 78, 88), (sx, sy, max(1, scale), max(1, scale)))

        for dot in mini.get("cameras", []):
            sx, sy = to_screen(dot[0], dot[1])
            colour = dot[2] if len(dot) > 2 else C_CYAN
            pygame.draw.circle(surface, colour, (int(sx), int(sy)), 3, 1)

        for dot in mini.get("enemies", []):
            sx, sy = to_screen(dot[0], dot[1])
            colour = dot[2] if len(dot) > 2 else C_RED
            pygame.draw.circle(surface, colour, (int(sx), int(sy)), 3)

        for dot in mini.get("trucks", []):
            sx, sy = to_screen(dot[0], dot[1])
            colour = dot[2] if len(dot) > 2 else C_AMBER
            pygame.draw.rect(surface, colour, (int(sx) - 2, int(sy) - 2, 5, 5))

        for dot in mini.get("objectives", []):
            sx, sy = to_screen(dot[0], dot[1])
            pygame.draw.circle(surface, C_GREEN, (int(sx), int(sy)), 4, 1)

        px, py = mini.get("player", (0.0, 0.0))
        angle = mini.get("angle", 0.0)
        sx, sy = to_screen(px, py)
        tip = (sx + math.cos(angle) * 7, sy + math.sin(angle) * 7)
        left = (sx + math.cos(angle + 2.5) * 5, sy + math.sin(angle + 2.5) * 5)
        right = (sx + math.cos(angle - 2.5) * 5, sy + math.sin(angle - 2.5) * 5)
        pygame.draw.polygon(surface, C_WHITE, [tip, left, right])

    def _draw_messages(self, surface, state):
        if self.current_message is not None:
            text, colour = self.current_message
            rendered = self.font_med.render(text, True, colour)
            rect = rendered.get_rect(center=(self.width // 2, self.height - 110))
            bg = pygame.Surface((rect.width + 24, rect.height + 12), pygame.SRCALPHA)
            bg.fill((8, 10, 14, 190))
            surface.blit(bg, (rect.x - 12, rect.y - 6))
            surface.blit(rendered, rect)

        y = 130
        for name, timer in self.kill_feed:
            colour = C_GREEN if "Colonel" not in name else C_AMBER
            text = self.font_small.render(f"ELIMINATED: {name}", True, colour)
            surface.blit(text, (16, y))
            y += 16

    def _draw_alert_banner(self, surface, state):
        if not state.get("alarm_active"):
            return
        text = self.font_big.render("! ALARM - DEPOT SECURITY ALERT !", True, (255, 210, 210))
        rect = text.get_rect(center=(self.width // 2, 40))
        bg = pygame.Surface((rect.width + 26, rect.height + 10), pygame.SRCALPHA)
        pulse = int(140 + 80 * (0.5 + 0.5 * math.sin(state.get("time", 0.0) * 8.0)))
        bg.fill((120, 20, 20, pulse))
        surface.blit(bg, (rect.x - 13, rect.y - 5))
        surface.blit(text, rect)

    def _draw_scope(self, surface, state):
        zoom = state.get("scoped", 0.0)
        if zoom <= 0.02:
            return
        # Black out everything outside a circular lens.
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, int(235 * zoom)))
        radius = int(self.height * 0.42)
        pygame.draw.circle(overlay, (0, 0, 0, 0), (self.width // 2, self.height // 2),
                           radius)
        surface.blit(overlay, (0, 0))
        centre = (self.width // 2, self.height // 2)
        pygame.draw.circle(surface, (10, 10, 10), centre, radius, 3)
        # Reticle
        pygame.draw.line(surface, (30, 190, 90),
                         (centre[0] - radius, centre[1]), (centre[0] - 18, centre[1]), 1)
        pygame.draw.line(surface, (30, 190, 90),
                         (centre[0] + 18, centre[1]), (centre[0] + radius, centre[1]), 1)
        pygame.draw.line(surface, (30, 190, 90),
                         (centre[0], centre[1] - radius), (centre[0], centre[1] - 18), 1)
        pygame.draw.line(surface, (30, 190, 90),
                         (centre[0], centre[1] + 18), (centre[0], centre[1] + radius), 1)
        for i in range(-4, 5):
            if i == 0:
                continue
            y = centre[1] + i * 16
            pygame.draw.line(surface, (30, 190, 90),
                             (centre[0] - 6, y), (centre[0] + 6, y), 1)

    def _draw_debug(self, surface, state):
        lines = state.get("debug_lines", [])
        y = 120
        for line in lines:
            text = self.font_small.render(line, True, (180, 220, 180))
            surface.blit(text, (self.width - 340, y))
            y += 15

    # ------------------------------------------------------------- overlays --
    def draw_title_panel(self, surface, title, lines, footer=None,
                         accent=C_CYAN):
        """Shared panel used by the menu, briefing and end screens."""
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((6, 8, 12, 215))
        surface.blit(overlay, (0, 0))
        pygame.draw.rect(surface, (60, 70, 80),
                         (40, 40, self.width - 80, self.height - 80), 2)

        t = self.font_huge.render(title, True, accent)
        surface.blit(t, t.get_rect(center=(self.width // 2, 110)))
        pygame.draw.line(surface, accent, (100, 148), (self.width - 100, 148), 2)

        y = 190
        for line in lines:
            rendered = self.font_med.render(line, True, C_WHITE)
            surface.blit(rendered, (110, y))
            y += 26
        if footer:
            f = self.font_med.render(footer, True, C_AMBER)
            surface.blit(f, f.get_rect(center=(self.width // 2, self.height - 90)))

    def draw_menu(self, surface, options, selected, title, subtitle):
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((4, 6, 10, 200))
        surface.blit(overlay, (0, 0))

        t = self.font_huge.render(title, True, (220, 230, 240))
        surface.blit(t, t.get_rect(center=(self.width // 2, 130)))
        s = self.font_big.render(subtitle, True, C_AMBER)
        surface.blit(s, s.get_rect(center=(self.width // 2, 178)))
        pygame.draw.line(surface, (70, 90, 110), (140, 205), (self.width - 140, 205), 2)

        y = 260
        for index, option in enumerate(options):
            active = index == selected
            colour = C_WHITE if active else C_GREY
            text = self.font_big.render(option, True, colour)
            rect = text.get_rect(center=(self.width // 2, y))
            if active:
                pygame.draw.rect(surface, (40, 90, 120),
                                 (rect.x - 30, rect.y - 5, rect.width + 60,
                                  rect.height + 10))
                pygame.draw.rect(surface, C_CYAN,
                                 (rect.x - 30, rect.y - 5, rect.width + 60,
                                  rect.height + 10), 2)
            surface.blit(text, rect)
            y += 54
