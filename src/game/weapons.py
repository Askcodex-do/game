"""Weapon handling, hitscan resolution, grenades and projectile effects."""

import math
import random

from ..config import (GRENADE_FUSE, GRENADE_RADIUS, HITSCAN_RANGE,
                      WEAPONS, WEAPON_ORDER)
from ..utils import clamp, dist, line_of_sight


class Weapon:
    """One held weapon: ammo, timers and firing logic."""

    def __init__(self, key):
        self.key = key
        self.spec = dict(WEAPONS[key])
        self.mag = self.spec["mag_size"]
        self.reserve = self.spec["reserve"]
        self.cooldown = 0.0
        self.reloading = False
        self.reload_timer = 0.0
        self.reload_stage = 0
        self.trigger_held = False

    @property
    def name(self):
        return self.spec["name"]

    @property
    def melee(self):
        return self.spec.get("melee", False)

    @property
    def thrown(self):
        return self.spec.get("thrown", False)

    @property
    def scoped(self):
        return self.spec.get("scoped", False)

    @property
    def infinite(self):
        # The knife and the throwing grenade pouch never run dry.
        return self.melee or self.thrown and False

    @property
    def can_fire(self):
        if self.reloading or self.cooldown > 0.0:
            return False
        if self.melee:
            return True
        return self.mag > 0

    @property
    def needs_reload(self):
        if self.melee:
            return False
        return self.mag <= 0 and self.reserve > 0

    def start_reload(self):
        if self.melee or self.reloading:
            return False
        if self.reserve <= 0 or self.mag >= self.spec["mag_size"]:
            return False
        self.reloading = True
        self.reload_timer = 0.0
        self.reload_stage = 0
        return True

    def update(self, dt):
        if self.cooldown > 0.0:
            self.cooldown = max(0.0, self.cooldown - dt)
        if self.reloading:
            self.reload_timer += dt
            total = self.spec["reload_time"]
            # Two audible stages: magazine out/in, then charging the bolt.
            if self.reload_stage == 0 and self.reload_timer >= total * 0.15:
                self.reload_stage = 1
            elif self.reload_stage == 1 and self.reload_timer >= total * 0.6:
                self.reload_stage = 2
            elif self.reload_stage == 2 and self.reload_timer >= total * 0.85:
                self.reload_stage = 3
            if self.reload_timer >= total:
                need = self.spec["mag_size"] - self.mag
                take = min(need, self.reserve)
                self.mag += take
                self.reserve -= take
                self.reloading = False
                self.reload_timer = 0.0
                self.reload_stage = 0
                return "reload_done"
        return None

    def consume_round(self):
        if not self.melee:
            self.mag = max(0, self.mag - 1)
        self.cooldown = self.spec["fire_period"]


class ShotResult:
    """Outcome of a single hitscan or explosion, consumed by the game layer."""

    __slots__ = ("hit", "target", "damage", "point", "normal", "killed",
                 "headshot", "surface")

    def __init__(self, hit=False, target=None, damage=0.0, point=None,
                 headshot=False, surface="stone", killed=False):
        self.hit = hit
        self.target = target
        self.damage = damage
        self.point = point
        self.headshot = headshot
        self.surface = surface
        self.killed = killed


class Grenade:
    """Physics-light thrown grenade: gravity, bounces, then a radial blast."""

    def __init__(self, x, y, z, vx, vy, vz, owner="player"):
        self.x = x
        self.y = y
        self.z = z
        self.vx = vx
        self.vy = vy
        self.vz = vz
        self.fuse = GRENADE_FUSE
        self.exploded = False
        self.owner = owner
        self.bounces = 0
        self.spin = 0.0

    def update(self, dt, level):
        """Integrate one step. Returns 'bounce' the first time it lands."""
        self.fuse -= dt
        if self.fuse <= 0.0:
            self.exploded = True
            return None
        self.spin += dt * 8.0

        self.vz -= 9.8 * dt
        event = None

        new_x = self.x + self.vx * dt
        new_y = self.y + self.vy * dt
        new_z = self.z + self.vz * dt

        # Vertical: bounce off the floor and a low ceiling.
        if new_z <= 0.06:
            new_z = 0.06
            self.vz = -self.vz * 0.34
            self.vx *= 0.62
            self.vy *= 0.62
            if abs(self.vz) < 1.2:
                self.vz = 0.0
            event = "bounce"
        elif new_z > 2.4:
            new_z = 2.4
            self.vz = -abs(self.vz) * 0.3

        # Horizontal: reflect off whichever axis is blocked.
        radius = 0.12
        if level.blocked_at(new_x, new_y, radius):
            if not level.blocked_at(new_x, self.y, radius):
                self.x = new_x
                self.vy = -self.vy * 0.42
                event = "bounce"
            elif not level.blocked_at(self.x, new_y, radius):
                self.y = new_y
                self.vx = -self.vx * 0.42
                event = "bounce"
            else:
                self.vx = -self.vx * 0.42
                self.vy = -self.vy * 0.42
                event = "bounce"
        else:
            self.x = new_x
            self.y = new_y

        self.z = new_z
        if event == "bounce":
            self.bounces += 1
        return event


