"""Covert Strike: Stage One - entry point, menus and the main loop.

Run with:
    python main.py                 # windowed
    python main.py --fullscreen
    python main.py --no-audio
    python main.py --low-detail    # half-rate floor casting, for weak GPUs
    python main.py --smoke N       # headless N-frame simulation test
"""

import argparse
import math
import os
import random
import sys
import time

# Headless runs must select dummy drivers before pygame initialises.
if "--smoke" in sys.argv:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from src import config
from src.audio import AudioManager
from src.engine.hud import HUD
from src.engine.raycaster import Raycaster
from src.engine.sprites import SpriteArt
from src.engine.textures import TextureLibrary
from src.game.level import TILE_TEXTURES, Level
from src.game.mission import Mission
from src.game.objectives import BRIEFING


# ------------------------------------------------------------------- states --
S_MENU, S_BRIEFING, S_PLAY, S_PAUSE, S_DEBRIEF, S_OPTIONS, S_CONTROLS = range(7)

MENU_ITEMS = ["New Mission", "Briefing", "Controls", "Options", "Quit"]

CONTROLS_TEXT = [
    ("MOVEMENT", ""),
    ("  W / S", "Move forward / back"),
    ("  A / D", "Strafe left / right"),
    ("  Mouse", "Look"),
    ("  Shift", "Sprint (uses stamina)"),
    ("  C or Ctrl", "Crouch (quiet, slower)"),
    ("  Space", "Jump / mantle (visual hop)"),
    ("COMBAT", ""),
    ("  Left Mouse", "Fire  (hold for automatic weapons)"),
    ("  Right Mouse", "Scope (sniper rifle)"),
    ("  R", "Reload"),
    ("  1 - 6", "Select weapon"),
    ("  Wheel", "Cycle weapons"),
    ("  G", "Throw grenade"),
    ("INTERACTION", ""),
    ("  E", "Interact / collect"),
    ("  Tab", "Hold for objectives and minimap zoom"),
    ("  M", "Toggle mute"),
    ("  F5 / F9", "Quick save / quick load (state snapshot)"),
    ("  Esc", "Pause menu"),
]

OPTIONS_ITEMS = ["Mouse Sensitivity", "Master Volume", "Low Detail",
                 "Fullscreen", "Back"]


