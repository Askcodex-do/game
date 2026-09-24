"""Tests for the graphical launcher and the icon generator.

These drive the real widgets - real event objects into the real handler, real
frames drawn onto a real surface - rather than asserting on a description of
them, so a broken hit-box or a crashed draw call shows up here.

Run with:
    python -m pytest tests -v
"""

import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

import launcher  # noqa: E402
import tools.make_icon as make_icon  # noqa: E402


class TestIconArt(unittest.TestCase):
    def test_render_shapes(self):
        rgb, alpha = make_icon.render_icon(64)
        self.assertEqual(rgb.shape, (64, 64, 3))
        self.assertEqual(alpha.shape, (64, 64))
        self.assertEqual(rgb.dtype, np.uint8)
        self.assertEqual(alpha.dtype, np.uint8)

    def test_corners_are_transparent(self):
        _rgb, alpha = make_icon.render_icon(64)
        for y, x in ((0, 0), (0, 63), (63, 0), (63, 63)):
            self.assertEqual(alpha[y, x], 0,
                             f"corner {(y, x)} should be outside the round bezel")

    def test_centre_is_opaque_and_bright(self):
        rgb, alpha = make_icon.render_icon(64)
        cy = cx = 31
        self.assertEqual(alpha[cy, cx], 255)
        # The centre dot is amber, so red and green should dominate blue.
        r, g, b = (int(v) for v in rgb[cy, cx])
        self.assertGreater(r, 120)
        self.assertGreater(g, 100)

    def test_reticle_ring_is_brighter_than_its_surroundings(self):
        size = 128
        rgb, _alpha = make_icon.render_icon(size)
        cx = cy = (size - 1) // 2
        radius = 0.465 * size          # matches render_icon's own geometry
        on_ring = int(rgb[cy, cx + int(0.62 * radius)].mean())
        inside = int(rgb[cy, cx + int(0.30 * radius)].mean())
        self.assertGreater(on_ring, inside,
                           "the reticle ring should stand out from the interior")

    def test_render_is_deterministic(self):
        a1, _ = make_icon.render_icon(48)
        a2, _ = make_icon.render_icon(48)
        np.testing.assert_array_equal(a1, a2)


class TestIconFile(unittest.TestCase):
    def test_write_ico_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "icon.ico")
            make_icon.write_ico(path, sizes=(16, 32, 48))
            data = open(path, "rb").read()

        reserved, kind, count = struct.unpack_from("<HHH", data, 0)
        self.assertEqual((reserved, kind), (0, 1), "must be a valid ICO header")
        self.assertEqual(count, 3)

        for index in range(count):
            dim, _dim2, _c, _r, planes, bpp, size, offset = struct.unpack_from(
                "<BBBBHHII", data, 6 + 16 * index)
            self.assertEqual(bpp, 32)
            self.assertEqual(planes, 1)
            # Each frame starts with a BITMAPINFOHEADER whose biSize is 40 and
            # whose height is doubled to cover the colour data plus the mask.
            bi_size, bi_w, bi_h = struct.unpack_from("<Iii", data, offset)
            self.assertEqual(bi_size, 40)
            self.assertEqual(bi_w, dim)
            self.assertEqual(bi_h, dim * 2)
            self.assertTrue(0 < offset < len(data))
            self.assertLessEqual(offset + size, len(data),
                                 "frame data must fit inside the file")

    def test_version_resource_has_the_expected_fields(self):
        for field in ("FileDescription", "ProductName", "FileVersion",
                      "OriginalFilename", "CompanyName"):
            self.assertIn(field, make_icon.VERSION_RC)
        self.assertIn("CovertStrike.exe", make_icon.VERSION_RC)
        self.assertIn("StringFileInfo", make_icon.VERSION_RC)
        self.assertIn("VarFileInfo", make_icon.VERSION_RC)


