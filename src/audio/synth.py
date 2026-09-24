"""Low-level procedural sound synthesis built on numpy.

Every sample the game ever plays is generated here or in the sibling modules,
so the shipped game contains no third-party audio and stays small enough for a
2 GB machine.
"""

import numpy as np

from ..config import SAMPLE_RATE

RNG = np.random.default_rng(0xC0FFEE)


def _t(duration):
    n = max(1, int(SAMPLE_RATE * duration))
    return np.arange(n, dtype=np.float64) / SAMPLE_RATE


def stereo(mono):
    """Duplicate a mono float array into an interleaved-free (n, 2) int16 frame.

    pygame's sndarray wants shape (n, channels); we build that directly. If the
    signal overshoots unity it is scaled down rather than hard-clipped, so hot
    effects stay clean instead of distorting.
    """
    mono = np.asarray(mono, dtype=np.float64)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak > 1.0:
        mono = mono / peak
    mono = np.clip(mono, -1.0, 1.0)
    pcm = (mono * 32767.0).astype(np.int16)
    return np.ascontiguousarray(np.stack([pcm, pcm], axis=1))


def white_noise(duration, rng=None):
    rng = rng or RNG
    return rng.uniform(-1.0, 1.0, _t(duration).size)


def sine(freq, duration, phase=0.0):
    return np.sin(2.0 * np.pi * freq * _t(duration) + phase)


def saw(freq, duration):
    t = _t(duration)
    return 2.0 * ((t * freq) % 1.0) - 1.0


def square(freq, duration, duty=0.5):
    t = _t(duration)
    return np.where((t * freq) % 1.0 < duty, 1.0, -1.0)


def triangle(freq, duration):
    t = _t(duration)
    x = (t * freq) % 1.0
    return 4.0 * np.abs(x - 0.5) - 1.0


def env(duration, attack=0.002, decay=0.05, sustain=0.0, release=0.05,
        sustain_level=0.7):
    """ADSR envelope scaled to `duration`, always exactly `duration` long."""
    n = _t(duration).size
    e = np.zeros(n)
    a = max(1, int(attack * SAMPLE_RATE))
    d = max(1, int(decay * SAMPLE_RATE))
    r = max(1, int(release * SAMPLE_RATE))
    s = max(0, n - a - d - r)
    idx = 0
    a = min(a, n)
    e[idx:idx + a] = np.linspace(0.0, 1.0, a, endpoint=False)
    idx += a
    if idx < n:
        d = min(d, n - idx)
        e[idx:idx + d] = np.linspace(1.0, sustain_level, d, endpoint=False)
        idx += d
    if idx < n:
        s = min(s, n - idx)
        e[idx:idx + s] = sustain_level
        idx += s
    if idx < n:
        r = min(r, n - idx)
        e[idx:idx + r] = np.linspace(sustain_level, 0.0, r, endpoint=False)
        idx += r
    if idx < n:
        e[idx:] = 0.0
    return e


def exp_decay(duration, rate):
    return np.exp(-rate * _t(duration))


def lowpass(signal, cutoff):
    """One-pole low-pass. numpy-only, no scipy dependency."""
    if cutoff >= SAMPLE_RATE * 0.5:
        return signal
    alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff / SAMPLE_RATE)
    out = np.empty_like(signal)
    acc = 0.0
    for i in range(signal.size):
        acc += alpha * (signal[i] - acc)
        out[i] = acc
    return out


def highpass(signal, cutoff):
    return signal - lowpass(signal, cutoff)


def vlowpass(signal, cutoff):
    """Vectorised-ish low-pass using cumulative filtering approximation.

    Implemented as a repeated box blur; cheap and adequate for game SFX where
    we mostly want to remove harshness from fresh noise.
    """
    if cutoff >= SAMPLE_RATE * 0.5:
        return signal
    win = max(1, int(SAMPLE_RATE / max(cutoff, 1.0)))
    kernel = np.ones(win) / win
    return np.convolve(signal, kernel, mode="same")


def bandpass(signal, low, high):
    return highpass(vlowpass(signal, high), low)


def fft_noise(duration, colour=0.0):
    """Tilted-spectrum noise. `colour` 0 = white, +1 = brighter, -1 = darker."""
    n = _t(duration).size
    spectrum = np.fft.rfft(white_noise(duration))
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    with np.errstate(divide="ignore"):
        tilt = np.power(np.maximum(freqs, 1.0), colour)
    spectrum *= tilt
    out = np.fft.irfft(spectrum, n=n)
    peak = np.max(np.abs(out))
    return out / peak if peak > 1e-9 else out


def fm_tone(carrier, mod_freq, index, duration):
    t = _t(duration)
    return np.sin(2.0 * np.pi * carrier * t
                  + index * np.sin(2.0 * np.pi * mod_freq * t))


def pulse_train(freq, duration, width=0.08):
    return square(freq, duration, duty=width)


def sweep(f0, f1, duration, kind="exp"):
    """Frequency sweep rendered sample-accurately."""
    n = _t(duration).size
    t = np.arange(n) / SAMPLE_RATE
    if kind == "exp" and f0 > 0 and f1 > 0:
        k = np.log(f1 / f0) / max(duration, 1e-6)
        phase = 2.0 * np.pi * f0 * (np.exp(k * t) - 1.0) / k
    else:
        phase = 2.0 * np.pi * (f0 * t + 0.5 * (f1 - f0) * t * t / max(duration, 1e-6))
    return np.sin(phase)


def mix(*layers):
    """Sum layers of differing lengths into one buffer."""
    if not layers:
        return np.zeros(1, dtype=np.float64)
    n = max(layer.size for layer in layers)
    out = np.zeros(n, dtype=np.float64)
    for layer in layers:
        out[:layer.size] += layer
    return out


def gain(signal, level):
    return signal * level


def concat(*layers):
    if not layers:
        return np.zeros(1, dtype=np.float64)
    return np.concatenate(layers)


def reverse(signal):
    return signal[::-1].copy()


def concat_gap(a, b, gap):
    silence = np.zeros(int(gap * SAMPLE_RATE))
    return np.concatenate([a, silence, b])
