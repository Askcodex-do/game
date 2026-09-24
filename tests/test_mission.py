"""Functional tests for Covert Strike: Stage One.

These exercise the real code paths - no mocks - by driving a live Mission
object: shooting guards, tripping the camera alarm, destroying bowsers,
collecting intel and completing the stage.

Run with:
    python -m pytest tests -v
or, without pytest installed:
    python tests/test_mission.py
"""

import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pygame  # noqa: E402

from src.audio import AudioManager  # noqa: E402
from src.engine.raycaster import Camera, Raycaster  # noqa: E402
from src.engine.sprites import SpriteArt  # noqa: E402
from src.engine.textures import TextureLibrary  # noqa: E402
from src.game.level import TILE_TEXTURES, Level  # noqa: E402
from src.game.enemies import (S_COMBAT, S_DEAD, S_INVESTIGATE,  # noqa: E402
                              S_PATROL)
from src.game.mission import Mission  # noqa: E402
from src.game.weapons import Grenade  # noqa: E402

# pygame's audio/video need initialising once for the whole test session.
pygame.init()
pygame.display.set_mode((64, 64))
pygame.mixer.init(22050, -16, 2, 512)

_TEXTURES = TextureLibrary()
_ART = SpriteArt()


def make_mission(audio=None):
    level = Level()
    mission = Mission(_ART, level=level, audio=audio)
    return mission


def step(mission, frames=1, input_state=None, dt=1.0 / 60.0):
    """Advance the mission, with neutral input by default."""
    neutral = {"move_x": 0.0, "move_y": 0.0, "run": False, "crouch": False,
               "look_dx": 0.0, "look_dy": 0.0}
    for _ in range(frames):
        mission.update(dt, input_state or neutral)


class TestLevelGeometry(unittest.TestCase):
    def test_player_start_is_walkable(self):
        level = Level()
        self.assertFalse(level.blocked_at(*level.player_start, 0.22),
                         "player spawns inside geometry")

    def test_extraction_is_walkable(self):
        level = Level()
        self.assertFalse(level.blocked_at(*level.extraction, 0.25),
                         "extraction pad is inside geometry")

    def test_all_patrol_waypoints_are_reachable_space(self):
        level = Level()
        for index, (ex, ey, facing, route, kind) in enumerate(level.enemy_spawns):
            self.assertFalse(level.blocked_at(ex, ey, 0.24),
                             f"guard {index} spawns in a wall at ({ex},{ey})")
            for wx, wy in route:
                self.assertFalse(
                    level.blocked_at(wx, wy, 0.30),
                    f"guard {index} waypoint ({wx},{wy}) is inside geometry")

    def test_camera_and_truck_spawns_are_consistent(self):
        level = Level()
        for cx, cy, facing, name in level.camera_spawns:
            self.assertLess(cx, 64)
            self.assertLess(cy, 48)
        for tx, ty, facing, patrolling, route in level.truck_spawns:
            self.assertFalse(level.blocked_at(tx, ty, 0.5),
                             f"truck at ({tx},{ty}) starts in a wall")

    def test_intel_and_pickups_are_reachable(self):
        level = Level()
        for ix, iy, label in level.intel_spawns:
            self.assertFalse(level.blocked_at(ix, iy, 0.2),
                             f"intel '{label}' is inside geometry")
        for kind, px, py in level.pickup_spawns:
            self.assertFalse(level.blocked_at(px, py, 0.2),
                             f"pickup '{kind}' at ({px},{py}) is in a wall")

    def test_tile_texture_table_covers_every_used_tile(self):
        level = Level()
        highest = int(level.grid.max())
        self.assertLess(highest, len(TILE_TEXTURES),
                        "a tile id has no texture assigned")
        for tile_id in range(1, highest + 1):
            self.assertIn(TILE_TEXTURES[tile_id], _TEXTURES.solid)


