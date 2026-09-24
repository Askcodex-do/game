"""Particle effects: muzzle flashes, explosions, smoke, blood and debris.

Particles are billboard sprites reused from the sprite library, so the effect
system costs almost nothing: it just moves a handful of Sprites around and
retires them. Everything is kept in a fixed-size pool to bound memory.
"""

import math
import random

from ..engine.sprites import Sprite
from ..utils import clamp


class Particle:
    __slots__ = ("x", "y", "z", "vx", "vy", "vz", "life", "max_life",
                 "sprite", "kind", "gravity", "drag", "spin", "start_scale",
                 "end_scale", "start_emit", "end_emit", "start_bright",
                 "end_bright", "fade")

    def __init__(self, kind, x, y, z, vx, vy, vz, life, sprite=None,
                 gravity=0.0, drag=0.9, start_scale=1.0, end_scale=1.4,
                 start_emit=0.9, end_emit=0.0, start_bright=1.0,
                 end_bright=0.6, fade=True):
        self.kind = kind
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.vx = float(vx)
        self.vy = float(vy)
        self.vz = float(vz)
        self.life = float(life)
        self.max_life = float(life)
        self.sprite = sprite
        self.gravity = gravity
        self.drag = drag
        self.start_scale = start_scale
        self.end_scale = end_scale
        self.start_emit = start_emit
        self.end_emit = end_emit
        self.start_bright = start_bright
        self.end_bright = end_bright
        self.spin = random.uniform(-3.0, 3.0)
        self.fade = fade

    @property
    def t(self):
        """Normalised age, 0 at birth and 1 at expiry."""
        return clamp(1.0 - self.life / self.max_life, 0.0, 1.0)

    @property
    def dead(self):
        return self.life <= 0.0


