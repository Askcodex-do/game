"""Procedurally composed soundtrack.

The tracks are original: a small step sequencer here renders short loops from
note tables using the synthesis primitives. Nothing is sampled from any
existing game, so the soundtrack can ship with no licensing questions.

Each loop is rendered once at startup (a couple of hundred milliseconds of CPU)
and then played on a dedicated pygame channel.
"""

import numpy as np

from ..config import SAMPLE_RATE
from . import synth as s

# Equal-temperament note table, A4 = 440 Hz.
_A4 = 440.0
_NOTE_OFFSETS = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
                 "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}


def note_hz(name):
    """Convert e.g. 'A3', 'C#4' to a frequency in Hz.

    Returns None for `None` and for trigger markers such as 'kick' or 'hat',
    which are used by percussion voices that ignore pitch.
    """
    if name is None:
        return None
    if isinstance(name, (int, float)):
        return float(name)
    if not isinstance(name, str) or len(name) < 2:
        return None
    pitch, octave_char = name[:-1], name[-1]
    if pitch not in _NOTE_OFFSETS:
        return None
    try:
        octave = int(octave_char)
    except ValueError:
        return None
    semis = _NOTE_OFFSETS[pitch] + (octave - 4) * 12
    return _A4 * (2.0 ** (semis / 12.0))


# ------------------------------------------------------------------ voices ---
def _pad(freq, dur, level=0.16):
    """Soft detuned pad, used for atmospheres."""
    if freq is None:
        return np.zeros(int(SAMPLE_RATE * dur))
    detune = freq * 1.004
    body = (np.sin(2.0 * np.pi * freq * _t(dur))
            + np.sin(2.0 * np.pi * detune * _t(dur))) * 0.5
    body += 0.2 * np.sin(2.0 * np.pi * freq * 2.0 * _t(dur))
    return s.gain(body, level) * s.env(dur, 0.35, 0.2, max(0.01, dur - 0.9), 0.35, 0.85)


def _t(dur):
    return np.arange(int(SAMPLE_RATE * dur)) / SAMPLE_RATE


def _bass(freq, dur, level=0.22):
    if freq is None:
        return np.zeros(int(SAMPLE_RATE * dur))
    body = 0.7 * np.sin(2.0 * np.pi * freq * _t(dur))
    body += 0.3 * np.square(2.0 * np.pi * freq * _t(dur)) * 0.15
    return s.gain(body, level) * s.env(dur, 0.008, 0.05, max(0.01, dur - 0.16), 0.1, 0.8)


def _lead(freq, dur, level=0.14, wave="tri"):
    if freq is None:
        return np.zeros(int(SAMPLE_RATE * dur))
    if wave == "saw":
        body = s.saw(freq, dur) * 0.6
    elif wave == "sq":
        body = s.square(freq, dur, 0.35) * 0.4
    else:
        body = s.triangle(freq, dur) * 0.7
    return s.gain(body, level) * s.env(dur, 0.01, 0.06, max(0.01, dur - 0.2), 0.12, 0.7)


def _pluck(freq, dur, level=0.18):
    if freq is None:
        return np.zeros(int(SAMPLE_RATE * dur))
    body = s.triangle(freq, dur) + 0.3 * s.sine(freq * 2, dur)
    env = s.exp_decay(dur, 7.0)
    return s.gain(body, level) * env


def _drum_kick(dur=0.32, level=0.5):
    t = _t(dur)
    pitch = 150.0 * np.exp(-18.0 * t) + 42.0
    phase = 2.0 * np.pi * np.cumsum(pitch) / SAMPLE_RATE
    body = np.sin(phase)
    click = s.gain(s.white_noise(dur), 0.25) * s.exp_decay(dur, 90.0)
    return s.gain(body, level) * s.exp_decay(dur, 9.0) + click * level


def _drum_snare(dur=0.22, level=0.32):
    tone = s.gain(s.sine(190.0, dur), 0.4) * s.exp_decay(dur, 30.0)
    noise = s.gain(s.bandpass(s.white_noise(dur), 900.0, 7500.0), 0.7) * s.exp_decay(dur, 26.0)
    return s.gain(s.mix(tone, noise), level)


def _drum_hat(dur=0.06, level=0.16):
    return s.gain(s.highpass(s.white_noise(dur), 6000.0), level) * s.exp_decay(dur, 110.0)


