"""Security cameras: sweeping vision cones, detection meter and the alarm.

Cameras are the stage's pressure valve. A camera that keeps eyes on the player
fills a detection meter; when it saturates, the depot alarm trips, guards are
told exactly where the player is, and the alert music takes over.

Cameras can be destroyed, which is one of the mission objectives, and they can
be blinded for a few seconds by shooting out their lens housing.
"""

import math
import random

from ..config import (CAMERA_ALERT_TIME, CAMERA_FOV, CAMERA_RANGE,
                      CAMERA_SWEEP, CAMERA_SWEEP_SPEED)
from ..utils import angle_difference, clamp, dist, line_of_sight


class SecurityCamera:
    """One panning camera on a pole.

    `facing` is the centre of its sweep; the live look direction oscillates
    around it. `detection` runs 0..1 and trips the alarm at 1.
    """

    # state constants, mirrored by the sprite art indices
    IDLE, SWEEPING, ALERT, DESTROYED = 0, 1, 2, 3

    def __init__(self, x, y, facing, name="Camera", level=None, audio=None):
        self.x = float(x)
        self.y = float(y)
        self.z_base = 2.0
        self.facing = float(facing)
        self.base_facing = float(facing)
        self.name = name
        self.level = level
        self.audio = audio

        self.sweep_phase = random.uniform(0.0, math.tau)
        self.look_angle = self.facing
        # Per-camera sweep tuning, so a fixed-mount camera is just sweep_range=0.
        self.sweep_range = CAMERA_SWEEP
        self.sweep_speed = CAMERA_SWEEP_SPEED
        self.detection = 0.0
        self.state = self.IDLE
        self.destroyed = False
        self.destroy_timer = 0.0
        self.health = 40.0
        self.alarm_raised = False
        self.beep_cooldown = 0.0
        self.blinded_timer = 0.0
        self.spark_timer = 0.0
        self.listener = None
        self.sprite = None

    # ------------------------------------------------------------ accessors --
    @property
    def alive(self):
        return not self.destroyed

    @property
    def height(self):
        return 0.55

    @property
    def eye_height(self):
        return 2.0

    @property
    def detection_ratio(self):
        return clamp(self.detection / CAMERA_ALERT_TIME, 0.0, 1.0)

    # ------------------------------------------------------------ perception --
    def can_see(self, px, py, player=None, level=None):
        if self.destroyed or self.blinded_timer > 0.0:
            return False
        level = level or self.level
        distance = dist(self.x, self.y, px, py)
        if distance > CAMERA_RANGE:
            return False
        angle_to = math.atan2(py - self.y, px - self.x)
        if abs(angle_difference(angle_to, self.look_angle)) > CAMERA_FOV * 0.5:
            return False
        # Movement makes the player easier to pick out against a still background.
        if player is not None:
            if getattr(player, "crouching", False) and distance > CAMERA_RANGE * 0.6:
                return False
        if level is not None:
            def blocked(bx, by):
                return level.is_solid(bx, by)
            return line_of_sight(self.x, self.y, px, py, blocked, step=0.34)
        return True

    # ---------------------------------------------------------------- update --
    def update(self, dt, player, level=None, audio=None):
        if audio is not None:
            self.audio = audio
        if self.destroyed:
            self.destroy_timer += dt
            self.spark_timer = max(0.0, self.spark_timer - dt)
            if self.spark_timer <= 0.0 and self.destroy_timer < 3.0:
                self.spark_timer = random.uniform(0.25, 0.9)
            return
        if self.blinded_timer > 0.0:
            self.blinded_timer = max(0.0, self.blinded_timer - dt)

        self.beep_cooldown = max(0.0, self.beep_cooldown - dt)
        self.sweep_phase += dt * self.sweep_speed
        offset = math.sin(self.sweep_phase) * self.sweep_range
        self.look_angle = self.base_facing + offset

        sees = player.alive and self.can_see(player.x, player.y, player, level)
        if sees:
            self.detection = min(CAMERA_ALERT_TIME, self.detection + dt)
            if self.state != self.ALERT:
                self.state = self.ALERT
                if self.beep_cooldown <= 0.0 and self.audio:
                    self.beep_cooldown = 0.55
                    self._play("camera_beep")
        else:
            # Detection decays, but slower than it builds.
            self.detection = max(0.0, self.detection - dt * 0.55)
            if self.detection <= 0.0:
                self.state = self.SWEEPING if abs(offset) > 0.08 else self.IDLE

        if self.detection >= CAMERA_ALERT_TIME and not self.alarm_raised:
            self.alarm_raised = True
            return "alarm"
        return None

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

    # ---------------------------------------------------------------- damage --
    def take_damage(self, amount, source_x=None, source_y=None, cause="bullet"):
        if self.destroyed:
            return False
        self.health -= amount
        if self.health <= 0.0:
            self.destroy()
            return True
        # A hit blinds it briefly: a player can shoot a lens to buy a window.
        self.blinded_timer = max(self.blinded_timer, 2.5)
        self.detection *= 0.4
        self._play("clang", volume=0.4)
        return False

    def destroy(self):
        if self.destroyed:
            return
        self.destroyed = True
        self.state = self.DESTROYED
        self.detection = 0.0
        self.alarm_raised = False
        self._play("camera_break", volume=0.75)

    def reset_alarm(self):
        self.alarm_raised = False
        self.detection = 0.0
        self.state = self.SWEEPING

    def hit_test(self, px, py, radius=0.0):
        return dist(self.x, self.y, px, py) <= 0.30 + radius

    @property
    def sprite_state(self):
        """Art index the renderer should show."""
        if self.destroyed:
            return self.DESTROYED
        if self.state == self.ALERT:
            return self.ALERT
        if abs(math.sin(self.sweep_phase)) > 0.05:
            return self.SWEEPING
        return self.IDLE

    @property
    def sprite_facing(self):
        return self.look_angle


class AlarmSystem:
    """Stage-wide alarm state triggered by cameras, explosions or bodies.

    Having a single owner means the alarm can only be raised once per stage
    segment, and cancelling it (by disabling every camera) is a real reward.
    """

    def __init__(self, audio=None):
        self.audio = audio
        self.active = False
        self.timer = 0.0
        self.trigger_count = 0
        self.just_triggered = False
        self.just_cancelled = False
        self.source = (0.0, 0.0)

    def trigger(self, x=0.0, y=0.0):
        if self.active:
            return False
        self.active = True
        self.timer = 0.0
        self.trigger_count += 1
        self.source = (x, y)
        self.just_triggered = True
        if self.audio:
            self.audio.loop_start("alarm")
            self.audio.play("alarm_cancel", 0.0, volume=0.0)
        return True

    def cancel(self, silent=False):
        if not self.active:
            return False
        self.active = False
        self.just_cancelled = True
        if self.audio:
            self.audio.loop_stop("alarm", fade_ms=400)
            if not silent:
                self.audio.play("alarm_cancel", 0.0)
        return True

    def update(self, dt, cameras=None):
        self.just_triggered = False
        self.just_cancelled = False
        if not self.active:
            return
        self.timer += dt
        # Disabling every camera silences the alarm: the player's reward for
        # completing the camera objective.
        if cameras is not None and cameras and all(c.destroyed for c in cameras):
            self.cancel()
            return
        # The alarm relaxes after a long stretch of no new sightings.
        if self.timer > 75.0:
            self.cancel()