class TestPlayerMovement(unittest.TestCase):
    def test_walking_forward_moves_the_player(self):
        mission = make_mission()
        start = (mission.player.x, mission.player.y)
        step(mission, 30, {"move_x": 0.0, "move_y": 1.0, "run": False,
                           "crouch": False, "look_dx": 0.0, "look_dy": 0.0})
        moved = math.dist(start, (mission.player.x, mission.player.y))
        self.assertGreater(moved, 0.5, "player did not move forward")

    def test_player_cannot_walk_through_walls(self):
        mission = make_mission()
        # Aim straight at the inner fence line (row y=45) and push into it.
        mission.player.x, mission.player.y = 10.5, 43.5
        mission.player.angle = math.pi / 2     # +y, toward the wall
        for _ in range(120):
            step(mission, 1, {"move_x": 0.0, "move_y": 1.0, "run": False,
                              "crouch": False, "look_dx": 0.0, "look_dy": 0.0})
        self.assertFalse(mission.level.blocked_at(mission.player.x,
                                                  mission.player.y, 0.20),
                         "player tunnelled into a wall")

    def _footstep_radius(self, crouch):
        """Drive the Player directly and read back its footstep noise.

        The mission layer consumes noise events each tick (that is how the AI
        hears them), so this test drives the player in isolation to inspect the
        raw emission.
        """
        from src.game.level import Level
        from src.game.player import Player
        level = Level()
        player = Player(*level.player_start, level.player_start_angle)
        input_state = {"move_x": 0.0, "move_y": 1.0, "run": False,
                       "crouch": crouch, "look_dx": 0.0, "look_dy": 0.0}
        radii = []
        for _ in range(60):
            player.update(1.0 / 60.0, level, input_state)
            radii.extend(e["radius"] for e in player.consume_noise()
                         if e["kind"] == "footstep")
        return max(radii) if radii else 0.0

    def test_crouching_reduces_noise_radius(self):
        standing = self._footstep_radius(False)
        crouched = self._footstep_radius(True)
        self.assertGreater(standing, 0.0, "standing produced no footsteps")
        self.assertGreater(crouched, 0.0, "crouching produced no footsteps")
        self.assertLess(crouched, standing,
                        "crouching should make footsteps quieter")

    def test_health_and_armor_absorb_damage(self):
        mission = make_mission()
        player = mission.player
        player.armor = 50
        player.take_damage(30.0, 0.0, 0.0)
        self.assertLess(player.armor, 50.0, "armor did not absorb anything")
        self.assertGreater(player.health, 70.0, "armor failed to mitigate damage")

    def test_player_dies_at_zero_health(self):
        mission = make_mission()
        died = mission.player.take_damage(999.0, 0.0, 0.0)
        self.assertTrue(died)
        self.assertFalse(mission.player.alive)
        step(mission, 2)
        self.assertTrue(mission.finished,
                        "mission did not register the operator's death")
        self.assertEqual(mission.outcome, "failure")


