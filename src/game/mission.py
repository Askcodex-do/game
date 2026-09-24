"""Mission orchestration: entity ownership, simulation and the game snapshot.

`Mission` is the single place that owns the level, the player, the guards,
cameras, trucks and effects, and it advances all of them in a fixed order:

  1. player input + movement (emits noise)
  2. weapons (emits shots and explosions)
  3. guards (consume noise and shots, emit their own)
  4. cameras and the alarm
  5. trucks
  6. effects and objectives

Everything the HUD needs is produced as a plain dict by `snapshot()`, so the
renderer and HUD never reach into game objects directly.
"""

import math
import random

from ..config import WEAPONS
from ..engine.particles import ParticleSystem
from ..engine.sprites import Sprite
from ..utils import dist, line_of_sight
from .enemies import S_COMBAT, S_INVESTIGATE, S_SUSPICIOUS, Enemy
from .level import Level
from .objectives import MissionState
from .player import Player
from .security_cameras import AlarmSystem, SecurityCamera
from .vehicles import Truck
from .weapons import WeaponSystem


class Mission:
    """The live stage: everything that exists in the world right now."""

    def __init__(self, art, level=None, audio=None, difficulty=1.0):
        self.art = art
        self.audio = audio
        self.level = level or Level()
        self.difficulty = difficulty

        self.player = Player(self.level.player_start[0],
                             self.level.player_start[1],
                             self.level.player_start_angle)
        self.player.armor = 30
        self.weapons = WeaponSystem(audio=audio)
        self.state = MissionState(
            intel_count=len(self.level.intel_spawns),
            cameras=len(self.level.camera_spawns),
            trucks=2,
        )
        self.particles = ParticleSystem(art, self.level)
        self.alarm = AlarmSystem(audio=audio)

        self.enemies = []
        self.cameras = []
        self.trucks = []
        self.pickups = []
        self.intel_items = []
        self.static_sprites = []
        self.effects = []                 # transient explosion visuals

        self.time = 0.0
        self.objective_flash_timer = 0.0
        self.finished = False
        self.outcome = None
        self.death_delay = 0.0
        self.music_mode = "stealth"
        self.ambient_started = False
        # Set by the game layer so the mission can post HUD messages directly.
        self.hud = None
        self._wire_resolver()
        self._build()
        # Entities need their billboards before the first frame is drawn.
        self._attach_sprites()

    # ------------------------------------------------------------- building --
    def _wire_resolver(self):
        """Let the weapon system ask "what am I hitting at this point?".

        Targets are guards, cameras and trucks. The resolver picks the closest
        candidate within a small radius, which makes shots feel generous without
        letting rounds curve through walls.
        """
        def resolver(px, py, radius=0.34):
            best = None
            best_distance = radius
            for enemy in self.enemies:
                if enemy.dead:
                    continue
                d = dist(px, py, enemy.x, enemy.y)
                if d <= radius + 0.26 and d < best_distance + 0.26:
                    if d <= best_distance + 0.26:
                        best = enemy
                        best_distance = d
            for camera in self.cameras:
                if camera.destroyed:
                    continue
                d = dist(px, py, camera.x, camera.y)
                if d <= 0.55 and d < best_distance:
                    best = camera
                    best_distance = d
            for truck in self.trucks:
                if truck.destroyed:
                    continue
                d = dist(px, py, truck.x, truck.y)
                if d <= truck.radius and d < best_distance:
                    best = truck
                    best_distance = d
            return best

        self.weapons.target_resolver = resolver

    def _build(self):
        level = self.level

        # ---- static scenery ----
        self.static_sprites = level.build_sprites(self.art)

        # ---- guards ----
        for index, (ex, ey, facing, route, kind) in enumerate(level.enemy_spawns):
            enemy = Enemy(ex, ey, facing, route=route, kind=kind, level=level,
                          audio=self.audio,
                          name="Colonel" if kind == "officer"
                          else f"Guard {index + 1:02d}")
            self.enemies.append(enemy)

        # ---- cameras ----
        for cx, cy, facing, name in level.camera_spawns:
            camera = SecurityCamera(cx, cy, facing, name=name, level=level,
                                    audio=self.audio)
            self.cameras.append(camera)

        # ---- trucks ----
        target_count = 0
        for tx, ty, facing, patrolling, route in level.truck_spawns:
            # Only the two parked bowsers in the motor pool are fuel targets.
            fuel = (not patrolling) and target_count < self.state.objectives[
                "trucks"].target
            if fuel:
                target_count += 1
            truck = Truck(tx, ty, facing, patrolling=patrolling, route=route,
                          level=level, audio=self.audio,
                          name="Fuel Bowser" if fuel else "Cargo Truck",
                          fuel=fuel)
            self.trucks.append(truck)

        # ---- pickups ----
        for kind, px, py in level.pickup_spawns:
            self.pickups.append({"kind": kind, "x": px, "y": py,
                                 "taken": False, "bob": random.uniform(0, 6.28)})

        # ---- intel ----
        for ix, iy, label in level.intel_spawns:
            self.intel_items.append({"x": ix, "y": iy, "label": label,
                                     "taken": False})

        self.state.begin()

    # ------------------------------------------------------------- geometry --
    def blocked_for_sight(self, x, y):
        return self.level.is_solid(x, y)

    def world_sprites(self):
        """Every sprite to render this frame, in one list."""
        sprites = list(self.static_sprites)
        sprites.extend(self._entity_sprites())
        sprites.extend(self.particles.sprites())
        return sprites

    def _entity_sprites(self):
        """Build or refresh the sprite attached to each live entity."""
        out = []
        for enemy in self.enemies:
            if enemy.sprite is None:
                continue
            out.append(enemy.sprite)
        for camera in self.cameras:
            if camera.sprite is None:
                continue
            out.append(camera.sprite)
        for truck in self.trucks:
            if truck.sprite is None:
                continue
            out.append(truck.sprite)
        return out

    def _attach_sprites(self):
        """Create sprites for entities that do not have one yet."""
        char_art = {
            "soldier": self.art.soldier,
            "officer": self.art.officer,
            "civilian": self.art.civilian,
        }
        for enemy in self.enemies:
            if enemy.sprite is not None:
                continue
            art = char_art.get(enemy.kind, self.art.soldier)
            frames = {view: frame_list for view, frame_list in art.items()}
            # Extra view 5 is the fallen pose, drawn once the guard is dead.
            frames[5] = self.art.props["bodybag"][0]
            sprite = Sprite(enemy.x, enemy.y, kind=enemy.kind,
                            art_frames=frames, height=1.8, width=0.72,
                            facing=enemy.facing, tag=("enemy", enemy))
            enemy.sprite = sprite

        for camera in self.cameras:
            if camera.sprite is not None:
                continue
            frames = {state: fl for state, fl in self.art.cameras.items()}
            sprite = Sprite(camera.x, camera.y, kind="camera",
                            art_frames=frames, height=0.55, width=0.6,
                            z_base=2.0, facing=camera.facing,
                            emit=0.35, tag=("camera", camera))
            camera.sprite = sprite

        for truck in self.trucks:
            if truck.sprite is not None:
                continue
            frames = {pose: fl for pose, fl in self.art.trucks.items()}
            sprite = Sprite(truck.x, truck.y, kind="truck", art_frames=frames,
                            height=1.55, width=3.3, facing=truck.facing,
                            tag=("truck", truck))
            truck.sprite = sprite

    def _sync_sprites(self):
        """Push live entity state into its sprite each frame."""
        for enemy in self.enemies:
            sprite = enemy.sprite
            if sprite is None:
                continue
            sprite.x = enemy.x
            sprite.y = enemy.y
            sprite.facing = enemy.facing
            sprite.z_base = 0.0
            if enemy.dead:
                # Swap to the fallen pose and flatten it against the ground.
                drop = min(1.0, enemy.death_timer / 0.4)
                sprite.view_override = 5
                sprite.height = 1.8 - 1.55 * drop
                sprite.width = 0.72 + 1.6 * drop
                sprite.brightness = 0.72
                sprite.frame = 0
            else:
                sprite.view_override = None
                sprite.height = 1.8
                sprite.width = 0.72
                # Walk animation advances only while actually moving.
                if enemy.moving:
                    sprite.frame = (sprite.frame + 1) % 3
                else:
                    sprite.frame = 0

        for camera in self.cameras:
            sprite = camera.sprite
            if sprite is None:
                continue
            sprite.facing = camera.sprite_facing
            sprite.frame = 0
            # Camera art is keyed by detection state, not viewing angle.
            sprite.view_override = camera.sprite_state
            sprite.brightness = 0.85 if not camera.destroyed else 0.5
            sprite.emit = 0.0 if camera.destroyed else 0.4

        for truck in self.trucks:
            sprite = truck.sprite
            if sprite is None:
                continue
            sprite.x = truck.x
            sprite.y = truck.y
            sprite.facing = truck.sprite_facing
            if truck.destroyed:
                sprite.brightness = 0.55
                sprite.height = 1.1
                sprite.emit = 0.25

    # ------------------------------------------------------------- simulate --
    def update(self, dt, input_state):
        self.time += dt
        player = self.player

        # Push the listener pose into anything that plays positional audio.
        listener = (player.x, player.y, player.angle)
        for manager in (self.enemies, self.cameras, self.trucks):
            for entity in manager:
                entity.listener = listener

        # ---- 1. player ----
        if not self.finished:
            player.update(dt, self.level, input_state, audio=self.audio)
        else:
            player.update(dt, self.level,
                          {"move_x": 0.0, "move_y": 0.0}, audio=self.audio)

        # Death can come from any source (guards, explosions, the world), so the
        # mission watches for it rather than relying on the shooting code path.
        if not player.alive and not self.finished:
            self._on_player_death()

        # ---- 2. weapons ----
        self.weapons.update(dt, player, self.level, self.enemies)
        player_noises = player.consume_noise()

        # ---- resolve shots fired this tick ----
        self._resolve_player_shots()

        # ---- 3. guards ----
        global_alert = self._global_alert()
        for enemy in self.enemies:
            if enemy.dead:
                enemy.update(dt, player, self.level)
                enemy.decay_suppression(dt)
                continue
            enemy.update(dt, player, self.level, global_alert, self.audio)
            enemy.decay_suppression(dt)

        # Feed player-generated noise to the guards.
        self._propagate_noise(player_noises)

        # ---- resolve enemy fire ----
        self._resolve_enemy_fire()

        # ---- 4. cameras and alarm ----
        self._update_cameras(dt)
        self.alarm.update(dt, self.cameras)

        # ---- 5. trucks ----
        for truck in self.trucks:
            truck.update(dt, player, self.level, self.audio)

        # ---- 6. effects, pickups, objectives ----
        self.particles.update(dt)
        self._update_explosions(dt)
        self._update_pickups(dt)
        self._check_extraction()
        self._update_state(dt)
        self._sync_sprites()
        self._attach_sprites()
        self._update_music()

    # --------------------------------------------------------- shot handling --
    def _resolve_player_shots(self):
        results = self.weapons.pending_hits()
        if not results:
            return
        player = self.player
        for result in results:
            if not result.hit or result.target is None:
                if result.point is not None:
                    px, py = result.point
                    self.particles.bullet_impact(
                        px - math.cos(player.angle) * 0.1,
                        py - math.sin(player.angle) * 0.1,
                        player.eye_z, player.angle, result.surface)
                continue
            target = result.target
            damage = result.damage
            killed = False
            if isinstance(target, SecurityCamera):
                destroyed = target.take_damage(damage, player.x, player.y)
                if destroyed:
                    killed = True
                    self.state.sync_cameras(
                        sum(1 for c in self.cameras if c.destroyed))
                    self.particles.explosion(target.x, target.y, 2.0, 1.2)
                    self._on_camera_killed(target)
            elif isinstance(target, Truck):
                destroyed = target.take_damage(damage, player.x, player.y)
                if destroyed:
                    killed = True
                    self._on_truck_killed(target)
            elif isinstance(target, Enemy):
                killed = target.take_damage(damage, player.x, player.y)
                self.particles.blood(target.x, target.y, 1.0,
                                     math.atan2(player.y - target.y,
                                                player.x - target.x))
                if killed:
                    self._on_enemy_killed(target)
            if result.hit:
                self.particles.bullet_impact(
                    result.point[0], result.point[1], player.eye_z,
                    player.angle + math.pi, "flesh" if isinstance(target, Enemy)
                    else "metal")

    def _on_enemy_killed(self, enemy):
        self.state.on_guard_killed(enemy.kind)
        if enemy.kind == "officer":
            self.state.on_colonel_killed()
            if self.hud:
                pass
        # Nearby allies hear the kill.
        self._alert_nearby(enemy.x, enemy.y, 9.0, "squad")

    def _on_camera_killed(self, camera):
        self.state.sync_cameras(sum(1 for c in self.cameras if c.destroyed))
        # A noisy camera destruction can be noticed.
        self._propagate_noise([{"x": camera.x, "y": camera.y, "radius": 8.0,
                                "kind": "gunshot", "loudness": 8.0}])

    def _on_truck_killed(self, truck):
        self.state.on_truck_destroyed()
        self.particles.explosion(truck.x, truck.y, 0.8, 4.2)
        self.particles.vehicle_wreck(truck.x, truck.y)
        # A burning bowser is impossible to miss: the blast wakes the depot.
        self._alert_nearby(truck.x, truck.y, 30.0, "explosion", force=True)

    def _alert_nearby(self, x, y, radius, kind, force=False):
        for enemy in self.enemies:
            if enemy.dead:
                continue
            if dist(enemy.x, enemy.y, x, y) <= radius:
                if line_of_sight(x, y, enemy.x, enemy.y,
                                 self.blocked_for_sight, step=0.5):
                    enemy.alert_to(x, y, kind, force_combat=force)

    def _propagate_noise(self, events):
        if not events:
            return
        for event in events:
            radius = event.get("radius", 4.0)
            for enemy in self.enemies:
                if enemy.dead:
                    continue
                if dist(enemy.x, enemy.y, event["x"], event["y"]) <= radius:
                    enemy.hear(event["x"], event["y"], radius,
                               event.get("loudness", radius))

    def _resolve_enemy_fire(self):
        player = self.player
        if not player.alive:
            for enemy in self.enemies:
                enemy.consume_shots()
            return
        for enemy in self.enemies:
            for shot in enemy.consume_shots():
                # A whiz past the player's head, always audible and scary.
                self.audio and self.audio.play_at(
                    "bullet_whizz", (player.x, player.y), (shot["x"], shot["y"]),
                    player.angle, volume=0.35)
                if shot["hit"]:
                    died = player.take_damage(shot["damage"] * self.difficulty,
                                              shot["x"], shot["y"])
                    if self.audio:
                        self.audio.play("hurt", 0.0, volume=0.5)
                    if died:
                        self._on_player_death()

    def _global_alert(self):
        """Fraction of living guards in combat, used for squad convergence."""
        living = [e for e in self.enemies if not e.dead]
        if not living:
            return 0.0
        in_combat = sum(1 for e in living if e.state == S_COMBAT)
        return in_combat / len(living)

    # -------------------------------------------------------------- cameras --
    def _update_cameras(self, dt):
        for camera in self.cameras:
            result = camera.update(dt, self.player, self.level, self.audio)
            if result == "alarm":
                self._raise_alarm(camera)

    def _raise_alarm(self, camera):
        if self.alarm.trigger(camera.x, camera.y):
            self.state.on_alarm()
            self.state.objectives["ghost"].done = False
            if self.hud:
                self.hud.push_message(
                    "ALARM RAISED - the garrison is converging on your position",
                    4.5, (255, 160, 160))
            # Everyone gets a fix on the player.
            for enemy in self.enemies:
                if not enemy.dead:
                    enemy.alert_to(self.player.x, self.player.y, "squad",
                                   force_combat=True)

    # ------------------------------------------------------------ explosions --
    def _update_explosions(self, dt):
        for explosion in list(self.effects):
            explosion["life"] -= dt
            if explosion["life"] <= 0.0:
                self.effects.remove(explosion)

    # -------------------------------------------------------------- pickups --
    def _update_pickups(self, dt):
        player = self.player
        for pickup in self.pickups:
            if pickup["taken"]:
                continue
            pickup["bob"] += dt
            if dist(player.x, player.y, pickup["x"], pickup["y"]) > 0.8:
                continue
            self._take_pickup(pickup)

        for item in self.intel_items:
            if item["taken"]:
                continue
            if dist(player.x, player.y, item["x"], item["y"]) > 1.0:
                continue
            item["taken"] = True
            self.state.on_intel()
            if self.audio:
                self.audio.play("intel", 0.0)
            self._retire_static("intel_marker", item["label"])
            if self.hud:
                self.hud.push_message(f"INTEL RECOVERED: {item['label']}",
                                      3.5, (120, 220, 240))

    def _take_pickup(self, pickup):
        kind = pickup["kind"]
        player = self.player
        if kind == "medkit":
            player.heal(45.0)
            if player.health > 95:
                player.add_armor(10)
            if self.audio:
                self.audio.play("pickup_item", 0.0)
        elif kind == "ammo":
            for key in player_weapon_keys(self.weapons):
                if key == "grenade":
                    continue
                self.weapons.add_ammo(key, WEAPONS[key]["mag_size"] * 2)
            self.weapons.add_ammo("grenade", 2)
            if self.audio:
                self.audio.play("pickup_ammo", 0.0)
        else:
            # A weapon cache.
            newly = self.weapons.give(kind)
            self.weapons.add_ammo(kind, WEAPONS[kind]["mag_size"] * 3)
            if self.audio:
                self.audio.play("pickup_item", 0.0)
            if self.hud:
                name = WEAPONS[kind]["name"]
                verb = "ACQUIRED" if newly else "AMMO REFILL"
                self.hud.push_message(f"{verb}: {name}", 3.0, (220, 230, 150))
        pickup["taken"] = True
        self._retire_static("pickup", (kind, pickup["x"], pickup["y"]))

    def _retire_static(self, tag_kind, tag_value):
        for sprite in self.static_sprites:
            tag = sprite.tag
            if not tag or not isinstance(tag, tuple):
                continue
            if tag[0] == tag_kind and len(tag) > 1 and tag[1] == tag_value:
                sprite.opacity = 0.0
                sprite.height = 0.0
                sprite.width = 0.0

    # ----------------------------------------------------------- extraction --
    def _check_extraction(self):
        if self.finished or not self.player.alive:
            return
        player = self.player
        ex, ey = self.level.extraction
        if dist(player.x, player.y, ex, ey) > 1.8:
            return
        primaries_ok = all(self.state.objectives[k].done
                           for k in ("cameras", "trucks", "intel", "colonel"))
        if primaries_ok:
            self.state.on_extracted()
            self._finish(True)
        else:
            if self.hud:
                self.hud.push_message(
                    "EXTRACTION DENIED - objectives outstanding", 2.5,
                    (255, 200, 140))

    # --------------------------------------------------------------- outcome --
    def _on_player_death(self):
        if self.finished:
            return
        self.state.fail("Operator killed in action")
        if self.audio:
            self.audio.play("death", 0.0)
            self.audio.play_stinger("defeat")
        self.death_delay = 2.6
        self._finish(False)

    def _finish(self, success):
        self.finished = True
        self.outcome = "success" if success else "failure"
        self.state.completed = success
        if success:
            if self.audio:
                self.audio.play_stinger("victory")
        self.music_mode = "victory" if success else "defeat"

    def force_fail(self, reason="Mission aborted"):
        self.state.fail(reason)
        self._finish(False)

    # ------------------------------------------------------------- snapshot --
    def _update_state(self, dt):
        self.state.update(dt)
        completed = self.state.consume_completions()
        for obj in completed:
            if self.audio:
                self.audio.play("objective_done", 0.0)
            if self.hud:
                self.hud.show_objective(f"OBJECTIVE COMPLETE: {obj.text}")

    def _update_music(self):
        """Pick the music bed that matches the current pressure level."""
        if self.finished:
            desired = self.music_mode
        elif self.alarm.active:
            desired = "alert"
        else:
            any_combat = any(e.state == S_COMBAT and not e.dead for e in self.enemies)
            any_suspicion = any(e.alert > 0.3 and not e.dead for e in self.enemies)
            if any_combat:
                desired = "alert"
            elif any_suspicion:
                desired = "tension"
            else:
                desired = "stealth"
        if desired != self.music_mode:
            if desired in ("victory", "defeat"):
                self.audio and self.audio.play_stinger(desired)
            else:
                self.audio and self.audio.play_music(desired)
            self.music_mode = desired

    # ------------------------------------------------------------- snapshot --
    def snapshot(self):
        player = self.player
        weapon = self.weapons.current
        stance = ("CROUCH" if player.crouching
                  else ("SPRINT" if player.sprinting else "STAND"))
        alive_enemies = [e for e in self.enemies if not e.dead]
        hostiles = sum(1 for e in alive_enemies
                       if e.state in (S_INVESTIGATE, S_COMBAT))

        return {
            "health": player.health,
            "armor": player.armor,
            "stamina": player.stamina,
            "stance": stance,
            "weapon_name": weapon.name,
            "mag": weapon.mag,
            "reserve": weapon.reserve,
            "melee": weapon.melee,
            "reloading": weapon.reloading,
            "grenades": self.weapons.weapons["grenade"].mag,
            "objectives": self.state.hud_list(),
            "hostiles": hostiles,
            "alarm_active": self.alarm.active,
            "damage_flash": player.damage_flash,
            "time": self.time,
            "scoped": self.weapons.scope_zoom,
            "crosshair_spread": self._crosshair_spread(),
            "minimap": self._minimap_data(),
        }

    def _crosshair_spread(self):
        weapon = self.weapons.current
        spread = weapon.spec["spread"] * 100.0
        if self.player.moving:
            spread += 5.0
        if self.player.sprinting:
            spread += 6.0
        if self.player.crouching:
            spread *= 0.6
        return min(14.0, 2.0 + spread)

    def _minimap_data(self):
        """Coarse, cheap minimap: wall dots plus tagged entity positions."""
        step = 2
        walls = []
        for gy in range(0, self.level.grid.shape[0], step):
            row = self.level.grid[gy]
            for gx in range(0, self.level.grid.shape[1], step):
                if row[gx] != 0:
                    walls.append((gx, gy))

        enemies = []
        for enemy in self.enemies:
            if enemy.dead:
                continue
            colour = (200, 60, 50) if enemy.state in (S_INVESTIGATE, S_COMBAT) \
                else (220, 120, 90)
            if enemy.state in (S_SUSPICIOUS, S_INVESTIGATE):
                colour = (235, 200, 90)
            enemies.append((enemy.x, enemy.y, colour))

        cameras = []
        for camera in self.cameras:
            colour = (90, 90, 95) if camera.destroyed else (90, 200, 220)
            cameras.append((camera.x, camera.y, colour))

        trucks = []
        for truck in self.trucks:
            colour = (70, 70, 75) if truck.destroyed else (
                (240, 170, 60) if truck.fuel else (150, 190, 140))
            trucks.append((truck.x, truck.y, colour))

        objectives = []
        for item in self.intel_items:
            if not item["taken"]:
                objectives.append((item["x"], item["y"]))
        objectives.append(self.level.extraction)

        return {
            "walls": walls,
            "enemies": enemies,
            "cameras": cameras,
            "trucks": trucks,
            "objectives": objectives,
            "player": (self.player.x, self.player.y),
            "angle": self.player.angle,
            "origin": (0.0, 0.0),
            "scale": 168.0 / 68.0,
        }


def player_weapon_keys(weapon_system):
    return weapon_system.owned_keys()