def _drum_tom(freq=140.0, dur=0.35, level=0.3):
    t = _t(dur)
    pitch = freq * np.exp(-4.0 * t) + freq * 0.55
    phase = 2.0 * np.pi * np.cumsum(pitch) / SAMPLE_RATE
    return s.gain(np.sin(phase), level) * s.exp_decay(dur, 10.0)


# --------------------------------------------------------------- sequencer ---
def _render_sequence(length, bpm, tracks):
    """Render a fixed-length loop.

    `tracks` is a list of dicts: {"steps": [...], "voice": callable,
    "duration": beats_per_step}. Steps are numbered in sixteenths and wrap;
    the loop is `length` bars of 4/4.
    """
    beats_per_sixteenth = 60.0 / bpm / 4.0
    bar_sixteenths = 16
    total_steps = length * bar_sixteenths
    total_samples = int(total_steps * beats_per_sixteenth * SAMPLE_RATE)
    buffer = np.zeros(total_samples + SAMPLE_RATE)  # headroom for tails

    for track in tracks:
        voice = track["voice"]
        duration = track.get("duration", 1) * beats_per_sixteenth * 4.0
        duration = max(duration, beats_per_sixteenth)
        steps = track["steps"]
        for i, note in enumerate(steps):
            if note is None:
                continue
            start = int((i % total_steps) * beats_per_sixteenth * SAMPLE_RATE)
            layer = voice(note_hz(note) if note != "rest" else None, duration)
            end = min(start + layer.size, buffer.size)
            buffer[start:end] += layer[:end - start]

    buffer = buffer[:total_samples]
    peak = np.max(np.abs(buffer))
    if peak > 1e-9:
        buffer = buffer / peak * 0.85
    return buffer


def _loop_safe(signal, fade=0.25):
    """Shrink a buffer to an exact whole number of samples and taper the seam.

    The tails rendered beyond the loop point are folded back onto the start,
    which keeps note releases from being chopped off.
    """
    n = signal.size
    fade_samples = int(fade * SAMPLE_RATE)
    if n > fade_samples * 2:
        head = signal[:fade_samples]
        tail = signal[-fade_samples:]
        signal = signal[:n - fade_samples]
        signal[:fade_samples] = head + tail
        signal[-fade_samples:] *= np.linspace(1.0, 1.0, fade_samples)
    return np.clip(signal, -1.0, 1.0)


# ------------------------------------------------------------------ tracks ---
def menu_theme():
    """Brooding menu loop: slow pad progression plus a sparse lead."""
    pad_chords = [
        ["D3", "F3", "A3"], ["A#2", "D3", "F3"],
        ["C3", "E3", "G3"], ["G2", "A#2", "D3"],
    ]
    buffer = np.zeros(int(SAMPLE_RATE * 4 * 4 * 60.0 / 76.0) + SAMPLE_RATE)
    beat = 60.0 / 76.0
    for bar, chord in enumerate(pad_chords):
        start = int(bar * 4 * beat * SAMPLE_RATE)
        for n in chord:
            layer = _pad(note_hz(n), 4 * beat + 0.6, 0.13)
            end = min(start + layer.size, buffer.size)
            buffer[start:end] += layer[:end - start]
    # Sparse bell lead over the top.
    lead = _render_sequence(4, 76.0, [
        {"steps": ["rest"] * 8 + ["D4", "rest", "rest", "rest", "F4", "rest", "rest", "rest"],
         "voice": lambda f, d: _pluck(f, d, 0.12), "duration": 1},
        {"steps": ["rest"] * 16, "voice": lambda f, d: _pluck(f, d, 0.0)},
    ])
    n = min(buffer.size, lead.size)
    buffer[:n] += lead[:n]
    out = _loop_safe(buffer)
    peak = np.max(np.abs(out))
    return out / peak * 0.8 if peak > 1e-9 else out


def stealth_theme():
    """Low tension bed for patrol gameplay: pulsing sub, ticking hats, drone."""
    tracks = [
        {"steps": ["D2", None, None, None, "D2", None, "A1", None,
                   "D2", None, None, None, "D2", None, "F1", None],
         "voice": _bass, "duration": 1.6},
        {"steps": [None, None, "D4", None, None, None, "F4", None,
                   None, None, "A4", None, None, None, "G4", None],
         "voice": lambda f, d: _pluck(f, d, 0.10), "duration": 1.2},
        {"steps": ["hit" if i % 8 == 4 else None for i in range(16)],
         "voice": lambda _f, d: _drum_hat(0.05, 0.10)},
    ]
    out = _render_sequence(2, 84.0, tracks)
    drone = _pad(note_hz("D2"), len(out) / SAMPLE_RATE, 0.08)
    n = min(out.size, drone.size)
    out[:n] += drone[:n]
    return _loop_safe(out)