class TestLauncher(unittest.TestCase):
    def setUp(self):
        pygame.event.clear()
        self.launcher = launcher.Launcher()

    def tearDown(self):
        pygame.event.clear()

    def _motion(self, x, y):
        self.launcher.handle_event(
            pygame.event.Event(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0),
                               buttons=(0, 0, 0)))

    def _click(self, x, y):
        self.launcher.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x, y)))

    def test_starts_with_every_option_off(self):
        for key, _label in launcher.OPTION_KEYS:
            self.assertFalse(self.launcher.options[key])

    def test_clicking_an_option_row_toggles_it(self):
        rect, key, _label = self.launcher._option_rows()[0]
        self._click(rect.centerx, rect.centery)
        self.assertTrue(self.launcher.options[key])
        self._click(rect.centerx, rect.centery)
        self.assertFalse(self.launcher.options[key])

    def test_each_option_toggles_independently(self):
        for rect, key, _label in self.launcher._option_rows():
            self._click(rect.centerx, rect.centery)
        for key, _label in launcher.OPTION_KEYS:
            self.assertTrue(self.launcher.options[key])
        # Toggling one back leaves the others alone.
        self._click(self.launcher._option_rows()[0][0].centerx,
                    self.launcher._option_rows()[0][0].centery)
        self.assertFalse(self.launcher.options[launcher.OPTION_KEYS[0][0]])
        self.assertTrue(self.launcher.options[launcher.OPTION_KEYS[1][0]])

    def test_number_keys_toggle_options(self):
        self.launcher.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1))
        self.assertTrue(self.launcher.options[launcher.OPTION_KEYS[0][0]])

    def test_hover_tracks_the_mouse(self):
        rect, _key, _label = self.launcher._option_rows()[1]
        self._motion(rect.centerx, rect.centery)
        self.assertEqual(self.launcher.hover_option, 1)
        self._motion(5, 5)
        self.assertEqual(self.launcher.hover_option, -1)

    def test_quit_button_stops_the_loop(self):
        quit_rect, action = [b for b in self.launcher._button_rects()
                             if b[1] == "quit"][0]
        self._click(quit_rect.centerx, quit_rect.centery)
        self.assertFalse(self.launcher.running)

    def test_escape_and_q_quit(self):
        for key in (pygame.K_ESCAPE, pygame.K_q):
            l = launcher.Launcher()
            l.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
            self.assertFalse(l.running)

    def test_window_close_quits(self):
        self.launcher.handle_event(pygame.event.Event(pygame.QUIT))
        self.assertFalse(self.launcher.running)

    def test_draw_produces_a_non_empty_frame(self):
        for _ in range(3):
            self.launcher.draw(1.0 / 60.0)
        frame = pygame.surfarray.array3d(self.launcher.screen)
        self.assertGreater(float(frame.mean()), 5.0,
                           "the launcher frame should not be blank")
        self.assertGreater(len(np.unique(frame.reshape(-1, 3), axis=0)), 100,
                           "the frame should contain rendered detail")

    def test_watermark_icon_renders(self):
        icon = self.launcher._icon(96)
        self.assertIsNotNone(icon, "the reticle watermark should render")
        self.assertEqual(icon.get_size(), (96, 96))

    def test_icon_is_cached_across_frames(self):
        self.launcher.draw(1.0 / 60.0)
        first = self.launcher._ICON
        self.launcher.draw(1.0 / 60.0)
        self.assertIs(first, self.launcher._ICON)

    def test_status_message_expires(self):
        self.launcher._set_status("hello", seconds=0.05)
        self.assertEqual(self.launcher.status, "hello")
        for _ in range(10):
            self.launcher.draw(1.0 / 60.0)
        self.assertLessEqual(self.launcher.status_timer, 0.0)

    def test_launch_builds_argv_from_selected_options(self):
        self.launcher.options["fullscreen"] = True
        self.launcher.options["no_audio"] = True
        self.launcher.options["low_detail"] = True
        argv = self.launcher._build_argv()
        self.assertIn("--fullscreen", argv)
        self.assertIn("--no-audio", argv)
        self.assertIn("--low-detail", argv)
        self.assertNotIn("--play", argv,
                         "an unfrozen run invokes main.py, not the --play path")

    def test_argv_omits_unselected_options(self):
        argv = self.launcher._build_argv()
        for flag in ("--fullscreen", "--no-audio", "--low-detail"):
            self.assertNotIn(flag, argv)

    def test_source_argv_points_at_an_existing_main_py(self):
        argv = self.launcher._build_argv()
        self.assertTrue(argv[1].endswith("main.py"))
        self.assertTrue(os.path.isfile(argv[1]),
                        "the launcher must point at a real entry point")

    def test_launch_does_not_duplicate_a_running_game(self):
        # A live, long-running child stands in for the game process; this is a
        # real process, not a fake, so the poll() check is genuinely exercised.
        self.launcher.child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            time.sleep(0.2)
            self.launcher._launch()
            self.assertIn("already running", self.launcher.status)
            self.assertIsNotNone(self.launcher.child)
        finally:
            self.launcher.child.terminate()
            self.launcher.child.wait(timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