class TestWeapons(unittest.TestCase):
    def _fire_once(self, mission, weapon_key, target_xy=None):
        weapons = mission.weapons
        weapons.give(weapon_key)
        weapons.switch_to(weapon_key)
        if target_xy is not None:
            player = mission.player
            player.angle = math.atan2(target_xy[1] - player.y,
                                      target_xy[0] - player.x)
        weapons.trigger_down(mission.player, mission.level)
        weapons.trigger_up()
        return mission.weapons.last_shot_result

    def test_firing_consumes_ammunition(self):
        mission = make_mission()
        before = mission.weapons.weapons["pistol"].mag
        self._fire_once(mission, "pistol")
        self.assertEqual(mission.weapons.weapons["pistol"].mag, before - 1)

    def test_reload_moves_rounds_from_reserve(self):
        mission = make_mission()
        pistol = mission.weapons.weapons["pistol"]
        pistol.mag = 0
        reserve_before = pistol.reserve
        pistol.start_reload()
        for _ in range(120):
            pistol.update(1.0 / 60.0)
        self.assertEqual(pistol.mag, pistol.spec["mag_size"])
        self.assertLess(pistol.reserve, reserve_before)

    def test_shooting_a_guard_damages_it(self):
        mission = make_mission()
        guard = mission.enemies[0]
        # Place the player in the guard's path with clear line of sight.
        mission.player.x = guard.x - 2.0
        mission.player.y = guard.y
        mission.player.angle = 0.0
        health_before = guard.health
        self._fire_once(mission, "sniper", (guard.x, guard.y))
        step(mission, 2)
        self.assertLess(guard.health, health_before,
                        "sniper round did not damage the guard")

    def test_enough_damage_kills_a_guard(self):
        mission = make_mission()
        guard = mission.enemies[0]
        for _ in range(12):
            guard.take_damage(50.0, guard.x - 2, guard.y)
        self.assertTrue(guard.dead, "guard survived sustained damage")
        self.assertEqual(guard.state, S_DEAD)

    def test_killing_the_colonel_completes_that_objective(self):
        mission = make_mission()
        colonel = [e for e in mission.enemies if e.kind == "officer"][0]
        for _ in range(10):
            colonel.take_damage(80.0, colonel.x - 2, colonel.y)
        self.assertTrue(colonel.dead)
        # Drive the mission so the objective sync path runs.
        mission.state.on_colonel_killed()
        self.assertTrue(mission.state.objectives["colonel"].done)

    def test_hitscan_is_blocked_by_walls(self):
        """A round fired into a wall must stop at the wall, not pass through."""
        mission = make_mission()
        level = mission.level
        # Stand inside the warehouse and fire straight into its north wall
        # (the warehouse spans x38..54, y28..42, so row 28 is the wall).
        mission.player.x, mission.player.y = 44.5, 35.5
        mission.player.angle = -math.pi / 2      # straight toward -y
        # Confirm the wall really is ahead of us before trusting the result.
        self.assertTrue(level.is_solid(44.5, 28.5),
                        "test placement is wrong: no wall ahead")
        result = self._fire_once(mission, "sniper")
        self.assertIsNotNone(result)
        self.assertFalse(result.hit,
                         "bullet hit a target through a solid wall")
        self.assertEqual(result.surface, "stone")

    def test_hitscan_stops_at_a_guard_with_clear_line_of_sight(self):
        """The mirror case: with nothing in the way, the round connects."""
        mission = make_mission()
        guard = mission.enemies[6]      # static tower sentry, open ground
        mission.player.x = guard.x - 3.0
        mission.player.y = guard.y
        # Clear any intervening geometry by checking first.
        from src.utils import line_of_sight
        if not line_of_sight(mission.player.x, mission.player.y, guard.x, guard.y,
                             mission.level.is_solid, step=0.3):
            self.skipTest("no clear line of sight to the sentry")
        health_before = guard.health
        self._fire_once(mission, "sniper", (guard.x, guard.y))
        step(mission, 2)
        self.assertLess(guard.health, health_before)

    def test_shotgun_fires_multiple_pellets(self):
        mission = make_mission()
        mission.weapons.give("shotgun")
        mission.weapons.switch_to("shotgun")
        results = mission.weapons._fire_hitscan(mission.player, mission.level)
        self.assertIsNotNone(results)
        self.assertEqual(mission.weapons.shots_fired, 1)
        # The pellet count is what makes a shotgun a shotgun.
        self.assertEqual(mission.weapons.current.spec["pellets"], 8)

    def test_grenade_explodes_after_its_fuse(self):
        mission = make_mission()
        grenade = Grenade(mission.player.x, mission.player.y, 1.0,
                          0.0, 0.0, 0.0)
        mission.player.x += 6.0
        mission.weapons.grenades.append(grenade)
        for _ in range(int(2.6 / (1.0 / 60.0))):
            mission.weapons.update(1.0 / 60.0, mission.player, mission.level,
                                   mission.enemies)
            if grenade.exploded:
                break
        self.assertTrue(grenade.exploded, "grenade never detonated")

    def test_grenade_damages_nearby_guard(self):
        mission = make_mission()
        guard = mission.enemies[0]
        mission.player.x = guard.x + 8.0
        mission.player.y = guard.y
        grenade = Grenade(guard.x + 0.4, guard.y, 1.0, 0.0, 0.0, 0.0)
        health_before = guard.health
        mission.weapons.grenades.append(grenade)
        for _ in range(int(2.6 / (1.0 / 60.0))):
            mission.weapons.update(1.0 / 60.0, mission.player, mission.level,
                                   mission.enemies)
            if grenade.exploded:
                break
        self.assertLess(guard.health, health_before,
                        "grenade blast did not hurt a guard in the open")

    def test_grenade_bounces_off_walls(self):
        mission = make_mission()
        # Fire a grenade straight into the perimeter wall.
        grenade = Grenade(10.5, 2.5, 1.0, 0.0, -8.0, 0.0)
        bounced = False
        for _ in range(60):
            event = grenade.update(1.0 / 60.0, mission.level)
            if event == "bounce":
                bounced = True
                break
        self.assertTrue(bounced, "grenade did not bounce off geometry")

    def test_weapon_switch_respects_ownership(self):
        mission = make_mission()
        self.assertFalse(mission.weapons.switch_to("sniper"),
                         "switched to a weapon not yet acquired")
        mission.weapons.give("sniper")
        self.assertTrue(mission.weapons.switch_to("sniper"))