class Game:
    """Top-level application: owns the window, states and the mission."""

    def __init__(self, fullscreen=False, no_audio=False, low_detail=False,
                 scale=config.WINDOW_SCALE):
        pygame.init()
        self.scale = scale
        flags = pygame.DOUBLEBUF
        if fullscreen:
            flags |= pygame.FULLSCREEN
            info = pygame.display.Info()
            size = (info.current_w, info.current_h)
        else:
            size = (config.WINDOW_W, config.WINDOW_H)
        self.screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(config.TITLE)
        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()
        self.running = True
        self.fullscreen = fullscreen

        # ---- assets (all generated, no external files) ----
        self.textures = TextureLibrary()
        self.art = SpriteArt()
        self.audio = AudioManager(enabled=not no_audio)
        self.audio.preload(["gun_pistol", "gun_smg", "step_concrete",
                            "step_gravel", "dry_fire", "reload_out"])
        self.hud = HUD(*size)

        self.renderer = Raycaster(textures=self.textures, low_detail=low_detail)
        self.renderer.tile_textures = TILE_TEXTURES
        self.low_detail = low_detail

        self.state = S_MENU
        self.menu_index = 0
        self.options_index = 0
        self.mouse_sensitivity = config.MOUSE_SENSITIVITY
        self.mission = None
        self.level = None
        self.paused_from = S_PLAY
        self.show_debug = False
        self.accumulator = 0.0
        self.fixed_dt = 1.0 / 60.0
        self.last_fps = 0.0
        self.fps_samples = []

        # Held input.
        self.keys_down = set()
        self.mouse_buttons = set()
        self.mouse_delta = (0, 0)
        self.look_pitch = 0.0

        self.save_snapshot = None
        self.audio.play_music("menu")

    # ================================================================ states ==
    def new_mission(self):
        """Build a fresh stage."""
        self.audio.stop_all_loops()
        self.level = Level()
        self.mission = Mission(self.art, level=self.level, audio=self.audio)
        self.mission.hud = self.hud
        self.look_pitch = 0.0
        self.state = S_PLAY
        self.hud.push_message("Insertion complete. Stay quiet.", 4.0,
                              (150, 220, 170))
        if self.audio:
            self.audio.loop_start("ambient")
        pygame.mouse.set_visible(False)
        self._grab_mouse()

    def _grab_mouse(self):
        try:
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)
            pygame.mouse.get_rel()
        except pygame.error:
            pass

    def _release_mouse(self):
        try:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
        except pygame.error:
            pass

    # ================================================================ events ==
    def handle_events(self):
        self.mouse_delta = (0, 0)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._on_key_down(event)
            elif event.type == pygame.KEYUP:
                self.keys_down.discard(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._on_mouse_down(event)
            elif event.type == pygame.MOUSEBUTTONUP:
                self.mouse_buttons.discard(event.button)
            elif event.type == pygame.MOUSEMOTION:
                if pygame.event.get_grab():
                    dx, dy = event.rel
                    self.mouse_delta = (self.mouse_delta[0] + dx,
                                        self.mouse_delta[1] + dy)

    def _on_key_down(self, event):
        key = event.key
        self.keys_down.add(key)
        if key == pygame.K_F11:
            self._toggle_fullscreen()
            return
        if key == pygame.K_F3:
            self.show_debug = not self.show_debug
            return

        if self.state == S_MENU:
            self._menu_key(key)
        elif self.state == S_BRIEFING:
            if key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                self.state = S_MENU
        elif self.state == S_CONTROLS:
            if key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                self.state = S_MENU
        elif self.state == S_OPTIONS:
            self._options_key(key)
        elif self.state == S_PLAY:
            self._play_key_down(key)
        elif self.state == S_PAUSE:
            self._pause_key(key)
        elif self.state == S_DEBRIEF:
            if key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                self.state = S_MENU
                self.audio.play_music("menu")

    def _menu_key(self, key):
        if key in (pygame.K_UP, pygame.K_w):
            self.menu_index = (self.menu_index - 1) % len(MENU_ITEMS)
            self.audio.play("ui_move", 0.0)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.menu_index = (self.menu_index + 1) % len(MENU_ITEMS)
            self.audio.play("ui_move", 0.0)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self._menu_confirm()
        elif key == pygame.K_ESCAPE:
            self.running = False

    def _menu_confirm(self):
        item = MENU_ITEMS[self.menu_index]
        self.audio.play("ui_confirm", 0.0)
        if item == "New Mission":
            self.new_mission()
        elif item == "Briefing":
            self.state = S_BRIEFING
        elif item == "Controls":
            self.state = S_CONTROLS
        elif item == "Options":
            self.options_index = 0
            self.state = S_OPTIONS
        elif item == "Quit":
            self.running = False

    def _options_key(self, key):
        if key in (pygame.K_UP, pygame.K_w):
            self.options_index = (self.options_index - 1) % len(OPTIONS_ITEMS)
            self.audio.play("ui_move", 0.0)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.options_index = (self.options_index + 1) % len(OPTIONS_ITEMS)
            self.audio.play("ui_move", 0.0)
        elif key == pygame.K_ESCAPE:
            self.state = S_MENU
        elif key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_RETURN,
                     pygame.K_SPACE):
            delta = -1 if key == pygame.K_LEFT else 1
            self._adjust_option(delta)

    def _adjust_option(self, delta):
        item = OPTIONS_ITEMS[self.options_index]
        if item == "Mouse Sensitivity":
            self.mouse_sensitivity = max(0.0006,
                                         min(0.006, self.mouse_sensitivity + delta * 0.0004))
            self.audio.play("ui_move", 0.0)
        elif item == "Master Volume":
            self.audio.set_master_volume(
                max(0.0, min(1.0, self.audio._master_volume + delta * 0.1)))
            self.audio.play("ui_click", 0.0)
        elif item == "Low Detail":
            self.low_detail = not self.low_detail if delta else self.low_detail
            self.renderer.low_detail = self.low_detail
            self.audio.play("ui_click", 0.0)
        elif item == "Fullscreen":
            self._toggle_fullscreen()
        elif item == "Back":
            self.state = S_MENU

    def _toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        flags = pygame.DOUBLEBUF
        if self.fullscreen:
            flags |= pygame.FULLSCREEN
            info = pygame.display.Info()
            size = (info.current_w, info.current_h)
        else:
            size = (config.WINDOW_W, config.WINDOW_H)
        self.screen = pygame.display.set_mode(size, flags)
        self.hud = HUD(*size)

    def _play_key_down(self, key):
        if key == pygame.K_ESCAPE:
            self._release_mouse()
            self.state = S_PAUSE
            self.paused_from = S_PLAY
            return
        if self.mission is None or self.mission.finished:
            return
        weapons = self.mission.weapons
        if key == pygame.K_r:
            if weapons.current.start_reload():
                self.audio.play("reload_out", 0.0)
        elif key == pygame.K_g:
            weapons.switch_to("grenade") or weapons.give("grenade")
            weapons.switch_to("grenade")
        elif key == pygame.K_1:
            weapons.select_index(0)
            self._weapon_switch_sound()
        elif key == pygame.K_2:
            weapons.select_index(1)
            self._weapon_switch_sound()
        elif key == pygame.K_3:
            weapons.select_index(2)
            self._weapon_switch_sound()
        elif key == pygame.K_4:
            weapons.select_index(3)
            self._weapon_switch_sound()
        elif key == pygame.K_5:
            weapons.select_index(4)
            self._weapon_switch_sound()
        elif key == pygame.K_6:
            weapons.give("grenade")
            weapons.switch_to("grenade")
            self._weapon_switch_sound()
        elif key == pygame.K_m:
            muted = self.audio.toggle_mute()
            self.hud.push_message("Audio muted" if muted else "Audio on", 1.5)
        elif key == pygame.K_q:
            weapons.cycle(1)
            self._weapon_switch_sound()
        elif key == pygame.K_e:
            self._interact()
        elif key == pygame.K_F5:
            self._quick_save()
        elif key == pygame.K_F9:
            self._quick_load()

    def _weapon_switch_sound(self):
        self.audio.play("reload_charge", 0.0, volume=0.35)

    def _pause_key(self, key):
        if key == pygame.K_ESCAPE:
            self.state = S_PLAY
            self._grab_mouse()
        elif key == pygame.K_RETURN:
            self.state = S_PLAY
            self._grab_mouse()
        elif key == pygame.K_q:
            self.state = S_MENU
            self.audio.play_music("menu")
        elif key == pygame.K_F3:
            self.show_debug = not self.show_debug

    def _on_mouse_down(self, event):
        self.mouse_buttons.add(event.button)
        if self.state == S_MENU:
            if event.button == 1:
                self._menu_confirm()
            return
        if self.state in (S_PAUSE, S_DEBRIEF, S_BRIEFING, S_CONTROLS, S_OPTIONS):
            return
        if self.state == S_PLAY and self.mission is not None:
            if event.button == 1:
                self.mission.weapons.trigger_down(self.mission.player,
                                                  self.mission.level)
            elif event.button == 3:
                if self.mission.weapons.current.scoped:
                    active = self.mission.weapons.toggle_scope()
                    self.hud.push_message(
                        "Scope engaged" if active else "Scope released", 1.2)

    def _interact(self):
        """E-key interactions: picking up intel is automatic, this is for colour."""
        if self.mission is None:
            return
        player = self.mission.player
        nearest = None
        nearest_distance = 2.0
        for item in self.mission.intel_items:
            if item["taken"]:
                continue
            d = math.hypot(item["x"] - player.x, item["y"] - player.y)
            if d < nearest_distance:
                nearest = item
                nearest_distance = d
        if nearest is not None:
            self.hud.push_message(f"Downloading {nearest['label']}...", 1.2,
                                  (140, 220, 240))
        else:
            self.hud.push_message("Nothing to interact with", 1.2, (170, 170, 170))

    # ------------------------------------------------------------ save/load --
    def _quick_save(self):
        if self.mission is None:
            return
        mission = self.mission
        self.save_snapshot = {
            "player": (mission.player.x, mission.player.y,
                       mission.player.angle, mission.player.health,
                       mission.player.armor),
            "time": mission.time,
            "kills": mission.state.kills,
        }
        self.hud.push_message("Quick save stored", 1.6, (150, 220, 150))
        self.audio.play("ui_confirm", 0.0)

    def _quick_load(self):
        if self.mission is None or self.save_snapshot is None:
            self.hud.push_message("No quick save available", 1.6, (230, 160, 160))
            self.audio.play("ui_error", 0.0)
            return
        snap = self.save_snapshot
        px, py, angle, health, armor = snap["player"]
        mission = self.mission
        mission.player.x = px
        mission.player.y = py
        mission.player.angle = angle
        mission.player.health = health
        mission.player.armor = armor
        mission.player.alive = health > 0
        mission.finished = False
        mission.outcome = None
        self.hud.push_message("Quick save restored", 1.6, (150, 220, 150))
        self.audio.play("ui_confirm", 0.0)

    # ================================================================ update ==
    def build_input_state(self):
        keys = self.keys_down
        move_x = 0.0
        move_y = 0.0
        if keys & {pygame.K_w, pygame.K_UP}:
            move_y += 1.0
        if keys & {pygame.K_s, pygame.K_DOWN}:
            move_y -= 1.0
        if keys & {pygame.K_d, pygame.K_RIGHT}:
            move_x += 1.0
        if keys & {pygame.K_a, pygame.K_LEFT}:
            move_x -= 1.0
        run = bool(keys & {pygame.K_LSHIFT, pygame.K_RSHIFT})
        crouch = bool(keys & {pygame.K_c, pygame.K_LCTRL, pygame.K_RCTRL})

        dx, dy = self.mouse_delta
        look_dx = dx * self.mouse_sensitivity
        # Mouse Y inverts to match first-person expectations, then feeds pitch.
        look_dy = -dy * self.mouse_sensitivity * 260.0
        self.look_pitch = max(-1.2, min(1.2, self.look_pitch + look_dy * 0.004))
        return {
            "move_x": move_x,
            "move_y": move_y,
            "run": run,
            "crouch": crouch,
            "look_dx": look_dx,
            "look_dy": look_dy * 0.6,
        }

    def update(self, dt):
        if self.state != S_PLAY or self.mission is None:
            return
        input_state = self.build_input_state()
        self.mission.update(dt, input_state)
        self.hud.update(dt)

        # Held-generator behaviours (automatic fire handled inside weapons).
        if 1 in self.mouse_buttons or 3 in self.mouse_buttons:
            pass

        if self.mission.finished:
            # Let the death animation or victory sting play out.
            if (self.mission.outcome == "failure"
                    and self.mission.player.death_timer < 2.4):
                return
            if self.mission.outcome == "failure":
                self._release_mouse()
                self.state = S_DEBRIEF

    def check_victory(self):
        """The debrief opens once victory has been savoured for a moment."""
        if self.mission is None:
            return
        if self.mission.outcome == "success":
            self.mission.death_delay += 1.0 / 60.0

    # ================================================================ render ==
    def render(self):
        surface = self.screen
        if self.state in (S_PLAY, S_PAUSE, S_DEBRIEF) and self.mission is not None:
            self._render_world(surface)
            if self.state == S_PLAY:
                snapshot = self.mission.snapshot()
                if self.show_debug:
                    snapshot["show_debug"] = True
                    snapshot["debug_lines"] = self._debug_lines()
                self.hud.draw(surface, snapshot)
            if self.state == S_PAUSE:
                self._draw_pause(surface)
            elif self.state == S_DEBRIEF:
                self._draw_debrief(surface)
        elif self.state == S_MENU:
            self._render_menu_backdrop(surface)
            self.hud.draw_menu(surface, MENU_ITEMS, self.menu_index,
                              config.TITLE, "STAGE ONE: SILENT DEPOT")
        elif self.state == S_BRIEFING:
            self._render_menu_backdrop(surface)
            self.hud.draw_title_panel(
                surface, "MISSION BRIEFING", BRIEFING,
                footer="[ENTER] return to menu    [ESC] back", accent=(120, 210, 240))
        elif self.state == S_CONTROLS:
            self._render_menu_backdrop(surface)
            lines = [f"{k:<16}{v}" for k, v in CONTROLS_TEXT]
            self.hud.draw_title_panel(
                surface, "CONTROLS", lines,
                footer="[ENTER] return to menu", accent=(150, 220, 160))
        elif self.state == S_OPTIONS:
            self._render_menu_backdrop(surface)
            self._draw_options(surface)

        pygame.display.flip()

    def _render_world(self, surface):
        mission = self.mission
        player = mission.player
        cam = self.renderer
        from src.engine.raycaster import Camera
        view = Camera(player.x, player.y, player.total_view_angle,
                      eye_z=player.eye_z, pitch=player.total_view_pitch)
        # The scope magnifies by narrowing the projection, which is handled
        # inside the renderer's zoom hook.
        zoom = 1.0 - mission.weapons.scope_zoom * 0.62
        cam.render(view, mission.level.grid, mission.level.floor_a,
                   mission.level.ceiling, mission.world_sprites(), zoom=zoom)
        cam.present(surface, self.scale)

    def _debug_lines(self):
        mission = self.mission
        lines = [
            f"FPS {self.last_fps:.0f}",
            f"POS {mission.player.x:.1f},{mission.player.y:.1f}",
            f"ANG {math.degrees(mission.player.angle):.0f}",
            f"ALERT {mission.alarm.active}",
            f"ENEMIES {sum(1 for e in mission.enemies if not e.dead)}",
            f"SPRITES {len(mission.world_sprites())}",
            f"PARTICLES {len(mission.particles)}",
            f"CAMS {sum(1 for c in mission.cameras if c.destroyed)}/{len(mission.cameras)}",
            f"TRUCKS {sum(1 for t in mission.trucks if t.destroyed)}/{len(mission.trucks)}",
            f"SHOTS {mission.weapons.shots_fired} HITS {mission.weapons.hits}",
            f"MUSIC {mission.music_mode}",
        ]
        return lines

    def _render_menu_backdrop(self, surface):
        """A slow drifting star/scanline wash, cheap but atmospheric."""
        surface.fill((6, 9, 14))
        t = pygame.time.get_ticks() * 0.001
        w, h = surface.get_size()
        for i in range(60):
            seed = (i * 37) % 997
            x = int((seed * 13 + t * (8 + i % 5)) % w)
            y = int((seed * 7 + i * 11) % h)
            shade = 40 + (seed % 60)
            pygame.draw.circle(surface, (shade // 2, shade, shade + 10), (x, y), 1)
        pygame.draw.line(surface, (18, 26, 34), (0, h * 2 // 3),
                         (w, h * 2 // 3), 120)

    def _draw_pause(self, surface):
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((4, 6, 10, 170))
        surface.blit(overlay, (0, 0))
        title = self.hud.font_huge.render("PAUSED", True, (220, 230, 240))
        surface.blit(title, title.get_rect(center=(self.hud.width // 2, 150)))
        items = ["[ENTER] Resume", "[Q] Abandon mission", "[F11] Fullscreen",
                 "[ESC] Resume"]
        y = 240
        for item in items:
            text = self.hud.font_med.render(item, True, config.C_GREY)
            surface.blit(text, text.get_rect(center=(self.hud.width // 2, y)))
            y += 30

    def _draw_options(self, surface):
        title = self.hud.font_huge.render("OPTIONS", True, (220, 230, 240))
        surface.blit(title, title.get_rect(center=(self.hud.width // 2, 120)))
        values = {
            "Mouse Sensitivity": f"{self.mouse_sensitivity:.4f}",
            "Master Volume": f"{self.audio._master_volume * 100:.0f}%",
            "Low Detail": "ON" if self.low_detail else "OFF",
            "Fullscreen": "ON" if self.fullscreen else "OFF",
            "Back": "",
        }
        y = 230
        for index, item in enumerate(OPTIONS_ITEMS):
            active = index == self.options_index
            label = f"{item}   {values[item]}".rstrip()
            colour = config.C_WHITE if active else config.C_GREY
            text = self.hud.font_big.render(label, True, colour)
            rect = text.get_rect(center=(self.hud.width // 2, y))
            if active:
                pygame.draw.rect(surface, (40, 90, 120),
                                 (rect.x - 24, rect.y - 4, rect.width + 48,
                                  rect.height + 8))
                pygame.draw.rect(surface, config.C_CYAN,
                                 (rect.x - 24, rect.y - 4, rect.width + 48,
                                  rect.height + 8), 2)
            surface.blit(text, rect)
            y += 52
        hint = self.hud.font_med.render(
            "[LEFT/RIGHT] change   [ESC] back", True, config.C_AMBER)
        surface.blit(hint, hint.get_rect(center=(self.hud.width // 2,
                                                 self.hud.height - 70)))

    def _draw_debrief(self, surface):
        mission = self.mission
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((4, 6, 10, 200))
        surface.blit(overlay, (0, 0))

        success = mission.outcome == "success"
        title = "MISSION ACCOMPLISHED" if success else "MISSION FAILED"
        colour = (120, 230, 150) if success else (230, 110, 110)
        t = self.hud.font_huge.render(title, True, colour)
        surface.blit(t, t.get_rect(center=(self.hud.width // 2, 90)))

        rank, score = mission.state.rank()
        rows = [
            f"Time elapsed      : {int(mission.state.elapsed // 60):02d}:"
            f"{int(mission.state.elapsed % 60):02d}",
            f"Guards eliminated : {mission.state.kills}",
            f"Cameras disabled  : {mission.state.camera_kills}",
            f"Bowsers destroyed : {mission.state.truck_kills}",
            f"Intel recovered   : {mission.state.intel_collected}",
            f"Alarm triggered   : {'YES' if mission.state.alarm_count else 'NO'}",
            f"Colonel          : {'ELIMINATED' if mission.state.colonel_dead else 'AT LARGE'}",
        ]
        if not success:
            rows.append(f"Reason            : {mission.state.fail_reason}")

        y = 175
        for row in rows:
            text = self.hud.font_med.render(row, True, config.C_WHITE)
            surface.blit(text, (140, y))
            y += 26

        pygame.draw.line(surface, colour, (140, y + 6), (self.hud.width - 140, y + 6), 2)
        rank_text = self.hud.font_huge.render(f"RANK {rank}   SCORE {score}",
                                              True, config.C_AMBER)
        surface.blit(rank_text, rank_text.get_rect(
            center=(self.hud.width // 2, y + 60)))

        footer = self.hud.font_med.render(
            "[ENTER] return to menu    [ESC] menu", True, config.C_GREY)
        surface.blit(footer, footer.get_rect(
            center=(self.hud.width // 2, self.hud.height - 60)))

    # ================================================================== run ==
    def run(self):
        while self.running:
            frame_start = time.time()
            self.handle_events()

            # Fixed timestep simulation with a bounded catch-up, which keeps the
            # AI deterministic-ish without ever spiralling on a slow frame.
            dt = self.clock.tick(config.MAX_FPS) / 1000.0
            dt = min(dt, 0.05)
            if self.state in (S_PLAY, S_PAUSE):
                self.update(dt)

            self.render()

            elapsed = time.time() - frame_start
            if elapsed > 0:
                self.fps_samples.append(1.0 / elapsed)
                if len(self.fps_samples) > 30:
                    self.fps_samples.pop(0)
                self.last_fps = sum(self.fps_samples) / len(self.fps_samples)

        self.audio.shutdown()
        pygame.quit()


# -------------------------------------------------------------------- smoke --
def run_smoke(frames, seed=1234):
    """Headless simulation test: runs the mission with scripted input.

    This exercises every subsystem (render, AI, audio, objectives) without a
    display, which is how the build is verified in CI.
    """
    random.seed(seed)
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.init()
    screen = pygame.display.set_mode((config.RENDER_W, config.RENDER_H))

    textures = TextureLibrary()
    art = SpriteArt()
    audio = AudioManager(enabled=True)
    level = Level()
    mission = Mission(art, level=level, audio=audio)
    renderer = Raycaster(textures=textures, low_detail=True)
    renderer.tile_textures = TILE_LABELS(level)

    dt = 1.0 / 60.0
    stats = {"frames": 0, "render_time": 0.0, "sim_time": 0.0, "errors": []}
    for frame in range(frames):
        # Scripted input: patrol the map, crouch sometimes, and every so often
        # turn to face the nearest living guard before firing so the full
        # combat loop (hit -> damage -> objective) actually runs.
        t = frame * dt
        if frame % 40 == 0:
            living = [e for e in mission.enemies if not e.dead]
            if living:
                nearest = min(living, key=lambda e: (e.x - mission.player.x) ** 2
                              + (e.y - mission.player.y) ** 2)
                mission.player.angle = math.atan2(nearest.y - mission.player.y,
                                                  nearest.x - mission.player.x)
        move_x = math.sin(t * 0.6)
        move_y = 1.0 if math.cos(t * 0.3) > -0.4 else -1.0
        input_state = {
            "move_x": move_x, "move_y": move_y,
            "run": (frame // 120) % 3 == 0,
            "crouch": (frame // 90) % 4 == 0,
            "look_dx": 0.0,
            "look_dy": 0.0,
        }
        t0 = time.time()
        mission.update(dt, input_state)
        stats["sim_time"] += time.time() - t0

        # Fire a burst every 40 frames; reload when asked.
        if frame % 40 == 0:
            mission.weapons.trigger_down(mission.player, mission.level)
        if frame % 40 == 38:
            mission.weapons.trigger_up()
        if frame % 137 == 0:
            mission.weapons.give("smg")
            mission.weapons.switch_to("smg")
        if frame % 211 == 0:
            mission.weapons.give("sniper")
        if frame % 97 == 0:
            mission.weapons.grenades and None
            mission.weapons.give("grenade")
            mission.weapons.switch_to("grenade")
            mission.weapons.trigger_down(mission.player, mission.level)

        t0 = time.time()
        from src.engine.raycaster import Camera
        view = Camera(mission.player.x, mission.player.y,
                      mission.player.total_view_angle,
                      eye_z=mission.player.eye_z,
                      pitch=mission.player.total_view_pitch)
        renderer.render(view, level.grid, level.floor_a, level.ceiling,
                        mission.world_sprites(),
                        zoom=1.0 - mission.weapons.scope_zoom * 0.62)
        renderer.present(screen, 1)
        stats["render_time"] += time.time() - t0
        stats["frames"] += 1

    # ------------------------------------------------------------ reporting --
    print("=" * 66)
    print("SMOKE TEST REPORT  (headless)")
    print("=" * 66)
    print(f"frames simulated   : {stats['frames']}")
    print(f"avg sim  per frame : {stats['sim_time'] / frames * 1000:.2f} ms")
    print(f"avg render per frame: {stats['render_time'] / frames * 1000:.2f} ms")
    print(f"total wall time    : {(stats['sim_time'] + stats['render_time']):.2f} s")
    print(f"shots fired        : {mission.weapons.shots_fired}")
    print(f"shot hits          : {mission.weapons.hits}")
    print(f"guards alive       : {sum(1 for e in mission.enemies if not e.dead)}"
          f" / {len(mission.enemies)}")
    print(f"guards in combat   : {sum(1 for e in mission.enemies if e.state == 5)}")
    print(f"cameras destroyed  : {sum(1 for c in mission.cameras if c.destroyed)}"
          f" / {len(mission.cameras)}")
    print(f"trucks destroyed   : {sum(1 for t in mission.trucks if t.destroyed)}"
          f" / {len(mission.trucks)}")
    print(f"alarm triggered    : {mission.alarm.active} "
          f"(events: {mission.state.alarm_count})")
    print(f"intel collected    : {mission.state.intel_collected}")
    print(f"particles live     : {len(mission.particles)}")
    print(f"player health      : {mission.player.health:.1f}  alive="
          f"{mission.player.alive}")
    print(f"player position    : ({mission.player.x:.1f}, {mission.player.y:.1f})")
    print(f"music mode         : {mission.music_mode}")
    print(f"objectives         : "
          f"{ {k: v.done for k, v in mission.state.objectives.items()} }")

    # Sanity assertions: the world must be producing sensible values.
    problems = []
    if mission.weapons.shots_fired == 0:
        problems.append("no shots were fired")
    if mission.weapons.hits == 0:
        problems.append("scripted aim never connected with a target")
    if not any(not e.dead for e in mission.enemies):
        problems.append("every guard died - AI too fragile")
    if mission.player.health > 100.5 or mission.player.health < 0.0:
        problems.append(f"player health out of range: {mission.player.health}")
    if not math.isfinite(mission.player.x) or not math.isfinite(mission.player.y):
        problems.append("player position became non-finite")
    if level.blocked_at(mission.player.x, mission.player.y, 0.1):
        problems.append("player ended up inside geometry")

    audio.shutdown()
    pygame.quit()
    if problems:
        print("\nPROBLEMS DETECTED:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("\nAll smoke checks passed.")
    return 0


def TILE_LABELS(level):
    return TILE_TEXTURES


# ---------------------------------------------------------------- argparse --
def parse_args(argv):
    parser = argparse.ArgumentParser(description=config.TITLE)
    parser.add_argument("--fullscreen", action="store_true",
                        help="start in fullscreen")
    parser.add_argument("--no-audio", action="store_true",
                        help="disable all sound")
    parser.add_argument("--low-detail", action="store_true",
                        help="halve floor-casting rate for weak GPUs")
    parser.add_argument("--scale", type=int, default=config.WINDOW_SCALE,
                        help="window scale factor")
    parser.add_argument("--smoke", type=int, default=0,
                        help="run N headless simulation frames and report")
    return parser.parse_args(argv)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    if args.smoke:
        return run_smoke(args.smoke)
    game = Game(fullscreen=args.fullscreen, no_audio=args.no_audio,
                low_detail=args.low_detail, scale=args.scale)
    try:
        game.run()
    finally:
        game.audio.shutdown()
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
