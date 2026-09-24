"""Enemy soldier AI: perception, alert propagation, patrols and combat.

The state machine is deliberately readable:

  IDLE -> PATROL -> SUSPICIOUS -> INVESTIGATE -> COMBAT -> SEARCH -> (PATROL)

Perception is split into sight (cone + line of sight + distance, with a
crouch/concealment modifier) and hearing (radius from noise events). Anything
that sees the player tags a shared "alert" value, which lets nearby guards
converge instead of each acting alone.
"""

import math
import random

from ..config import (ALERT_DECAY, ENEMY_ACCURACY_BASE, ENEMY_DAMAGE,
                      ENEMY_FIRE_PERIOD, ENEMY_FOV, ENEMY_HEIGHT,
                      ENEMY_MAG, ENEMY_RADIUS, ENEMY_REACTION, ENEMY_RELOAD,
                      ENEMY_VIEW_DISTANCE, S_COMBAT, S_DEAD, S_IDLE,
                      S_INVESTIGATE, S_PATROL, S_SEARCH, S_SUSPICIOUS)
from ..utils import (angle_difference, clamp, dist, line_of_sight,
                     rotate_towards)


class Enemy:
    """A single guard.

    Coordinates are world-space tile units. `route` is a list of waypoints that
    the guard walks in a loop (or ping-pongs when there are only two).
    """

    def __init__(self, x, y, facing, route=None, kind="soldier", level=None,
                 audio=None, name=None):
        self.x = float(x)
        self.y = float(y)
        self.z_base = 0.0
        self.facing = float(facing)
        self.kind = kind
        self.name = name or ("Colonel" if kind == "officer" else "Guard")
        self.route = [tuple(p) for p in (route or [(x, y)])]
        self.route_index = 0
        self.route_direction = 1
        self.ping_pong = len(self.route) == 2

        self.health = 130.0 if kind == "officer" else 100.0
        self.armor = 35.0 if kind == "officer" else 0.0
        self.dead = False
        self.death_timer = 0.0
        self.death_angle = 0.0

        self.state = S_PATROL if len(self.route) > 1 else S_IDLE
        self.state_timer = 0.0
        self.alert = 0.0                  # 0..1 shared-suspicion level
        self.visual_contact = False
        self.last_seen = None             # (x, y) of the last confirmed sighting
        self.target = None

        # Combat bookkeeping.
        self.reaction_timer = 0.0
        self.fire_timer = random.uniform(0.0, 0.3)
        self.mag = ENEMY_MAG
        self.reloading = False
        self.reload_timer = 0.0
        self.burst_remaining = 0
        self.burst_timer = 0.0
        self.aim_error = 0.0
        self.suppression = 0.0

        # Search behaviour.
        self.search_points = []
        self.search_index = 0
        self.search_wait = 0.0

        self.move_speed = 1.55 if kind == "soldier" else 1.35
        self.step_timer = 0.0
        self.pause_timer = 0.0
        self.scan_timer = 0.0
        self.scan_target = None

        self.level = level
        self.audio = audio
        # (x, y, facing) of the listener, pushed in by the game layer each frame.
        self.listener = None
        self.footstep_counter = 0
        # Billboard attached by the mission layer.
        self.sprite = None
        self.moving = False

        # Shots this guard has fired, consumed by the game layer.
        self.shots = []
        self.combat_calls = 0

        self._last_hit_distance = 0.0

    # ------------------------------------------------------------ accessors --
    @property
    def last_hit_distance(self):
        return self._last_hit_distance

    @property
    def eye_height(self):
        return 0.62

    @property
    def alive(self):
        return not self.dead

    @property
    def state_name(self):
        return {S_IDLE: "IDLE", S_PATROL: "PATROL", S_SUSPICIOUS: "SUSPICIOUS",
                S_INVESTIGATE: "INVESTIGATE", S_COMBAT: "COMBAT",
                S_SEARCH: "SEARCH", S_DEAD: "DEAD"}[self.state]

    # ------------------------------------------------------------- perceive --
    def can_see(self, px, py, player=None, level=None):
        """Cone + distance + line-of-sight test against a point."""
        level = level or self.level
        distance = dist(self.x, self.y, px, py)
        view = ENEMY_VIEW_DISTANCE
        # Crouching players are harder to spot at range.
        if player is not None and getattr(player, "crouching", False):
            view *= 0.68
        if getattr(player, "sprinting", False):
            view *= 1.15
        if distance > view:
            return False

        angle_to = math.atan2(py - self.y, px - self.x)
        if abs(angle_difference(angle_to, self.facing)) > ENEMY_FOV * 0.5:
            # Guards still notice movement very close to them.
            if distance > 3.0:
                return False
        if level is not None:
            def blocked(bx, by):
                return level.is_solid(bx, by)
            return line_of_sight(self.x, self.y, px, py, blocked, step=0.32)
        return True

    def hear(self, noise_x, noise_y, radius, loudness=0.0):
        """React to a noise event. Returns True if it changed behaviour.

        `radius` is the effective audible radius the emitter advertises; only
        noises at least as loud as the guard's baseline hearing floor carry
        beyond it, which keeps quiet crouched footsteps local.
        """
        if self.dead:
            return False
        distance = dist(self.x, self.y, noise_x, noise_y)
        if distance > radius:
            return False

        if self.state == S_COMBAT:
            self.last_seen = (noise_x, noise_y)
            return False

        self.alert = min(1.0, self.alert + 0.55)
        if self.state in (S_IDLE, S_PATROL, S_SEARCH):
            self._enter_investigate(noise_x, noise_y)
            return True
        self.last_seen = (noise_x, noise_y)
        return True

    def alert_to(self, x, y, kind="gunshot", force_combat=False):
        """Direct alert from a squad-mate, an explosion or taking a hit."""
        if self.dead:
            return
        self.alert = 1.0
        self.last_seen = (x, y)
        if force_combat or kind in ("explosion", "squad"):
            self.state = S_COMBAT
            self.state_timer = 0.0
            self.reaction_timer = ENEMY_REACTION * 0.6
            self.combat_calls += 1
        elif self.state not in (S_COMBAT,):
            self._enter_investigate(x, y)

    # --------------------------------------------------------------- states --
    def _enter_investigate(self, x, y):
        self.state = S_INVESTIGATE
        self.state_timer = 0.0
        self.last_seen = (x, y)

    def _enter_search(self):
        """Fan out around the last known position looking for the player."""
        self.state = S_SEARCH
        self.state_timer = 0.0
        anchor = self.last_seen or (self.x, self.y)
        points = []
        for i in range(4):
            angle = random.uniform(0, math.tau)
            radius = random.uniform(1.2, 5.0)
            px = anchor[0] + math.cos(angle) * radius
            py = anchor[1] + math.sin(angle) * radius
            if self.level and not self.level.blocked_at(px, py, ENEMY_RADIUS):
                points.append((px, py))
        points.append(anchor)
        self.search_points = points
        self.search_index = 0
        self.search_wait = 0.0

    def _resume_patrol(self):
        self.state = S_PATROL if len(self.route) > 1 else S_IDLE
        self.state_timer = 0.0
        self.alert = 0.0

    # ------------------------------------------------------------- movement --
    def _move_towards_point(self, tx, ty, dt, speed_scale=1.0, turn_rate=3.4):
        """Step toward a point with wall-aware sliding. Returns arrival distance."""
        dx = tx - self.x
        dy = ty - self.y
        target_distance = math.hypot(dx, dy)
        if target_distance < 1e-4:
            return 0.0

        desired = math.atan2(dy, dx)
        self.facing = rotate_towards(self.facing, desired, turn_rate * dt)

        # Only advance while roughly facing the target, so turns feel deliberate.
        if abs(angle_difference(desired, self.facing)) > 1.1:
            return target_distance

        step = self.move_speed * speed_scale * dt
        vx = math.cos(self.facing) * step
        vy = math.sin(self.facing) * step

        moved = False
        if not self.level.blocked_at(self.x + vx, self.y, ENEMY_RADIUS):
            self.x += vx
            moved = True
        if not self.level.blocked_at(self.x, self.y + vy, ENEMY_RADIUS):
            self.y += vy
            moved = True

        if not moved:
            # Slide along whichever axis is free, mirroring player collision.
            side = 1.0 if random.random() < 0.5 else -1.0
            if not self.level.blocked_at(self.x + vx * side, self.y, ENEMY_RADIUS):
                self.x += vx * side
            elif not self.level.blocked_at(self.x, self.y + vy * side, ENEMY_RADIUS):
                self.y += vy * side

        self.moving = moved
        if moved:
            self._emit_footstep(dt, speed_scale)
        return target_distance

    def _emit_footstep(self, dt, speed_scale):
        self.step_timer += dt
        interval = 0.52 if speed_scale < 1.2 else 0.4
        if self.step_timer < interval:
            return
        self.step_timer = 0.0
        self.footstep_counter += 1
        if self.audio and self.footstep_counter % 2 == 0:
            self._play_positional("enemy_step", volume=0.16)

    def _play_positional(self, key, volume=None):
        """Play a sound at this guard's position, attenuated for the listener.

        The listener pose is pushed in by the game layer each frame; until then
        sounds play centred, which is harmless.
        """
        if not self.audio:
            return
        listener = self.listener
        if listener is None:
            self.audio.play(key, 0.0, (0.707, 0.707), volume=volume)
            return
        lx, ly, facing = listener
        self.audio.play_at(key, (lx, ly), (self.x, self.y), facing,
                           volume=volume)

    def _advance_route(self):
        if len(self.route) <= 1:
            return self.route[0] if self.route else (self.x, self.y)
        if self.ping_pong:
            self.route_index = (self.route_index + self.route_direction)
            if self.route_index >= len(self.route):
                self.route_index = len(self.route) - 2
                self.route_direction = -1
            elif self.route_index < 0:
                self.route_index = 1
                self.route_direction = 1
        else:
            self.route_index = (self.route_index + 1) % len(self.route)
        return self.route[self.route_index]

    # ---------------------------------------------------------------- update --
    def update(self, dt, player, level=None, global_alert=0.0, audio=None):
        """Advance the guard. `player` may be dead; guards calm down then."""
        level = level or self.level
        if audio is not None:
            self.audio = audio
        self.level = level

        if self.dead:
            self.death_timer += dt
            return

        self.state_timer += dt
        if self.reloading:
            self.reload_timer += dt
            if self.reload_timer >= ENEMY_RELOAD:
                self.reloading = False
                self.mag = ENEMY_MAG
                self.reload_timer = 0.0

        player_alive = player.alive and not getattr(player, "dead", False)
        sees = (player_alive and self.can_see(player.x, player.y, player,
                                              level))
        self.visual_contact = sees

        if sees:
            self.alert = 1.0
            self.last_seen = (player.x, player.y)
            self.target = player
            if self.state != S_COMBAT:
                self.state = S_COMBAT
                self.state_timer = 0.0
                self.reaction_timer = ENEMY_REACTION
                self.combat_calls += 1
                if self.audio:
                    self._play_positional("enemy_alert")
            self.reaction_timer = max(0.0, self.reaction_timer - dt)
        else:
            # Alert decays when nothing is visible or heard.
            self.alert = max(0.0, self.alert - ALERT_DECAY * dt)
            if global_alert > 0.9 and self.state != S_COMBAT and self.last_seen:
                # Squad mates converge on the shared report.
                if self.state not in (S_INVESTIGATE, S_SEARCH):
                    self._enter_investigate(*self.last_seen)

        handler = {
            S_IDLE: self._update_idle,
            S_PATROL: self._update_patrol,
            S_SUSPICIOUS: self._update_suspicious,
            S_INVESTIGATE: self._update_investigate,
            S_COMBAT: self._update_combat,
            S_SEARCH: self._update_search,
        }[self.state]
        handler(dt, player, level, sees)

    # ------------------------------------------------------------ behaviours --
    def _update_idle(self, dt, player, level, sees):
        # A stationary guard scans left and right, which is what makes the
        # static tower posts feel alert rather than frozen.
        self.scan_timer += dt
        if self.scan_target is None or self.scan_timer > 3.2:
            self.scan_timer = 0.0
            self.scan_target = self.facing + random.uniform(-1.0, 1.0)
        self.facing = rotate_towards(self.facing, self.scan_target, 0.5 * dt)
        if self.alert > 0.7 and self.last_seen:
            self._enter_investigate(*self.last_seen)
        elif len(self.route) > 1:
            self.state = S_PATROL

    def _update_patrol(self, dt, player, level, sees):
        if self.pause_timer > 0.0:
            self.pause_timer -= dt
            self.moving = False
            # Scan while paused at a waypoint.
            self.scan_timer += dt
            if self.scan_target is None:
                self.scan_target = self.facing + random.uniform(-0.7, 0.7)
            self.facing = rotate_towards(self.facing, self.scan_target, 0.9 * dt)
            return

        target = self.route[self.route_index]
        remaining = self._move_towards_point(target[0], target[1], dt)
        if remaining < 0.35:
            self.pause_timer = random.uniform(0.8, 2.4)
            self.scan_target = None
            self._advance_route()
        if self.alert > 0.75 and self.last_seen:
            self._enter_investigate(*self.last_seen)

    def _update_suspicious(self, dt, player, level, sees):
        # Freeze, face the last stimulus, build alert; then investigate.
        if self.last_seen:
            desired = math.atan2(self.last_seen[1] - self.y,
                                 self.last_seen[0] - self.x)
            self.facing = rotate_towards(self.facing, desired, 2.6 * dt)
        if self.state_timer > 1.1:
            if self.last_seen:
                self._enter_investigate(*self.last_seen)
            else:
                self._resume_patrol()

    def _update_investigate(self, dt, player, level, sees):
        if not self.last_seen:
            self._enter_search()
            return
        remaining = self._move_towards_point(self.last_seen[0], self.last_seen[1],
                                            dt, speed_scale=1.25, turn_rate=4.2)
        if remaining < 0.5 or self.state_timer > 12.0:
            self._enter_search()

    def _update_search(self, dt, player, level, sees):
        if self.search_wait > 0.0:
            self.search_wait -= dt
            self.scan_timer += dt
            self.facing += math.sin(self.scan_timer * 2.4) * 1.6 * dt
            if self.search_wait <= 0.0:
                self.search_index += 1
            return
        if self.search_index >= len(self.search_points):
            if self.state_timer > 8.0:
                self._resume_patrol()
            return
        point = self.search_points[self.search_index]
        remaining = self._move_towards_point(point[0], point[1], dt,
                                            speed_scale=1.15)
        if remaining < 0.4:
            self.search_wait = random.uniform(0.6, 1.8)
            self.scan_timer = 0.0
        if self.state_timer > 22.0:
            self._resume_patrol()

    def _update_combat(self, dt, player, level, sees):
        """Track, aim and shoot at the player with burst discipline."""
        if not player.alive:
            self.state = S_SEARCH
            self.state_timer = 0.0
            self.search_points = [self.last_seen] if self.last_seen else []
            self.search_index = 0
            return

        # Face the player (or the last known spot when contact is lost).
        aim_point = (player.x, player.y) if sees else (self.last_seen or (self.x, self.y))
        desired = math.atan2(aim_point[1] - self.y, aim_point[0] - self.x)
        self.facing = rotate_towards(self.facing, desired, 5.5 * dt)

        # Break contact -> search.
        if not sees:
            self.lost_contact_timer = getattr(self, "lost_contact_timer", 0.0) + dt
            self._move_towards_point(aim_point[0], aim_point[1], dt,
                                     speed_scale=1.35, turn_rate=5.0)
            if self.lost_contact_timer > 4.5:
                self.lost_contact_timer = 0.0
                self._enter_search()
            return
        self.lost_contact_timer = 0.0

        if self.reaction_timer > 0.0:
            return

        # Maintain a sensible stand-off distance.
        distance = dist(self.x, self.y, player.x, player.y)
        if distance > 9.0:
            self._move_towards_point(player.x, player.y, dt, speed_scale=1.25)
        elif distance < 3.2:
            # Back away while shooting: a retreat step.
            away = desired + math.pi
            step = self.move_speed * 0.85 * dt
            nx = self.x + math.cos(away) * step
            ny = self.y + math.sin(away) * step
            if not level.blocked_at(nx, self.y, ENEMY_RADIUS):
                self.x = nx
            if not level.blocked_at(self.x, ny, ENEMY_RADIUS):
                self.y = ny

        self.fire_timer -= dt
        if self.reloading:
            return
        if self.fire_timer <= 0.0:
            self._fire_at_player(player, level, distance)

    def _fire_at_player(self, player, level, distance):
        if self.mag <= 0:
            self.reloading = True
            self.reload_timer = 0.0
            if self.audio:
                self._play_positional("enemy_reload")
            return

        # Burst discipline: 3-5 rounds then a beat.
        if self.burst_remaining <= 0:
            self.burst_remaining = random.randint(3, 5)
            self.burst_timer = 0.0

        self.burst_remaining -= 1
        self.mag -= 1
        self.fire_timer = ENEMY_FIRE_PERIOD

        # Accuracy degrades with range, player movement, and incoming fire.
        accuracy = ENEMY_ACCURACY_BASE
        accuracy *= clamp(1.25 - distance / 14.0, 0.35, 1.15)
        if getattr(player, "crouching", False):
            accuracy *= 0.9
        if getattr(player, "sprinting", False):
            accuracy *= 0.78
        accuracy *= clamp(1.0 - self.suppression * 0.5, 0.4, 1.0)

        hit = random.random() < accuracy
        self.shots.append({
            "x": self.x, "y": self.y, "hit": hit,
            "damage": ENEMY_DAMAGE * random.uniform(0.8, 1.2),
            "target": (player.x, player.y),
            "kind": self.kind,
        })

        if self.audio:
            self._play_positional("gun_smg", volume=0.5)

        if self.burst_remaining <= 0:
            self.fire_timer = random.uniform(0.55, 1.25)

    # --------------------------------------------------------------- damage --
    def take_damage(self, amount, source_x=None, source_y=None, cause="bullet"):
        """Apply damage. Returns True if this killed the guard."""
        if self.dead:
            return False
        if self.armor > 0:
            absorbed = min(self.armor, amount * 0.5)
            self.armor -= absorbed
            amount -= absorbed
        self.health -= amount
        if source_x is not None:
            self._last_hit_distance = dist(self.x, self.y, source_x, source_y)
        if self.health <= 0.0:
            self.health = 0.0
            self.dead = True
            self.state = S_DEAD
            self.death_timer = 0.0
            self.death_angle = math.atan2(
                (source_y - self.y) if source_y is not None else 0.0,
                (source_x - self.x) if source_x is not None else 1.0)
            if self.audio:
                self._play_positional("enemy_death")
            return True

        self.suppression = min(1.0, self.suppression + 0.5)
        if self.audio:
            self._play_positional("enemy_pain")
        # Being shot at reveals the shooter's position.
        if source_x is not None:
            self.alert_to(source_x, source_y, "gunshot", force_combat=True)
        return False

    def suppress(self, amount=0.4):
        self.suppression = min(1.0, self.suppression + amount)

    def decay_suppression(self, dt):
        self.suppression = max(0.0, self.suppression - dt * 0.6)

    def consume_shots(self):
        shots = self.shots
        self.shots = []
        return shots

    # -------------------------------------------------------------- geometry --
    def bounds(self):
        """Axis-aligned bounds used for quick hit queries."""
        return (self.x - ENEMY_RADIUS, self.y - ENEMY_RADIUS,
                self.x + ENEMY_RADIUS, self.y + ENEMY_RADIUS)

    @property
    def height(self):
        return ENEMY_HEIGHT

    def hit_test(self, px, py, radius=0.0):
        return dist(self.x, self.y, px, py) <= ENEMY_RADIUS + radius