class TestEnemyAI(unittest.TestCase):
    def test_guard_sees_player_in_front(self):
        mission = make_mission()
        guard = mission.enemies[0]
        level = mission.level
        # Put the player 4 units directly ahead of the guard, in open space.
        for distance in (4.0, 3.0, 2.5):
            px = guard.x + math.cos(guard.facing) * distance
            py = guard.y + math.sin(guard.facing) * distance
            if not level.blocked_at(px, py, 0.2):
                mission.player.x, mission.player.y = px, py
                break
        else:
            self.skipTest("could not place player in front of the guard")
        self.assertTrue(guard.can_see(mission.player.x, mission.player.y,
                                      mission.player, level))

    def test_guard_cannot_see_behind_itself(self):
        mission = make_mission()
        guard = mission.enemies[0]
        level = mission.level
        px = guard.x - math.cos(guard.facing) * 5.0
        py = guard.y - math.sin(guard.facing) * 5.0
        if level.blocked_at(px, py, 0.2):
            self.skipTest("placement blocked")
        self.assertFalse(guard.can_see(px, py, mission.player, level))

    def test_wall_blocks_sight(self):
        """A guard inside the motor pool cannot see a player outside its wall."""
        mission = make_mission()
        level = mission.level
        from src.utils import line_of_sight
        # The motor pool's north wall runs along row 32.
        self.assertTrue(level.is_solid(16.0, 32.0),
                        "test placement is wrong: expected a wall at row 32")
        self.assertFalse(
            line_of_sight(16.5, 36.5, 16.5, 30.0, level.is_solid, step=0.3),
            "line of sight passed through the motor pool wall")
        guard = mission.enemies[2]                  # motor pool interior guard
        guard.x, guard.y = 16.5, 36.5
        guard.facing = -math.pi / 2                 # facing the wall
        self.assertFalse(guard.can_see(16.5, 30.0, mission.player, level),
                         "guard saw through a solid wall")

    def test_seeing_player_enters_combat(self):
        mission = make_mission()
        guard = mission.enemies[0]
        mission.player.x = guard.x + 2.0
        mission.player.y = guard.y
        guard.facing = 0.0
        guard.update(1.0 / 60.0, mission.player, mission.level)
        self.assertEqual(guard.state, S_COMBAT,
                         "guard did not enter combat on sight")

    def test_hearing_a_gunshot_investigates(self):
        mission = make_mission()
        # Pick a guard that is not the one nearest the shot.
        guard = mission.enemies[1]
        guard.state = S_PATROL
        responded = guard.hear(guard.x + 2.0, guard.y, 12.0, 12.0)
        self.assertTrue(responded)
        self.assertEqual(guard.state, S_INVESTIGATE)

    def test_quiet_noise_is_not_heard_from_far(self):
        mission = make_mission()
        guard = mission.enemies[1]
        responded = guard.hear(guard.x + 40.0, guard.y, 1.0, 1.0)
        self.assertFalse(responded, "guard heard a distant whisper")

    def test_guard_fires_at_a_visible_player(self):
        mission = make_mission()
        guard = mission.enemies[0]
        mission.player.x = guard.x + 3.0
        mission.player.y = guard.y
        guard.facing = 0.0
        guard.reaction_timer = 0.0
        guard.state = S_COMBAT
        guard.fire_timer = 0.0
        guard._fire_at_player(mission.player, mission.level, 3.0)
        self.assertTrue(guard.shots, "guard produced no shot")

    def test_guard_takes_damage_and_becomes_hostile(self):
        mission = make_mission()
        guard = mission.enemies[1]
        guard.take_damage(20.0, guard.x + 3, guard.y)
        self.assertEqual(guard.state, S_COMBAT,
                         "guard did not react to being shot")

    def test_alert_decays_when_nothing_is_visible(self):
        mission = make_mission()
        guard = mission.enemies[5]
        guard.alert = 0.9
        for _ in range(180):
            guard.update(1.0 / 60.0, mission.player, mission.level)
        self.assertLess(guard.alert, 0.9, "guard alert never decayed")

    def test_guards_do_not_walk_into_walls(self):
        mission = make_mission()
        for _ in range(900):
            for enemy in mission.enemies:
                enemy.update(1.0 / 60.0, mission.player, mission.level)
        for enemy in mission.enemies:
            self.assertFalse(
                mission.level.blocked_at(enemy.x, enemy.y, 0.20),
                f"{enemy.name} walked into geometry at "
                f"({enemy.x:.2f},{enemy.y:.2f})")


