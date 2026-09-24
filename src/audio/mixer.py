"""Audio manager: lazy sound building, 3D attenuation and music playback."""

import math
import random

import pygame

from ..config import (AUDIO_CHANNELS, MUSIC_VOLUME, SAMPLE_RATE,
                      SFX_VOLUME)
from . import music
from .registry import LOOP_REGISTRY, SFX_REGISTRY
from .synth import stereo

# Distance model for positional sound.
REF_DISTANCE = 1.6
ROLLOFF = 1.15
MAX_AUDIBLE = 28.0


class AudioManager:
    """Owns every Sound object and every channel.

    Sounds are synthesised on first use, which keeps startup fast and memory
    low: the menu never pays for the truck engine, and vice versa.
    """

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.available = False
        self._sfx = {}
        self._loops = {}
        self._music = {}
        self._music_names = {}
        self._loop_channels = {}
        self._music_channel = None
        self._current_music = None
        self.muted = False
        self._master_volume = 1.0
        self._last_play_time = {}
        if enabled:
            self._init_mixer()

    # ------------------------------------------------------------ lifecycle --
    def _init_mixer(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(SAMPLE_RATE, -16, 2, 512)
                pygame.mixer.init(SAMPLE_RATE, -16, 2, 512)
            pygame.mixer.set_num_channels(AUDIO_CHANNELS)
            # Reserve the last few channels for music and looping beds.
            pygame.mixer.set_reserved(6)
            self.available = True
        except pygame.error:
            self.available = False
            self.enabled = False

    def shutdown(self):
        if not self.available:
            return
        try:
            pygame.mixer.stop()
            pygame.mixer.quit()
        except pygame.error:
            pass
        self.available = False

    # ---------------------------------------------------------- sound cache --
    def _build(self, key):
        if key in self._sfx:
            return self._sfx[key]
        builder, vol = SFX_REGISTRY[key]
        sound = self._make_sound(builder())
        self._sfx[key] = (sound, vol)
        return self._sfx[key]

    def _build_loop(self, key):
        if key in self._loops:
            return self._loops[key]
        builder, vol = LOOP_REGISTRY[key]
        sound = self._make_sound(builder())
        self._loops[key] = (sound, vol)
        return self._loops[key]

    @staticmethod
    def _make_sound(samples):
        frames = stereo(samples)
        try:
            return pygame.sndarray.make_sound(frames)
        except (pygame.error, ValueError):
            # Rarely, mixer format negotiation fails; fall back to silence.
            return None

    def preload(self, keys):
        for key in keys:
            if key in SFX_REGISTRY:
                self._build(key)

    # --------------------------------------------------------------- playing --
    def _attenuation(self, distance):
        if distance <= REF_DISTANCE:
            return 1.0
        if distance >= MAX_AUDIBLE:
            return 0.0
        return REF_DISTANCE / (REF_DISTANCE + ROLLOFF * (distance - REF_DISTANCE))

    def _pan(self, dx, dy, facing):
        """Return a (left, right) gain pair for a world-space offset.

        `facing` is the player's look angle; dy grows downward in world space.
        """
        if dx == 0.0 and dy == 0.0:
            return (0.707, 0.707)
        angle_to = math.atan2(dy, dx)
        rel = angle_to - facing
        # Right vector in this coordinate system is (-sin, cos) for increasing angle.
        rightness = math.sin(rel)
        left = math.sqrt(max(0.0, 0.5 * (1.0 - rightness)))
        right = math.sqrt(max(0.0, 0.5 * (1.0 + rightness)))
        return (left, right)

    def play(self, key, distance=0.0, pan=(0.707, 0.707), volume=None,
             pitch_variation=0.0):
        """Play a one-shot. `pan` comes from `pan_for` or is centred."""
        if not (self.available and self.enabled) or self.muted:
            return
        if key not in SFX_REGISTRY:
            return
        attenu = self._attenuation(distance)
        if attenu <= 0.0:
            return
        sound, base_vol = self._build(key)
        if sound is None:
            return
        vol = (volume if volume is not None else base_vol) * attenu * SFX_VOLUME * self._master_volume
        if vol <= 0.003:
            return
        channel = pygame.mixer.find_channel(True)
        if channel is None:
            return
        channel.set_volume(vol * pan[0], vol * pan[1])
        # Slight random pitch variation stops repeated footsteps sounding robotic.
        if pitch_variation > 0.0:
            factor = 1.0 + random.uniform(-pitch_variation, pitch_variation)
            try:
                channel.set_sound(sound)
            except AttributeError:
                pass
            channel.play(sound)
            self._tune_channel(channel, factor)
        else:
            channel.play(sound)

    @staticmethod
    def _tune_channel(channel, factor):
        """Approximate pitch variation by short-loop mix tweaks if supported."""
        # SDL_mixer has no per-channel pitch; variation is applied at build time
        # for the sounds where it matters, so this is intentionally a no-op hook.
        return

    def play_built(self, sound, volume, pan=(0.707, 0.707)):
        """Play an already-built Sound (used by pooled/looping effects)."""
        if not (self.available and self.enabled) or self.muted or sound is None:
            return None
        vol = volume * SFX_VOLUME * self._master_volume
        channel = pygame.mixer.find_channel(True)
        if channel is None:
            return None
        channel.set_volume(vol * pan[0], vol * pan[1])
        channel.play(sound)
        return channel

    def pan_for(self, listener, target, facing):
        """Convenience: give a world position, get (distance, (l, r)) gains."""
        dx = target[0] - listener[0]
        dy = target[1] - listener[1]
        return math.hypot(dx, dy), self._pan(dx, dy, facing)

    def play_at(self, key, listener, target, facing, volume=None,
                pitch_variation=0.0):
        distance, pan = self.pan_for(listener, target, facing)
        self.play(key, distance, pan, volume, pitch_variation)

    # ------------------------------------------------------------- looping ----
    def loop_start(self, key, volume=None, pan=(0.707, 0.707)):
        """Start (or restart) a looping bed on a dedicated channel."""
        if not (self.available and self.enabled) or self.muted:
            return None
        if key not in LOOP_REGISTRY:
            return None
        sound, base_vol = self._build_loop(key)
        if sound is None:
            return None
        channel = self._loop_channels.get(key)
        if channel is None:
            channel = pygame.mixer.find_channel(True)
            if channel is None:
                return None
            self._loop_channels[key] = channel
        vol = (volume if volume is not None else base_vol) * SFX_VOLUME * self._master_volume
        if vol <= 0.003:
            channel.stop()
            return channel
        channel.set_volume(vol * pan[0], vol * pan[1])
        if not channel.get_busy() or channel.get_sound() is not sound:
            channel.play(sound, loops=-1)
        return channel

    def loop_update(self, key, distance, pan=(0.707, 0.707), volume=None):
        """Adjust a running loop's attenuation without restarting it."""
        if not (self.available and self.enabled) or self.muted:
            return
        channel = self._loop_channels.get(key)
        if channel is None or not channel.get_busy():
            return
        if key not in LOOP_REGISTRY:
            return
        _sound, base_vol = self._loops.get(key, self._build_loop(key))
        attenu = self._attenuation(distance)
        vol = (volume if volume is not None else base_vol) * attenu * SFX_VOLUME * self._master_volume
        if vol <= 0.003:
            channel.set_volume(0.0, 0.0)
        else:
            channel.set_volume(vol * pan[0], vol * pan[1])

    def loop_stop(self, key, fade_ms=0):
        channel = self._loop_channels.get(key)
        if channel is None:
            return
        if fade_ms > 0:
            channel.fadeout(fade_ms)
        else:
            channel.stop()

    def stop_all_loops(self):
        for key in list(self._loop_channels):
            self.loop_stop(key)

    # --------------------------------------------------------------- music ----
    def _build_music(self, name):
        if name in self._music:
            return self._music[name]
        builder = music.TRACKS.get(name)
        if builder is None:
            return None
        sound = self._make_sound(builder())
        self._music[name] = sound
        return sound

    def play_music(self, name, loops=-1, fade_ms=600):
        if not (self.available and self.enabled) or self.muted:
            return
        if self._current_music == name:
            return
        sound = self._build_music(name)
        if sound is None:
            return
        if self._music_channel is None:
            self._music_channel = pygame.mixer.Channel(0)
        self._music_channel.set_volume(MUSIC_VOLUME * self._master_volume)
        self._music_channel.play(sound, loops=loops, fade_ms=fade_ms)
        self._current_music = name

    def stop_music(self, fade_ms=400):
        if self._music_channel is not None:
            self._music_channel.fadeout(fade_ms)
        self._current_music = None

    def play_stinger(self, name, volume=0.8):
        """Play a non-looping track (victory/defeat) on the music channel."""
        if not (self.available and self.enabled) or self.muted:
            return
        sound = self._build_music(name)
        if sound is None:
            return
        if self._music_channel is None:
            self._music_channel = pygame.mixer.Channel(0)
        self._music_channel.set_volume(volume * MUSIC_VOLUME * self._master_volume)
        self._music_channel.play(sound, loops=0)
        self._current_music = name

    # -------------------------------------------------------------- volume ----
    def set_master_volume(self, value):
        self._master_volume = max(0.0, min(1.0, value))

    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            if self.available:
                pygame.mixer.pause()
        else:
            if self.available:
                pygame.mixer.unpause()
        return self.muted
