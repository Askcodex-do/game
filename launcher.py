"""Covert Strike launcher: a small graphical front end for the executable.

The game itself is a full-screen interactive application, so a bare .exe that
jumps straight into gameplay gives no way to read the controls, change video
settings or confirm the machine can run it. This launcher presents those
options, then either starts the game as a child process or runs it in-process.

Launching the game as a separate process matters: when the player quits, the
launcher is still there and can start another round, which is what people
expect from a game with a menu.

Only used when the executable is started with no arguments. Passing a game
flag such as ``--smoke`` or ``--fullscreen`` goes straight to the game, so the
CLI and the CI smoke test behave exactly as before.
"""

import os
import subprocess
import sys

import pygame

from src import config

# Launcher sizing is independent of the game's internal render resolution.
WIN_W, WIN_H = 720, 460

BG = (10, 13, 18)
PANEL = (20, 25, 33)
PANEL_HI = (30, 38, 50)
EDGE = (58, 70, 86)
CYAN = (120, 226, 236)
AMBER = (240, 190, 96)
TEXT = (216, 224, 234)
DIM = (140, 152, 168)
GREEN = (126, 214, 140)
RED = (232, 120, 120)

OPTION_KEYS = [
    ("fullscreen", "Fullscreen"),
    ("low_detail", "Low detail (weak GPU)"),
    ("no_audio", "Mute audio"),
]

NOTES = {
    "fullscreen": "Fill the display. Press F11 in game to toggle.",
    "low_detail": "Halves ground casting. Use on old integrated graphics.",
    "no_audio": "Silence everything. Useful if the sound device is busy.",
}


def _font(size, bold=False):
    for name in ("consolas", "dejavusansmono", "couriernew", "monospace"):
        try:
            return pygame.font.SysFont(name, size, bold=bold)
        except Exception:
            continue
    return pygame.font.Font(None, size)