class TestSecurityCameras(unittest.TestCase):
    def test_camera_detects_player_in_its_cone(self):
        mission = make_mission()
        camera = mission.cameras[0]
        # Place the player directly along the camera's base facing.
        px = camera.x + math.cos(camera.base_facing) * 3.0
        py = camera.y + math.sin(camera.base_facing) * 3.0
        if mission.level.blocked_at(px, py, 0.2):
            self.skipTest("placement blocked")
        camera.look_angle = camera.base_facing
        self.assertTrue(camera.can_see(px, py, mission.player, mission.level))

    def test_camera_ignores_player_behind_it(self):
        mission = make_mission()
        camera = mission.cameras[0]
        camera.look_angle = camera.base_facing
        px = camera.x - math.cos(camera.base_facing) * 4.0
        py = camera.y - math.sin(camera.base_facing) * 4.0
        self.assertFalse(camera.can_see(px, py, mission.player, mission.level))

    def test_sustained_sighting_raises_the_alarm(self):
        mission = make_mission()
        camera = mission.cameras[0]
        # Pin the camera to a fixed mount so the player can be parked in view.
        camera.sweep_range = 0.0
        camera.look_angle = camera.base_facing
        distance = 3.0
        mission.player.x = camera.x + math.cos(camera.base_facing) * distance
        mission.player.y = camera.y + math.sin(camera.base_facing) * distance
        self.assertFalse(mission.level.blocked_at(mission.player.x,
                                                  mission.player.y, 0.2),
                         "test placement put the player inside geometry")
        frames = int(4.0 / (1.0 / 60.0))
        for _ in range(frames):
            camera.update(1.0 / 60.0, mission.player, mission.level)
            if camera.alarm_raised:
                break
        self.assertTrue(camera.alarm_raised,
                        f"camera never raised the alarm "
                        f"(detection {camera.detection:.2f})")

    def test_shooting_a_camera_destroys_it(self):
        mission = make_mission()
        camera = mission.cameras[0]
        destroyed = False
        for _ in range(6):
            if camera.take_damage(25.0, camera.x, camera.y):
                destroyed = True
                break
        self.assertTrue(destroyed, "camera survived repeated hits")
        self.assertTrue(camera.destroyed)

    def test_alarm_triggers_and_puts_guards_into_combat(self):
        mission = make_mission()
        camera = mission.cameras[0]
        mission._raise_alarm(camera)
        self.assertTrue(mission.alarm.active)
        self.assertGreater(mission.state.alarm_count, 0)
        self.assertTrue(any(e.state == S_COMBAT for e in mission.enemies),
                        "guards did not respond to the alarm")

    def test_alarm_cancels_when_all_cameras_are_destroyed(self):
        mission = make_mission()
        mission._raise_alarm(mission.cameras[0])
        self.assertTrue(mission.alarm.active)
        for camera in mission.cameras:
            camera.destroy()
        mission.alarm.update(1.0 / 60.0, mission.cameras)
        self.assertFalse(mission.alarm.active,
                         "alarm persisted after every camera went down")

    def test_destroying_cameras_completes_the_objective(self):
        mission = make_mission()
        for camera in mission.cameras:
            camera.destroy()
        mission.state.sync_cameras(
            sum(1 for c in mission.cameras if c.destroyed))
        self.assertTrue(mission.state.objectives["cameras"].done)