class ParticleSystem:
    """Fixed-capacity pool of particle effects bound to sprites."""

    MAX_PARTICLES = 220

    def __init__(self, art, level=None):
        self.art = art
        self.level = level
        self.particles = []
        self._pool = {}
        self._build_pool()

    def _build_pool(self):
        for name in ("flash", "smoke", "fireball"):
            frames = self.art.props[name][0]
            self._pool[name] = frames

    def _spawn_sprite(self, particle):
        frames = self._pool.get(particle.kind)
        if frames is None:
            return None
        sprite = Sprite(particle.x, particle.y, kind=particle.kind,
                        art_frames={0: frames}, height=0.4, width=0.4,
                        z_base=particle.z, emit=particle.start_emit)
        return sprite

    def _emit(self, particle):
        if len(self.particles) >= self.MAX_PARTICLES:
            return
        particle.sprite = self._spawn_sprite(particle)
        if particle.sprite is None:
            return
        self.particles.append(particle)

    # ------------------------------------------------------------ emitters ---
    def muzzle_flash(self, x, y, z, angle):
        forward = 0.5
        px = x + math.cos(angle) * forward
        py = y + math.sin(angle) * forward
        particle = Particle("flash", px, py, z, 0.0, 0.0, 0.0, 0.075,
                            start_scale=0.5, end_scale=0.7,
                            start_emit=1.0, end_emit=0.0)
        self._emit(particle)

    def bullet_impact(self, x, y, z, angle, surface="stone"):
        """A small puff plus a couple of sparks, tinted bronze for metal."""
        kind = "smoke" if surface == "stone" else "flash"
        for _ in range(3):
            spread = random.uniform(0.4, 1.1)
            a = angle + math.pi + random.uniform(-0.6, 0.6)
            vx = math.cos(a) * spread
            vy = math.sin(a) * spread
            particle = Particle(kind, x, y, z, vx, vy, random.uniform(0.2, 1.4),
                                random.uniform(0.12, 0.3),
                                start_scale=0.16, end_scale=0.5,
                                start_emit=0.7, end_emit=0.0, gravity=3.0)
            self._emit(particle)

    def blood(self, x, y, z, angle):
        for _ in range(6):
            a = angle + random.uniform(-0.9, 0.9)
            speed = random.uniform(0.8, 2.6)
            particle = Particle("smoke", x, y, z, math.cos(a) * speed,
                                math.sin(a) * speed, random.uniform(0.4, 2.0),
                                random.uniform(0.18, 0.4),
                                start_scale=0.12, end_scale=0.4,
                                start_emit=0.35, end_emit=0.0, gravity=7.0,
                                start_bright=0.8, end_bright=0.3)
            self._emit(particle)

    def explosion(self, x, y, z=0.5, radius=4.0):
        """Fireball core, expanding smoke ring and flying embers."""
        core = Particle("fireball", x, y, z, 0.0, 0.0, 0.6,
                        0.42, start_scale=1.6, end_scale=3.4,
                        start_emit=1.0, end_emit=0.5,
                        start_bright=1.0, end_bright=0.5)
        self._emit(core)
        for _ in range(10):
            a = random.uniform(0, math.tau)
            speed = random.uniform(1.0, 4.5)
            particle = Particle("fireball", x, y, z,
                                math.cos(a) * speed, math.sin(a) * speed,
                                random.uniform(0.5, 3.2),
                                random.uniform(0.2, 0.55),
                                start_scale=0.5, end_scale=1.2,
                                start_emit=0.95, end_emit=0.2,
                                gravity=5.0)
            self._emit(particle)
        for _ in range(14):
            a = random.uniform(0, math.tau)
            speed = random.uniform(0.5, 2.4)
            particle = Particle("smoke", x, y, z,
                                math.cos(a) * speed, math.sin(a) * speed,
                                random.uniform(0.6, 2.6),
                                random.uniform(0.8, 1.9),
                                start_scale=0.9, end_scale=4.2,
                                start_emit=0.5, end_emit=0.0,
                                start_bright=0.9, end_bright=0.35)
            self._emit(particle)

    def vehicle_wreck(self, x, y):
        """Continuous smoke handled by update; spawns the first heavy plume."""
        for _ in range(10):
            a = random.uniform(0, math.tau)
            r = random.uniform(0.0, 1.2)
            particle = Particle("smoke", x + math.cos(a) * r, y + math.sin(a) * r,
                                random.uniform(0.6, 1.4), 0.0, 0.0,
                                random.uniform(0.6, 1.4),
                                random.uniform(2.0, 4.0),
                                start_scale=1.4, end_scale=5.0,
                                start_emit=0.7, end_emit=0.0,
                                start_bright=0.8, end_bright=0.25)
            self._emit(particle)

    def spark_shower(self, x, y, z):
        for _ in range(8):
            a = random.uniform(0, math.tau)
            particle = Particle("flash", x, y, z, math.cos(a) * 1.6,
                                math.sin(a) * 1.6, random.uniform(0.5, 2.2),
                                random.uniform(0.15, 0.35),
                                start_scale=0.1, end_scale=0.25,
                                start_emit=0.9, end_emit=0.1, gravity=8.0)
            self._emit(particle)

    # ---------------------------------------------------------------- update --
    def update(self, dt):
        alive = []
        for particle in self.particles:
            particle.life -= dt
            if particle.dead:
                continue
            damping = particle.drag ** (dt * 60.0)
            particle.vx *= damping
            particle.vy *= damping
            particle.vz -= particle.gravity * dt
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.z += particle.vz * dt
            if particle.z < 0.05:
                particle.z = 0.05
                particle.vz = 0.0
            alive.append(particle)
        self.particles = alive

    def sprites(self):
        """Project every particle into a Sprite ready for the renderer."""
        out = []
        for particle in self.particles:
            sprite = particle.sprite
            if sprite is None:
                continue
            t = particle.t
            scale = particle.start_scale + (particle.end_scale - particle.start_scale) * t
            sprite.x = particle.x
            sprite.y = particle.y
            sprite.z_base = particle.z
            sprite.height = 0.42 * scale
            sprite.width = 0.42 * scale
            sprite.emit = particle.start_emit + (particle.end_emit - particle.start_emit) * t
            sprite.brightness = particle.start_bright + (particle.end_bright - particle.start_bright) * t
            sprite.opacity = (1.0 - t) if particle.fade else 1.0
            out.append(sprite)
        return out

    def clear(self):
        self.particles = []

    def __len__(self):
        return len(self.particles)