class WeaponSystem:
    """Owns the player's arsenal and resolves every shot."""

    def __init__(self, audio=None):
        self.audio = audio
        self.weapons = {key: Weapon(key) for key in WEAPON_ORDER}
        # The knife and pistol are always available; better gear is picked up.
        self.owned = {"knife", "pistol"}
        self.current_key = "pistol"
        self.grenades = []
        self.pending_shots = []
        self.bullet_tracers = []
        self.muzzle_timer = 0.0
        self.scope_active = False
        self.scope_zoom = 0.0
        self.last_shot_result = None
        self.shots_fired = 0
        self.hits = 0

    # ------------------------------------------------------------- selection --
    @property
    def current(self):
        return self.weapons[self.current_key]

    def owned_keys(self):
        return [k for k in WEAPON_ORDER if k in self.owned]

    def give(self, key):
        """Pick up a weapon. Returns True if it was newly acquired."""
        if key not in self.weapons:
            return False
        new = key not in self.owned
        self.owned.add(key)
        return new

    def add_ammo(self, key, amount):
        if key not in self.weapons:
            return
        weapon = self.weapons[key]
        weapon.reserve += amount

    def switch_to(self, key):
        if key not in self.owned or key == self.current_key:
            return False
        self.current_key = key
        self.scope_active = False
        return True

    def cycle(self, direction=1):
        keys = self.owned_keys()
        if not keys:
            return False
        idx = keys.index(self.current_key) if self.current_key in keys else 0
        idx = (idx + direction) % len(keys)
        self.current_key = keys[idx]
        self.scope_active = False
        return True

    def select_index(self, index):
        keys = self.owned_keys()
        if 0 <= index < len(keys):
            return self.switch_to(keys[index])
        return False

    # ---------------------------------------------------------------- firing --
    def trigger_down(self, player, level):
        weapon = self.current
        weapon.trigger_held = True
        if weapon.melee:
            return self._melee_attack(player, level)
        if weapon.thrown:
            return self._throw_grenade(player)
        if weapon.reloading:
            return None
        if weapon.mag <= 0:
            if weapon.reserve > 0:
                self._begin_reload()
            else:
                if self.audio:
                    self.audio.play("dry_fire", 0.0)
            return None
        return self._fire_hitscan(player, level)

    def trigger_up(self):
        self.current.trigger_held = False

    def update(self, dt, player, level, enemies, breakables=None):
        """Advance timers, handle automatic fire, grenades and tracers."""
        weapon = self.current
        for key in self.owned_keys():
            event = self.weapons[key].update(dt)
            if event == "reload_done" and key == self.current_key and self.audio:
                self.audio.play("reload_charge", 0.0)

        self.muzzle_timer = max(0.0, self.muzzle_timer - dt)

        # Automatic weapons keep firing while the trigger is held.
        if (weapon.spec.get("automatic") and weapon.trigger_held
                and player.alive and not weapon.reloading):
            if weapon.cooldown <= 0.0:
                self._fire_hitscan(player, level)

        # Scoped view eases in and out.
        if weapon.scoped and self.scope_active and player.alive:
            self.scope_zoom = min(1.0, self.scope_zoom + dt * 4.0)
        else:
            self.scope_zoom = max(0.0, self.scope_zoom - dt * 5.0)

        # Grenade simulation and detonation.
        for grenade in list(self.grenades):
            event = grenade.update(dt, level)
            if event == "bounce" and self.audio:
                self.audio.play("grenade_bounce", 0.6, (0.707, 0.707), volume=0.3)
            if grenade.exploded:
                self.grenades.remove(grenade)
                self._detonate(grenade, player, level, enemies)

        # Tracer lifetime (purely visual).
        for tracer in list(self.bullet_tracers):
            tracer["life"] -= dt
            if tracer["life"] <= 0.0:
                self.bullet_tracers.remove(tracer)

        if breakables:
            self._update_breakables(dt, breakables)

    def _begin_reload(self):
        if self.current.start_reload():
            if self.audio:
                self.audio.play("reload_out", 0.0)

    def _fire_hitscan(self, player, level):
        weapon = self.current
        if not weapon.can_fire:
            return None
        weapon.consume_round()
        self.shots_fired += 1
        self.muzzle_timer = 0.055

        origin_x, origin_y = player.x, player.y
        base_angle = player.angle
        results = []

        pellets = weapon.spec.get("pellets", 1)
        for _ in range(pellets):
            spread = weapon.spec["spread"]
            # Moving and standing both widen the cone.
            movement_penalty = 0.0
            if player.moving and not player.crouching:
                movement_penalty = 0.012 if not player.sprinting else 0.028
            if player.crouching:
                spread *= 0.6
            angle = base_angle + random.gauss(0.0, spread + movement_penalty + 1e-4)
            result = self._trace_shot(origin_x, origin_y, angle, weapon, level,
                                      player)
            results.append(result)

        # Audio: weapon report plus a distant reporting crack for the AI layer.
        if self.audio:
            key = {"pistol": "gun_pistol", "smg": "gun_smg",
                   "shotgun": "gun_shotgun", "sniper": "gun_sniper"}.get(weapon.key)
            if key:
                self.audio.play(key, 0.0)
        player.apply_recoil(weapon.spec["recoil"] * random.uniform(0.8, 1.2),
                            weapon.spec["recoil"] * random.uniform(-0.6, 0.6))

        player.noise_events.append({
            "x": player.x, "y": player.y, "radius": weapon.spec["noise"],
            "kind": "gunshot", "loudness": weapon.spec["noise"],
        })

        hit_any = any(r.hit for r in results)
        if hit_any:
            self.hits += 1
        self.pending_shots.extend(results)
        self.last_shot_result = results[0] if results else None
        return results[0] if results else None

    def _trace_shot(self, ox, oy, angle, weapon, level, player):
        """Walk the ray and return the first thing it strikes."""
        max_range = weapon.spec.get("range", HITSCAN_RANGE)
        step = 0.09
        dx = math.cos(angle)
        dy = math.sin(angle)
        travel = 0.0
        while travel < max_range:
            travel += step
            px = ox + dx * travel
            py = oy + dy * travel
            if level.is_solid(px, py):
                if self.audio:
                    self.audio.play("impact_stone", 0.0, volume=0.28)
                return ShotResult(hit=False, point=(px, py), surface="stone")
            hit = self._query_targets(px, py, weapon, level, player)
            if hit is not None:
                return hit
        return ShotResult(hit=False)

    def _query_targets(self, px, py, weapon, level, player):
        """Check bullets against the game's target list, if one is registered."""
        resolver = getattr(self, "target_resolver", None)
        if resolver is None:
            return None
        target = resolver(px, py)
        if target is None:
            return None
        damage = weapon.spec["damage"]
        headshot = False
        damage, headshot = self._apply_range_falloff(weapon, target, damage)
        return ShotResult(hit=True, target=target, damage=damage,
                          point=(px, py), headshot=headshot, surface="flesh")

    @staticmethod
    def _apply_range_falloff(weapon, target, damage):
        """Long shots with an SMG hurt less; sniper rounds do not care."""
        if weapon.key == "sniper":
            return damage, False
        falloff = {"pistol": 0.75, "smg": 0.62, "shotgun": 0.45}.get(weapon.key, 0.8)
        distance = getattr(target, "last_hit_distance", 0.0)
        scaled = damage * (1.0 - (1.0 - falloff) * clamp(distance / 24.0, 0.0, 1.0))
        return scaled, False

    def _melee_attack(self, player, level):
        weapon = self.current
        if not weapon.can_fire:
            return None
        weapon.consume_round()
        if self.audio:
            self.audio.play("knife_swing", 0.0)
        reach = weapon.spec.get("melee_range", 1.4)
        px = player.x + math.cos(player.angle) * reach * 0.6
        py = player.y + math.sin(player.angle) * reach * 0.6
        resolver = getattr(self, "target_resolver", None)
        target = resolver(px, py, reach) if resolver else None
        if target is not None:
            result = ShotResult(hit=True, target=target,
                                damage=weapon.spec["damage"],
                                point=(px, py), killed=False, surface="flesh")
            self.pending_shots.append(result)
            if self.audio:
                self.audio.play("knife_hit", 0.0)
            return result
        return None

    def _throw_grenade(self, player):
        weapon = self.current
        if not weapon.can_fire:
            return None
        if weapon.mag <= 0:
            if self.audio:
                self.audio.play("dry_fire", 0.0)
            return None
        weapon.consume_round()
        if self.audio:
            self.audio.play("grenade_pin", 0.0)
        # Throw along the look direction, with a modest upward arc.
        speed = 11.0
        pitch_factor = clamp(-player.pitch / 140.0, -0.35, 0.5)
        vx = math.cos(player.angle) * speed * math.cos(pitch_factor)
        vy = math.sin(player.angle) * speed * math.cos(pitch_factor)
        vz = speed * math.sin(pitch_factor) + 1.6
        grenade = Grenade(player.x + vx * 0.04, player.y + vy * 0.04,
                          1.2, vx, vy, vz, owner="player")
        self.grenades.append(grenade)
        player.noise_events.append({
            "x": player.x, "y": player.y, "radius": 4.0,
            "kind": "throw", "loudness": 4.0,
        })
        return None

    def _detonate(self, grenade, player, level, enemies):
        """Apply a radial blast with line-of-sight cover checking."""
        if self.audio:
            self.audio.play_at("grenade_boom", (player.x, player.y),
                               (grenade.x, grenade.y), player.angle)
        player.noise_events.append({
            "x": grenade.x, "y": grenade.y, "radius": 26.0,
            "kind": "explosion", "loudness": 26.0,
        })
        self.explosions = getattr(self, "explosions", [])
        self.explosions.append({
            "x": grenade.x, "y": grenade.y, "z": grenade.z,
            "radius": GRENADE_RADIUS, "life": 0.42, "max_life": 0.42,
        })

        def blocked(bx, by):
            return level.is_solid(bx, by)

        # Splash damage to listed targets.
        for target in (enemies or []):
            if getattr(target, "dead", False):
                continue
            distance = dist(grenade.x, grenade.y, target.x, target.y)
            if distance > GRENADE_RADIUS:
                continue
            if not line_of_sight(grenade.x, grenade.y, target.x, target.y,
                                 blocked, step=0.35):
                continue
            falloff = 1.0 - (distance / GRENADE_RADIUS) ** 1.5
            damage = WEAPONS["grenade"]["damage"] * falloff
            if hasattr(target, "take_damage"):
                target.take_damage(damage, grenade.x, grenade.y, "explosion")
                target.alert_to(grenade.x, grenade.y, "explosion")

        # The player can cook themselves too.
        distance = dist(grenade.x, grenade.y, player.x, player.y)
        if distance <= GRENADE_RADIUS:
            if line_of_sight(grenade.x, grenade.y, player.x, player.y,
                             blocked, step=0.35):
                falloff = 1.0 - (distance / GRENADE_RADIUS) ** 1.5
                player.take_damage(WEAPONS["grenade"]["damage"] * falloff * 0.7,
                                   grenade.x, grenade.y)

    @staticmethod
    def _update_breakables(dt, breakables):
        for entity in breakables:
            if getattr(entity, "alive", True):
                entity.update(dt)

    # ---------------------------------------------------------------- state --
    def pending_hits(self):
        results = self.pending_shots
        self.pending_shots = []
        return results

    def clear_explosions(self):
        return getattr(self, "explosions", [])

    def toggle_scope(self):
        if self.current.scoped:
            self.scope_active = not self.scope_active
            return self.scope_active
        return False

    @property
    def total_ammo(self):
        weapon = self.current
        if weapon.melee:
            return -1
        return weapon.mag + weapon.reserve