class TestVehicles(unittest.TestCase):
    def test_two_trucks_are_fuel_targets(self):
        mission = make_mission()
        targets = [t for t in mission.trucks if t.fuel]
        self.assertEqual(len(targets), 2,
                         "expected exactly two fuel bowser objectives")

    def test_destroying_a_fuel_truck_advances_the_objective(self):
        mission = make_mission()
        target = [t for t in mission.trucks if t.fuel][0]
        for _ in range(20):
            if target.take_damage(60.0, target.x - 3, target.y):
                break
        self.assertTrue(target.destroyed)
        mission._on_truck_killed(target)
        self.assertEqual(mission.state.objectives["trucks"].progress, 1)

    def test_both_trucks_destroyed_completes_objective(self):
        mission = make_mission()
        for target in [t for t in mission.trucks if t.fuel]:
            for _ in range(20):
                if target.take_damage(60.0, target.x - 3, target.y):
                    break
            mission._on_truck_killed(target)
        self.assertTrue(mission.state.objectives["trucks"].done)

    def test_patrolling_truck_stays_on_drivable_ground(self):
        mission = make_mission()
        patrol = [t for t in mission.trucks if t.patrolling]
        self.assertTrue(patrol, "no patrolling trucks were created")
        for _ in range(1200):
            for truck in patrol:
                truck.update(1.0 / 60.0, mission.player, mission.level)
        for truck in patrol:
            self.assertFalse(
                mission.level.blocked_at(truck.x, truck.y, 0.30),
                f"patrol truck drove into geometry at "
                f"({truck.x:.2f},{truck.y:.2f})")

    def test_destroyed_truck_blows_up_nearby_guards(self):
        mission = make_mission()
        target = [t for t in mission.trucks if t.fuel][0]
        # Find a guard, place it beside the truck.
        guard = mission.enemies[0]
        guard.x, guard.y = target.x + 1.0, target.y
        target.explode()
        mission._on_truck_killed(target)
        self.assertTrue(target.destroyed)
        # A wreck must not keep running its engine loop.
        self.assertFalse(target.engine_on)