class Launcher:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption(config.TITLE)
        # SCALED needs a hardware renderer, which headless CI (SDL dummy
        # driver) and some old drivers do not provide. Fall back progressively
        # rather than failing to start.
        self.screen = None
        for flags in (pygame.SCALED | pygame.RESIZABLE, pygame.RESIZABLE, 0):
            try:
                self.screen = pygame.display.set_mode((WIN_W, WIN_H), flags)
                break
            except pygame.error:
                continue
        if self.screen is None:
            raise RuntimeError("could not open a window for the launcher")
        self.clock = pygame.time.Clock()
        self.title_font = _font(34, bold=True)
        self.sub_font = _font(15)
        self.item_font = _font(19)
        self.small_font = _font(14)
        self.options = {key: False for key, _ in OPTION_KEYS}
        self.hover_button = -1
        self.hover_option = -1
        self.status = ""
        self.status_colour = DIM
        self.status_timer = 0.0
        self.running = True
        self.child = None
        self._ICON = None

    # ------------------------------------------------------------- layout --
    def _icon(self, size):
        try:
            from tools.make_icon import render_icon
            import numpy as np
            rgb, alpha = render_icon(size)
            # render_icon returns (y, x, channel); pygame wants (x, y, channel).
            arr = np.ascontiguousarray(
                np.transpose(np.dstack([rgb, alpha]), (1, 0, 2)))
            # blit_array does not accept 4-channel arrays, so build the surface
            # straight from the buffer instead.
            return pygame.image.frombuffer(arr.tobytes(), (size, size), "RGBA")
        except Exception:
            return None

    def _option_rows(self):
        rows = []
        top = 210
        for index, (key, label) in enumerate(OPTION_KEYS):
            rows.append((pygame.Rect(48, top + index * 44, WIN_W - 96, 34),
                         key, label))
        return rows

    def _button_rects(self):
        gap = 16
        width = 190
        height = 46
        total = width * 2 + gap
        left = (WIN_W - total) // 2
        top = WIN_H - 78
        return [
            (pygame.Rect(left, top, width, height), "start"),
            (pygame.Rect(left + width + gap, top, width, height), "quit"),
        ]

    # -------------------------------------------------------------- input --
    def _set_status(self, text, colour=DIM, seconds=4.0):
        self.status = text
        self.status_colour = colour
        self.status_timer = seconds

    def _build_argv(self):
        """Return the command line that starts the game.

        Split out from _launch so the argument construction can be tested on
        its own, without spawning a process.
        """
        if getattr(sys, "frozen", False):
            # A frozen build is a single exe; re-invoke it with a game flag so
            # it skips this launcher next time round.
            argv = [sys.executable, "--play"]
        else:
            argv = [sys.executable, os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "main.py")]
        if self.options["fullscreen"]:
            argv.append("--fullscreen")
        if self.options["no_audio"]:
            argv.append("--no-audio")
        if self.options["low_detail"]:
            argv.append("--low-detail")
        return argv

    def _launch(self):
        """Start the game in a child process so we return here on exit."""
        if self.child is not None and self.child.poll() is None:
            self._set_status("The game is already running.", AMBER)
            return
        argv = self._build_argv()
        if getattr(sys, "frozen", False):
            cwd = os.path.dirname(sys.executable)
        else:
            cwd = os.path.dirname(os.path.abspath(__file__))
        try:
            creation = 0
            if os.name == "nt":
                # Detach so closing the launcher is not blocked by the game.
                creation = 0x00000008  # DETACHED_PROCESS
            self.child = subprocess.Popen(argv, cwd=cwd, creationflags=creation)
        except Exception as exc:  # pragma: no cover - environment dependent
            self._set_status(f"Could not start the game: {exc}", RED)
            return
        self._set_status("Mission launched. This window will wait.", GREEN, 6.0)

    def _quit(self):
        self.running = False

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self._quit()
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                self._quit()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._launch()
            elif event.key in (pygame.K_SPACE,):
                # Space cycles the highlighted option for keyboard-only use.
                if self.hover_option >= 0:
                    key = OPTION_KEYS[self.hover_option][0]
                    self.options[key] = not self.options[key]
            elif pygame.K_1 <= event.key <= pygame.K_3:
                key = OPTION_KEYS[event.key - pygame.K_1][0]
                self.options[key] = not self.options[key]
        elif event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self.hover_button = -1
            for rect, action in self._button_rects():
                if rect.collidepoint(mx, my):
                    self.hover_button = 0 if action == "start" else 1
            self.hover_option = -1
            for index, (rect, _key, _label) in enumerate(self._option_rows()):
                if rect.collidepoint(mx, my):
                    self.hover_option = index
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for rect, key, _label in self._option_rows():
                if rect.collidepoint(mx, my):
                    self.options[key] = not self.options[key]
            for rect, action in self._button_rects():
                if rect.collidepoint(mx, my):
                    if action == "start":
                        self._launch()
                    else:
                        self._quit()

    # -------------------------------------------------------------- render --
    def draw(self, dt):
        s = self.screen
        s.fill(BG)

        # Backdrop: a reticle watermark in the top-right corner. Rendered once
        # and cached; regenerating it every frame would waste CPU for no gain.
        if self._ICON is None:
            self._ICON = self._icon(150)
        if self._ICON is not None:
            s.blit(self._ICON, (WIN_W - 190, 26))

        title = self.title_font.render("COVERT STRIKE", True, CYAN)
        s.blit(title, (48, 44))
        sub = self.sub_font.render("Stage One  \u2014  Silent Depot", True, DIM)
        s.blit(sub, (50, 88))

        rules = self.small_font.render(
            "Sabotage the convoy before dawn. Night infiltration, one operator.",
            True, TEXT)
        s.blit(rules, (50, 120))
        hint = self.small_font.render(
            "WASD move  \u00b7  mouse look  \u00b7  crouch to stay quiet  "
            "\u00b7  Tab objectives  \u00b7  F11 fullscreen", True, DIM)
        s.blit(hint, (50, 142))

        # Separator.
        pygame.draw.line(s, EDGE, (48, 180), (WIN_W - 48, 180), 1)

        label = self.small_font.render("LAUNCH OPTIONS", True, DIM)
        s.blit(label, (48, 190))

        mx, my = pygame.mouse.get_pos()
        for index, (rect, key, text) in enumerate(self._option_rows()):
            hovered = self.hover_option == index
            base = PANEL_HI if hovered else PANEL
            pygame.draw.rect(s, base, rect, border_radius=6)
            pygame.draw.rect(s, EDGE, rect, 1, border_radius=6)
            # Checkbox.
            box = pygame.Rect(rect.x + 10, rect.y + 8, 18, 18)
            pygame.draw.rect(s, EDGE, box, 2, border_radius=4)
            if self.options[key]:
                pygame.draw.rect(s, CYAN, box.inflate(-6, -6), border_radius=2)
            s.blit(self.item_font.render(text, True,
                                         TEXT if hovered else DIM),
                   (rect.x + 40, rect.y + 6))
            note = self.small_font.render(NOTES[key], True, (96, 106, 120))
            s.blit(note, (rect.x + 40, rect.y + 22 - 2))

        if self.status and self.status_timer > 0:
            self.status_timer -= dt
            shown = self.small_font.render(self.status, True, self.status_colour)
            s.blit(shown, (48, WIN_H - 108))

        for index, (rect, action) in enumerate(self._button_rects()):
            hovered = self.hover_button == index
            accent = CYAN if action == "start" else (150, 160, 174)
            fill = PANEL_HI if hovered else PANEL
            pygame.draw.rect(s, fill, rect, border_radius=8)
            pygame.draw.rect(s, accent if hovered else EDGE, rect, 2,
                             border_radius=8)
            text = "START MISSION" if action == "start" else "QUIT"
            rendered = self.item_font.render(text, True,
                                             accent if hovered else TEXT)
            s.blit(rendered, rendered.get_rect(center=rect.center))

        foot = self.small_font.render(
            "Original work \u00b7 no third-party assets  \u00b7  "
            "Enter to launch  \u00b7  Esc to quit", True, (92, 102, 116))
        s.blit(foot, foot.get_rect(center=(WIN_W // 2, WIN_H - 16)))

        pygame.display.flip()

    def run(self):
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            for event in pygame.event.get():
                self.handle_event(event)
            self.draw(dt)
        pygame.quit()


def main():
    Launcher().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