def alert_theme():
    """Combat loop: driving kick/snare pulse with urgent bass and stabs."""
    tracks = [
        {"steps": ["D2"] * 4 + ["D2", None, "D2", None] + ["D2"] * 2 + ["F2", "G2"],
         "voice": _bass, "duration": 0.8},
        {"steps": [("kick" if i % 4 == 0 else ("snare" if i % 8 == 4 else None))
                   for i in range(32)],
         "voice": lambda _f, d: _drum_kick(0.3, 0.55)},
        {"steps": [None] * 32, "voice": lambda _f, d: _drum_snare(0.2, 0.0)},
        {"steps": [None, None, "D4", None, None, None, "A3", None] * 4,
         "voice": lambda f, d: _lead(f, d, 0.13, "sq"), "duration": 1.0},
    ]
    # Snare hits need their own step pattern, so add them explicitly.
    tracks[2]["steps"] = [("snare" if i % 8 == 4 else None) for i in range(32)]
    tracks[2]["voice"] = lambda _f, d: _drum_snare(0.2, 0.30)
    tracks.append({
        "steps": [("hat" if i % 2 == 0 else None) for i in range(32)],
        "voice": lambda _f, d: _drum_hat(0.05, 0.16),
    })
    out = _render_sequence(2, 132.0, tracks)
    return _loop_safe(out)


def tension_theme():
    """Suspicion/investigation: dissonant sustained strings and a ticking pulse."""
    tracks = [
        {"steps": ["A1", None, None, None, None, None, "A1", None] * 2 + [None] * 16,
         "voice": _bass, "duration": 2.0},
        {"steps": [("tick" if i % 4 == 2 else None) for i in range(32)],
         "voice": lambda _f, d: _drum_hat(0.04, 0.14)},
    ]
    out = _render_sequence(2, 96.0, tracks)
    for n in ("A2", "A#2", "E3"):
        layer = _pad(note_hz(n), len(out) / SAMPLE_RATE, 0.10)
        out[:min(out.size, layer.size)] += layer[:out.size]
    return _loop_safe(out)


def victory_theme():
    """Short triumphant stinger, not looped."""
    buffer = np.zeros(int(SAMPLE_RATE * 3.6) + SAMPLE_RATE)
    beat = 60.0 / 108.0
    melody = [("D4", 0), ("F4", 1), ("A4", 2), ("D5", 3),
              ("C5", 4), ("A4", 5), ("D5", 6.5)]
    for name, b in melody:
        start = int(b * beat * SAMPLE_RATE)
        layer = _lead(note_hz(name), beat * 0.9, 0.2, "tri")
        end = min(start + layer.size, buffer.size)
        buffer[start:end] += layer[:end - start]
    for b in (0, 1, 2, 3, 4, 5, 6, 7):
        start = int(b * beat * SAMPLE_RATE)
        layer = _bass(note_hz("D2" if b % 2 == 0 else "A1"), beat * 0.8, 0.24)
        end = min(start + layer.size, buffer.size)
        buffer[start:end] += layer[:end - start]
    for b in (0, 4):
        start = int(b * beat * SAMPLE_RATE)
        layer = _drum_kick(0.4, 0.6)
        end = min(start + layer.size, buffer.size)
        buffer[start:end] += layer[:end - start]
    for b in (2, 6):
        start = int(b * beat * SAMPLE_RATE)
        layer = _drum_snare(0.3, 0.4)
        end = min(start + layer.size, buffer.size)
        buffer[start:end] += layer[:end - start]
    out = np.clip(buffer, -1.0, 1.0)
    peak = np.max(np.abs(out))
    return out / peak * 0.85 if peak > 1e-9 else out


def defeat_theme():
    """Sombre fail stinger, not looped."""
    parts = []
    for name, dur in (("A3", 0.5), ("G3", 0.5), ("F3", 0.7), ("D3", 1.3)):
        tone = _pad(note_hz(name), dur, 0.3)
        parts.append(tone)
    out = s.concat(*parts)
    peak = np.max(np.abs(out))
    return out / peak * 0.8 if peak > 1e-9 else out


TRACKS = {
    "menu": menu_theme,
    "stealth": stealth_theme,
    "alert": alert_theme,
    "tension": tension_theme,
    "victory": victory_theme,
    "defeat": defeat_theme,
}