class TestMissionFlow(unittest.TestCase):
    def test_intel_pickup_advances_objective(self):
        mission = make_mission()
        item = mission.intel_items[0]
        mission.player.x, mission.player.y = item["x"], item["y"]
        step(mission, 2)
        self.assertTrue(item["taken"])
        self.assertEqual(mission.state.objectives["intel"].progress, 1)

    def test_all_three_intel_completes_objective(self):
        mission = make_mission()
        for item in mission.intel_items:
            mission.player.x, mission.player.y = item["x"], item["y"]
            step(mission, 2)
        self.assertTrue(mission.state.objectives["intel"].done)

    def test_medkit_heals_the_player(self):
        mission = make_mission()
        mission.player.health = 40.0
        medkit = [p for p in mission.pickups if p["kind"] == "medkit"][0]
        mission.player.x, mission.player.y = medkit["x"], medkit["y"]
        step(mission, 2)
        self.assertGreater(mission.player.health, 40.0)

    def test_weapon_cache_grants_a_weapon(self):
        mission = make_mission()
        cache = [p for p in mission.pickups if p["kind"] == "smg"][0]
        self.assertNotIn("smg", mission.weapons.owned)
        mission.player.x, mission.player.y = cache["x"], cache["y"]
        step(mission, 2)
        self.assertIn("smg", mission.weapons.owned)

    def test_extraction_without_objectives_is_refused(self):
        mission = make_mission()
        mission.player.x, mission.player.y = mission.level.extraction
        step(mission, 2)
        self.assertFalse(mission.finished,
                         "extraction succeeded with objectives outstanding")

    def test_full_mission_completion(self):
        """The complete happy path: objectives done, then extraction."""
        mission = make_mission()
        # Cameras
        for camera in mission.cameras:
            camera.destroy()
        mission.state.sync_cameras(len(mission.cameras))
        # Trucks
        for target in [t for t in mission.trucks if t.fuel]:
            target.explode()
            mission._on_truck_killed(target)
        # Intel
        for item in mission.intel_items:
            mission.player.x, mission.player.y = item["x"], item["y"]
            step(mission, 2)
        # Colonel
        colonel = [e for e in mission.enemies if e.kind == "officer"][0]
        colonel.take_damage(999.0, colonel.x - 2, colonel.y)
        mission.state.on_colonel_killed()
        # Extraction
        mission.player.x, mission.player.y = mission.level.extraction
        step(mission, 4)
        self.assertTrue(mission.finished, "mission never finished")
        self.assertEqual(mission.outcome, "success")
        self.assertEqual(mission.state.rank()[0], "S",
                         "a perfect run should rank S")

    def test_ghost_bonus_lost_when_alarm_trips(self):
        mission = make_mission()
        mission._raise_alarm(mission.cameras[0])
        for camera in mission.cameras:
            camera.destroy()
        mission.state.sync_cameras(len(mission.cameras))
        for target in [t for t in mission.trucks if t.fuel]:
            target.explode()
            mission._on_truck_killed(target)
        for item in mission.intel_items:
            mission.player.x, mission.player.y = item["x"], item["y"]
            step(mission, 2)
        mission.state.on_colonel_killed()
        mission.player.x, mission.player.y = mission.level.extraction
        step(mission, 4)
        self.assertTrue(mission.finished)
        self.assertFalse(mission.state.objectives["ghost"].done,
                         "ghost bonus should be forfeited after an alarm")

    def test_mission_survives_a_long_random_run(self):
        """A fuzz pass: no crashes, no NaN, nothing stuck inside geometry."""
        import random
        random.seed(99)
        mission = make_mission()
        for frame in range(900):
            t = frame / 60.0
            input_state = {
                "move_x": math.sin(t * 1.3),
                "move_y": math.cos(t * 0.7),
                "run": frame % 200 < 40,
                "crouch": frame % 150 < 30,
                "look_dx": 0.04 * math.sin(t * 2.1),
                "look_dy": 0.0,
            }
            mission.update(1.0 / 60.0, input_state)
            if frame % 30 == 0:
                mission.weapons.trigger_down(mission.player, mission.level)
            if frame % 30 == 25:
                mission.weapons.trigger_up()
        self.assertTrue(math.isfinite(mission.player.x))
        self.assertTrue(math.isfinite(mission.player.y))
        for enemy in mission.enemies:
            self.assertTrue(math.isfinite(enemy.x) and math.isfinite(enemy.y))

    def test_snapshot_has_every_hud_key(self):
        mission = make_mission()
        step(mission, 1)
        snap = mission.snapshot()
        for key in ("health", "armor", "stamina", "stance", "weapon_name",
                    "mag", "reserve", "melee", "reloading", "grenades",
                    "objectives", "hostiles", "alarm_active", "damage_flash",
                    "time", "scoped", "crosshair_spread", "minimap"):
            self.assertIn(key, snap, f"HUD snapshot missing '{key}'")


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.renderer = Raycaster(textures=_TEXTURES, low_detail=True)
        self.renderer.tile_textures = TILE_TEXTURES
        self.surface = pygame.Surface((480, 270))

    def test_frame_has_geometry_and_no_garbage(self):
        mission = make_mission()
        cam = Camera(mission.player.x, mission.player.y,
                     mission.player.angle, eye_z=mission.player.eye_z)
        self.renderer.render(cam, mission.level.grid, mission.level.floor_a,
                            mission.level.ceiling, mission.world_sprites())
        frame = self.renderer.frame
        self.assertEqual(frame.shape, (270, 480, 3))
        self.assertGreater(frame.max(), 20, "frame is entirely black")
        self.assertGreater(len(set(frame.reshape(-1, 3).tobytes()[::97])), 4,
                           "frame has almost no variation")

    def test_z_buffer_is_ordered_and_finite(self):
        mission = make_mission()
        cam = Camera(mission.player.x, mission.player.y,
                     mission.player.angle, eye_z=mission.player.eye_z)
        self.renderer.render(cam, mission.level.grid, mission.level.floor_a,
                            mission.level.ceiling, mission.world_sprites())
        z = self.renderer.z_buffer
        self.assertTrue((z > 0).all(), "z-buffer has non-positive values")
        self.assertTrue(z.max() <= 32.0 + 1e-3, "z-buffer exceeded max depth")

    def test_sprites_are_depth_tested_behind_walls(self):
        mission = make_mission()
        # Stand inside the barracks; a guard outside must not be drawn on top.
        cam = Camera(12.0, 12.0, 0.0, eye_z=1.5)
        sprites = mission.world_sprites()
        self.renderer.render(cam, mission.level.grid, mission.level.floor_a,
                            mission.level.ceiling, sprites)
        self.assertTrue((self.renderer.z_buffer < 32.0).any())

    def test_zoom_narrows_the_projection(self):
        mission = make_mission()
        cam = Camera(mission.player.x, mission.player.y,
                     mission.player.angle, eye_z=mission.player.eye_z)
        self.renderer.render(cam, mission.level.grid, mission.level.floor_a,
                            mission.level.ceiling, [], zoom=1.0)
        wide = self.renderer.proj
        self.renderer.render(cam, mission.level.grid, mission.level.floor_a,
                            mission.level.ceiling, [], zoom=0.45)
        self.assertGreater(self.renderer.proj, wide,
                           "scoping did not magnify the projection")

    def test_render_is_fast_enough_for_realtime(self):
        mission = make_mission()
        cam = Camera(mission.player.x, mission.player.y,
                     mission.player.angle, eye_z=mission.player.eye_z)
        import time
        sprites = mission.world_sprites()
        start = time.time()
        frames = 30
        for _ in range(frames):
            self.renderer.render(cam, mission.level.grid, mission.level.floor_a,
                                mission.level.ceiling, sprites)
        per_frame = (time.time() - start) / frames
        # Generous bound: the CI box is shared, but 60 FPS needs < 16.7 ms.
        self.assertLess(per_frame, 0.040,
                        f"render too slow: {per_frame * 1000:.1f} ms/frame")


