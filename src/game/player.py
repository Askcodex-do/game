"""Player controller: movement, collision, stance, health and noise output."""

import math

from ..config import (CROUCH_EYE, CROUCH_SPEED, MAX_ARMOR, MAX_HEALTH,
                      NOISE_CROUCH, NOISE_RUN, NOISE_WALK, PLAYER_EYE,
                      PLAYER_RADIUS, RUN_SPEED, STRAFE_SPEED, WALK_SPEED)
from ..utils import clamp, move_towards


class Player:
    """First-person agent state.

    Movement uses axis-separated collision so sliding along walls feels right
    without needing a physics engine. Every action that makes noise emits a
    `noise` event which the AI layer consumes.
    """

    def __init__(self, x, y, angle):
        self.x = float(x)
        self.y = float(y)
        self.angle = float(angle)
        self.pitch = 0.0
        self.eye_z = PLAYER_EYE
        self.target_eye = PLAYER_EYE

        self.vel_x = 0.0
        self.vel_y = 0.0
        self.height = 1.75

        self.health = MAX_HEALTH
        self.armor = 0
        self.alive = True

        self.stamina = 100.0
        self.crouching = False
        self.sprinting = False
        self.moving = False
        self.speed = 0.0

        # View bob and recoil, both expressed as pixel offsets.
        self.bob_phase = 0.0
        self.bob_offset = 0.0
        self.recoil_pitch = 0.0
        self.recoil_yaw = 0.0
        self.land_kick = 0.0

        self.step_timer = 0.0
        self.step_index = 0
        self.noise_events = []
        self.footstep_surface = "concrete"

        self.last_damage_dir = 0.0
        self.damage_flash = 0.0
        self.death_timer = 0.0

    # ---------------------------------------------------------- properties --
    @property
    def stance_noise(self):
        if self.crouching:
            return NOISE_CROUCH
        if self.sprinting:
            return NOISE_RUN
        return NOISE_WALK

    # ------------------------------------------------------------ movement --
    def update(self, dt, level, input_state, audio=None):
        """Advance the player one tick.

        `input_state` is a dict: move_x (strafe, +right), move_y (forward),
        run (bool), crouch (bool), look_dx, look_dy (radians).
        """
        if not self.alive:
            self.death_timer += dt
            # Settle to the floor when dead.
            self.target_eye = 0.28
            self.eye_z = move_towards(self.eye_z, self.target_eye, dt * 1.4)
            return

        # ---- look ----
        self.angle += input_state.get("look_dx", 0.0)
        self.angle %= math.tau
        self.pitch = clamp(self.pitch + input_state.get("look_dy", 0.0), -140.0, 140.0)

        # ---- stance ----
        self.crouching = input_state.get("crouch", False)
        wants_run = input_state.get("run", False) and not self.crouching
        move_x = input_state.get("move_x", 0.0)
        move_y = input_state.get("move_y", 0.0)
        magnitude = math.hypot(move_x, move_y)
        self.moving = magnitude > 0.01

        # Sprinting requires stamina and forward input.
        if wants_run and self.moving and self.stamina > 1.0 and move_y > 0.05:
            self.sprinting = True
        else:
            self.sprinting = False

        if self.sprinting:
            self.stamina = max(0.0, self.stamina - dt * 18.0)
        else:
            self.stamina = min(100.0, self.stamina + dt * (11.0 if self.moving else 16.0))

        # ---- speed target ----
        base = CROUCH_SPEED if self.crouching else (RUN_SPEED if self.sprinting else WALK_SPEED)
        if magnitude > 1.0:
            magnitude = 1.0
        target_speed = base * magnitude
        # Strafing is a touch slower than moving forward.
        if abs(move_y) < abs(move_x):
            target_speed *= (STRAFE_SPEED / max(WALK_SPEED, 1e-6))
        self.speed = target_speed

        # ---- direction in world space ----
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        fwd_x, fwd_y = cos_a, sin_a
        right_x, right_y = -sin_a, cos_a
        if magnitude > 1e-6:
            norm = 1.0 / math.hypot(move_x, move_y)
            dir_x = (fwd_x * move_y + right_x * move_x) * norm
            dir_y = (fwd_y * move_y + right_y * move_x) * norm
        else:
            dir_x = dir_y = 0.0

        vx = dir_x * self.speed
        vy = dir_y * self.speed

        # ---- axis-separated collision ----
        radius = PLAYER_RADIUS
        new_x = self.x + vx * dt
        if not level.blocked_at(new_x, self.y, radius):
            self.x = new_x
        else:
            # Try a nudge to slip around corners instead of sticking.
            if not level.blocked_at(new_x, self.y + 0.05, radius):
                self.y += 0.05 * min(1.0, dt * 20.0)
            elif not level.blocked_at(new_x, self.y - 0.05, radius):
                self.y -= 0.05 * min(1.0, dt * 20.0)

        new_y = self.y + vy * dt
        if not level.blocked_at(self.x, new_y, radius):
            self.y = new_y
        else:
            if not level.blocked_at(self.x + 0.05, new_y, radius):
                self.x += 0.05 * min(1.0, dt * 20.0)
            elif not level.blocked_at(self.x - 0.05, new_y, radius):
                self.x -= 0.05 * min(1.0, dt * 20.0)

        # ---- eye height / head bob ----
        self.target_eye = CROUCH_EYE if self.crouching else PLAYER_EYE
        self.eye_z = move_towards(self.eye_z, self.target_eye, dt * 3.2)

        if self.moving and not self.crouching:
            self.bob_phase += dt * (12.0 if self.sprinting else 8.5)
        else:
            self.bob_phase += dt * 3.0
        amplitude = 0.0
        if self.moving:
            amplitude = 5.0 if self.sprinting else 3.0
            if self.crouching:
                amplitude = 1.4
        self.bob_offset = math.sin(self.bob_phase * 2.0) * amplitude * (1.0 - self.eye_crouch_mix())

        # ---- recoil recovery ----
        self.recoil_pitch *= math.exp(-dt * 9.0)
        self.recoil_yaw *= math.exp(-dt * 9.0)
        self.land_kick *= math.exp(-dt * 8.0)

        # ---- footsteps and noise ----
        self._emit_footsteps(dt, level, audio)

        self.damage_flash = max(0.0, self.damage_flash - dt * 2.4)

    def eye_crouch_mix(self):
        span = PLAYER_EYE - CROUCH_EYE
        if span <= 1e-6:
            return 0.0
        return clamp((PLAYER_EYE - self.eye_z) / span, 0.0, 1.0)

    def _emit_footsteps(self, dt, level, audio):
        if not self.moving:
            self.step_timer = 0.0
            return
        interval = 0.42 if self.crouching else (0.30 if self.sprinting else 0.40)
        self.step_timer += dt
        if self.step_timer < interval:
            return
        self.step_timer = 0.0
        self.step_index = (self.step_index + 1) % 3

        tile = level.tile_at(self.x, self.y)
        surface = self._surface_for(tile)
        self.footstep_surface = surface
        noise = self.stance_noise
        self.noise_events.append({
            "x": self.x, "y": self.y, "radius": noise, "kind": "footstep",
            "loudness": noise,
        })
        if audio is not None:
            key = {"concrete": "step_concrete", "gravel": "step_gravel",
                   "grass": "step_grass", "metal": "step_metal"}[surface]
            audio.play(key, 0.0, (0.707, 0.707),
                       volume=0.30 if self.crouching else 0.42)

    @staticmethod
    def _surface_for(tile):
        # Interior floors are concrete/steel, the yard is gravel.
        if tile in (3, 7, 10):
            return "concrete"
        if tile == 9:
            return "grass"
        return "gravel"

    # -------------------------------------------------------------- damage --
    def take_damage(self, amount, source_x=None, source_y=None):
        if not self.alive:
            return False
        # Armor soaks two thirds of incoming damage until it runs out.
        if self.armor > 0:
            absorbed = min(self.armor, amount * 0.66)
            self.armor -= absorbed
            amount -= absorbed
        self.health -= amount
        self.damage_flash = min(1.0, self.damage_flash + amount / 45.0)
        if source_x is not None:
            self.last_damage_dir = math.atan2(source_y - self.y, source_x - self.x)
        if self.health <= 0.0:
            self.health = 0.0
            self.alive = False
            return True
        return False

    def heal(self, amount):
        self.health = min(MAX_HEALTH, self.health + amount)

    def add_armor(self, amount):
        self.armor = min(MAX_ARMOR, self.armor + amount)

    def apply_recoil(self, pitch_kick, yaw_kick):
        self.recoil_pitch += pitch_kick
        self.recoil_yaw += yaw_kick

    def consume_noise(self):
        events = self.noise_events
        self.noise_events = []
        return events

    @property
    def total_view_pitch(self):
        """Pixel pitch fed to the camera: look pitch plus bob and recoil."""
        return (self.pitch - self.bob_offset - self.land_kick
                + self.recoil_pitch * 120.0)

    @property
    def total_view_angle(self):
        return self.angle + self.recoil_yaw
