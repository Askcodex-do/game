"""Army trucks: parked fuel bowsers, driving patrols, and destructible wrecks.

Two flavours exist:
  * parked trucks - static cover, some of them mission targets that explode
  * patrol trucks - drive a looped route, emit engine loops, and run over the
    player if they are careless. Their headlights sweep the roads.

Both share the same Sprite billboard and the same damage handling.
"""

import math
import random

from ..utils import dist, rotate_towards


class Truck:
    """A single army truck.

    `patrolling` trucks follow `route` forever at a modest speed, articulating
    their facing toward the road ahead. Parked trucks just sit there, with an
    idle engine only if `engine_on` is set.
    """

    WIDTH = 3.4
    LENGTH = 1.0

    def __init__(self, x, y, facing, patrolling=False, route=None,
                 level=None, audio=None, name="Truck", fuel=True):
        self.x = float(x)
        self.y = float(y)
        self.facing = float(facing)
        self.patrolling = bool(patrolling)
        self.route = [tuple(p) for p in (route or [(x, y)])]
        self.route_index = 0
        self.level = level
        self.audio = audio
        self.name = name

        self.fuel = fuel                  # fuel bowsers are the explosive targets
        self.destroyed = False
        self.health = 260.0 if fuel else 340.0
        self.burning_timer = 0.0
        self.smoke_timer = 0.0
        self.speed = 2.6 if patrolling else 0.0
        self.engine_on = True
        self.sprite_facing = self.facing
        self.listener = None
        self.headlight_on = patrolling

        self.horn_cooldown = random.uniform(2.0, 8.0)
        self.wheel_phase = random.uniform(0.0, math.tau)
        self.sprite = None

        # Body that can block the player's path while intact.
        self.radius = 1.25

    # ------------------------------------------------------------ accessors --
    @property
    def alive(self):
        return not self.destroyed

    @property
    def height(self):
        return 1.55

    @property
    def targetable(self):
        return self.fuel

    # ---------------------------------------------------------------- update --
    def update(self, dt, player=None, level=None, audio=None):
        if audio is not None:
            self.audio = audio
        if level is not None:
            self.level = level

        if self.destroyed:
            self.burning_timer += dt
            self.smoke_timer -= dt
            if self.smoke_timer <= 0.0:
                self.smoke_timer = random.uniform(0.08, 0.2)
            return

        if self.patrolling:
            self._drive(dt)
            self._engine_sound(dt, moving=True)
        else:
            self._engine_sound(dt, moving=False)

        if player is not None and player.alive and not self.destroyed:
            self._run_over_check(player, dt)

    def _drive(self, dt):
        if len(self.route) <= 1:
            return
        target = self.route[self.route_index]
        dx = target[0] - self.x
        dy = target[1] - self.y
        remaining = math.hypot(dx, dy)

        if remaining < 0.6:
            self.route_index = (self.route_index + 1) % len(self.route)
            # Trucks pause and sound their horn at a waypoint every so often.
            if self.horn_cooldown <= 0.0 and self.audio:
                self._play("truck_horn", volume=0.4)
                self.horn_cooldown = random.uniform(18.0, 40.0)
            return

        desired = math.atan2(dy, dx)
        # Trucks steer slowly, which reads as heavy and gives the player a chance.
        self.facing = rotate_towards(self.facing, desired, 1.3 * dt)
        self.horn_cooldown = max(0.0, self.horn_cooldown - dt)

        # Only drive along the heading so corners are taken wide.
        step = self.speed * dt
        vx = math.cos(self.facing) * step
        vy = math.sin(self.facing) * step

        if self.level is not None:
            if not self._blocked(self.x + vx, self.y):
                self.x += vx
            if not self._blocked(self.x, self.y + vy):
                self.y += vy
        else:
            self.x += vx
            self.y += vy

        self.wheel_phase += dt * 6.0
        self.sprite_facing = self.facing

    def _blocked(self, x, y):
        """Test the truck's footprint, not a point, against the world."""
        r = 0.9
        for ox, oy in ((r, 0), (-r, 0), (0, r), (0, -r), (0, 0)):
            if self.level.blocked_at(x + ox, y + oy, 0.35):
                return True
        return False

    def _engine_sound(self, dt, moving):
        if not self.audio or not self.engine_on:
            return
        key = "engine_move" if moving else "engine_idle"
        listener = self.listener
        if listener is None:
            self.audio.loop_start(key, volume=0.0)
            return
        lx, ly, facing = listener
        distance, pan = self.audio.pan_for((lx, ly), (self.x, self.y), facing)
        if distance > 26.0:
            self.audio.loop_update(key, distance, pan)
            return
        self.audio.loop_start(key)
        self.audio.loop_update(key, distance, pan)

    def _play(self, key, volume=None):
        if not self.audio:
            return
        listener = self.listener
        if listener is None:
            self.audio.play(key, 0.0, (0.707, 0.707), volume=volume)
            return
        lx, ly, facing = listener
        self.audio.play_at(key, (lx, ly), (self.x, self.y), facing,
                           volume=volume)

    def _run_over_check(self, player, dt):
        """A moving truck that reaches the player shoves and hurts them."""
        if not self.patrolling or self.speed <= 0.0:
            return
        distance = dist(self.x, self.y, player.x, player.y)
        if distance > 1.5:
            return
        # Push the player out of the truck's path and deal impact damage.
        push_angle = math.atan2(player.y - self.y, player.x - self.x)
        push = 2.6 * dt
        nx = player.x + math.cos(push_angle) * push
        ny = player.y + math.sin(push_angle) * push
        if self.level is None or not self.level.blocked_at(nx, player.y, 0.22):
            player.x = nx
        if self.level is None or not self.level.blocked_at(player.x, ny, 0.22):
            player.y = ny
        if distance < 1.1:
            player.take_damage(28.0 * dt * 3.0, self.x, self.y)

    # ---------------------------------------------------------------- damage --
    def take_damage(self, amount, source_x=None, source_y=None, cause="bullet"):
        """Returns True when the truck is destroyed by this hit."""
        if self.destroyed:
            return False
        self.health -= amount
        self._play("impact_metal", volume=0.5)
        if self.health <= 0.0:
            self.health = 0.0
            self.explode()
            return True
        return False

    def explode(self):
        if self.destroyed:
            return
        self.destroyed = True
        self.engine_on = False
        self.speed = 0.0
        self.burning_timer = 0.0
        self._play("truck_boom", volume=0.95)
        if self.audio:
            listener = self.listener
            if listener:
                self.audio.loop_stop("engine_idle", fade_ms=200)
                self.audio.loop_stop("engine_move", fade_ms=200)
            else:
                self.audio.loop_stop("engine_idle", fade_ms=200)
                self.audio.loop_stop("engine_move", fade_ms=200)

    def hit_test(self, px, py, radius=0.0):
        return dist(self.x, self.y, px, py) <= self.radius + radius

    @property
    def sprite_facing_current(self):
        return self.sprite_facing

    @property
    def block_radius(self):
        return self.radius