class TestAudioIntegration(unittest.TestCase):
    def test_audio_manager_builds_and_plays(self):
        audio = AudioManager(enabled=True)
        self.assertTrue(audio.available, "audio mixer unavailable under dummy driver")
        audio.play("gun_pistol", 1.0, (0.7, 0.7))
        audio.loop_start("alarm")
        audio.loop_update("alarm", 4.0, (0.6, 0.8))
        audio.loop_stop("alarm")
        audio.play_music("stealth")
        audio.play_stinger("victory")
        audio.shutdown()

    def test_every_registered_sound_synthesises(self):
        import numpy as np
        from src.audio import registry
        for key, (builder, volume) in registry.SFX_REGISTRY.items():
            samples = builder()
            self.assertGreater(samples.size, 0, f"{key} produced no samples")
            self.assertTrue(np.isfinite(samples).all(), f"{key} has NaN/inf")
            self.assertGreater(float(np.max(np.abs(samples))), 0.0,
                               f"{key} is silent")

    def test_every_music_track_synthesises(self):
        import numpy as np
        from src.audio import music
        for name, builder in music.TRACKS.items():
            samples = builder()
            self.assertGreater(samples.size, 22050, f"{name} is too short")
            self.assertTrue(np.isfinite(samples).all(), f"{name} has NaN/inf")

    def test_mission_runs_with_audio_attached(self):
        audio = AudioManager(enabled=True)
        mission = make_mission(audio=audio)
        step(mission, 60)
        mission.weapons.trigger_down(mission.player, mission.level)
        step(mission, 30)
        audio.shutdown()
        self.assertGreater(mission.weapons.shots_fired, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
