"""Procedural sound-effect recipes.

Each function returns a mono float array in [-1, 1]. The mixer turns these into
pygame Sound objects lazily, so only the effects a stage actually uses cost RAM.
"""

import numpy as np

from ..config import SAMPLE_RATE
from . import synth as s

RNG = np.random.default_rng(0x5EED)


# ----------------------------------------------------------------- weapons ---
def gunshot_suppressed():
    """SD pistol: a dry snap plus a short, damped body."""
    snap = s.gain(s.highpass(s.white_noise(0.055), 1800.0), 0.75)
    snap *= s.exp_decay(0.055, 90.0)
    body = s.gain(s.vlowpass(s.white_noise(0.14), 900.0), 0.5)
    body *= s.exp_decay(0.14, 34.0)
    click = s.gain(s.pulse_train(2400.0, 0.02, 0.2), 0.22) * s.exp_decay(0.02, 220.0)
    return s.mix(snap, body, click)


def gunshot_smg():
    crack = s.gain(s.highpass(s.white_noise(0.09), 1200.0), 0.9)
    crack *= s.exp_decay(0.09, 46.0)
    tone = s.gain(s.sweep(420.0, 90.0, 0.11), 0.45) * s.exp_decay(0.11, 30.0)
    return s.mix(crack, tone)


def gunshot_rifle():
    crack = s.gain(s.highpass(s.white_noise(0.12), 900.0), 1.0)
    crack *= s.exp_decay(0.12, 32.0)
    boom = s.gain(s.sweep(260.0, 55.0, 0.22), 0.6) * s.exp_decay(0.22, 16.0)
    tail = s.gain(s.vlowpass(s.white_noise(0.4), 500.0), 0.28)
    tail *= s.exp_decay(0.4, 9.0)
    return s.mix(crack, boom, tail)


def gunshot_shotgun():
    crack = s.gain(s.white_noise(0.16), 0.95) * s.exp_decay(0.16, 26.0)
    boom = s.gain(s.sweep(200.0, 40.0, 0.3), 0.7) * s.exp_decay(0.3, 12.0)
    return s.mix(crack, boom)


def gunshot_sniper():
    crack = s.gain(s.highpass(s.white_noise(0.18), 700.0), 1.0) * s.exp_decay(0.18, 26.0)
    boom = s.gain(s.sweep(180.0, 38.0, 0.45), 0.8) * s.exp_decay(0.45, 8.0)
    tail = s.gain(s.vlowpass(s.white_noise(1.0), 420.0), 0.3) * s.exp_decay(1.0, 3.4)
    return s.mix(crack, boom, tail)


def dry_fire():
    return s.gain(s.pulse_train(1600.0, 0.04, 0.25), 0.4) * s.exp_decay(0.04, 90.0)


def reload_mag_out():
    clack = s.gain(s.highpass(s.white_noise(0.06), 2200.0), 0.5) * s.exp_decay(0.06, 70.0)
    return s.mix(clack, s.gain(s.pulse_train(700.0, 0.05, 0.3), 0.25) * s.exp_decay(0.05, 60.0))


def reload_mag_in():
    thunk = s.gain(s.vlowpass(s.white_noise(0.08), 1400.0), 0.7) * s.exp_decay(0.08, 45.0)
    click = s.gain(s.pulse_train(1900.0, 0.03, 0.2), 0.3) * s.exp_decay(0.03, 150.0)
    return s.mix(thunk, click)


def reload_charge():
    bolt = s.gain(s.highpass(s.white_noise(0.1), 1500.0), 0.55) * s.exp_decay(0.1, 40.0)
    return s.mix(bolt, s.gain(s.pulse_train(950.0, 0.06, 0.35), 0.28) * s.exp_decay(0.06, 55.0))


def knife_swing():
    return s.gain(s.bandpass(s.white_noise(0.16), 500.0, 2600.0), 0.5) * s.exp_decay(0.16, 18.0)


def knife_hit():
    thud = s.gain(s.vlowpass(s.white_noise(0.14), 500.0), 0.8) * s.exp_decay(0.14, 30.0)
    return s.mix(thud, s.gain(s.sweep(300.0, 80.0, 0.12), 0.3) * s.exp_decay(0.12, 30.0))


def bullet_impact_stone():
    tick = s.gain(s.highpass(s.white_noise(0.07), 2500.0), 0.6) * s.exp_decay(0.07, 80.0)
    return s.mix(tick, s.gain(s.pulse_train(3000.0, 0.03, 0.15), 0.25) * s.exp_decay(0.03, 160.0))


def bullet_impact_metal():
    tick = s.gain(s.bandpass(s.white_noise(0.16), 1800.0, 7000.0), 0.55) * s.exp_decay(0.16, 34.0)
    ring = s.gain(s.sine(3150.0, 0.2), 0.18) * s.exp_decay(0.2, 22.0)
    return s.mix(tick, ring)


def bullet_impact_flesh():
    thud = s.gain(s.vlowpass(s.white_noise(0.12), 700.0), 0.85) * s.exp_decay(0.12, 32.0)
    return s.mix(thud, s.gain(s.sweep(340.0, 110.0, 0.1), 0.3) * s.exp_decay(0.1, 32.0))


def grenade_pin():
    return s.mix(
        s.gain(s.pulse_train(2600.0, 0.04, 0.2), 0.35) * s.exp_decay(0.04, 120.0),
        s.gain(s.bandpass(s.white_noise(0.1), 2000.0, 6000.0), 0.3) * s.exp_decay(0.1, 40.0),
    )


def grenade_bounce():
    return s.gain(s.vlowpass(s.white_noise(0.07), 900.0), 0.5) * s.exp_decay(0.07, 55.0)


def grenade_explosion():
    boom = s.gain(s.sweep(150.0, 28.0, 0.9), 0.95) * s.exp_decay(0.9, 5.5)
    blast = s.gain(s.vlowpass(s.white_noise(1.5), 700.0), 0.8) * s.exp_decay(1.5, 3.0)
    crack = s.gain(s.white_noise(0.12), 0.7) * s.exp_decay(0.12, 35.0)
    rumble = s.gain(s.vlowpass(s.white_noise(2.0), 180.0), 0.6) * s.exp_decay(2.0, 2.0)
    return s.mix(boom, blast, crack, rumble)


# ----------------------------------------------------------------- picking ---
def pickup_item():
    return s.mix(
        s.gain(s.sine(880.0, 0.09), 0.35) * s.env(0.09, 0.004, 0.02, 0.02, 0.05),
        s.gain(s.sine(1320.0, 0.12), 0.28) * s.env(0.12, 0.004, 0.02, 0.02, 0.08),
    )


def pickup_ammo():
    clack = s.gain(s.highpass(s.white_noise(0.05), 2000.0), 0.5) * s.exp_decay(0.05, 80.0)
    return s.mix(clack, s.gain(s.pulse_train(1100.0, 0.05, 0.3), 0.3) * s.exp_decay(0.05, 60.0))


def intel_download():
    """Rising digital chirp used when picking up mission intel."""
    steps = [660.0, 830.0, 990.0, 1240.0]
    parts = []
    for i, f in enumerate(steps):
        tone = s.gain(s.pulse_train(f, 0.075, 0.4), 0.25)
        tone *= s.env(0.075, 0.003, 0.01, 0.05, 0.012)
        parts.append(tone)
    return s.concat(*parts)


def objective_complete():
    notes = [523.25, 659.25, 783.99, 1046.50]
    parts = []
    for f in notes:
        tone = s.mix(s.gain(s.sine(f, 0.3), 0.3), s.gain(s.triangle(f * 0.5, 0.3), 0.12))
        tone *= s.env(0.3, 0.005, 0.06, 0.14, 0.1)
        parts.append(tone)
    return s.concat(*parts)


def objective_failed():
    parts = []
    for f in (392.0, 311.13, 233.08):
        tone = s.gain(s.saw(f, 0.36), 0.22) * s.env(0.36, 0.006, 0.08, 0.15, 0.12)
        parts.append(tone)
    return s.concat(*parts)


# ---------------------------------------------------------------- movement ---
def footstep_concrete():
    step = s.gain(s.vlowpass(s.white_noise(0.075), 1500.0), 0.30)
    step *= s.exp_decay(0.075, 60.0)
    return s.mix(step, s.gain(s.sine(120.0, 0.06), 0.12) * s.exp_decay(0.06, 70.0))


def footstep_gravel():
    n = s.white_noise(0.1)
    return s.gain(s.bandpass(n, 700.0, 5000.0), 0.30) * s.exp_decay(0.1, 42.0)


def footstep_grass():
    return s.gain(s.vlowpass(s.white_noise(0.11), 2600.0), 0.24) * s.exp_decay(0.11, 38.0)


def footstep_metal():
    clang = s.gain(s.bandpass(s.white_noise(0.14), 1500.0, 6000.0), 0.28) * s.exp_decay(0.14, 30.0)
    ring = s.gain(s.sine(2100.0, 0.2), 0.10) * s.exp_decay(0.2, 20.0)
    return s.mix(clang, ring)


def jump_grunt():
    return s.gain(s.vlowpass(s.white_noise(0.16), 900.0), 0.22) * s.env(0.16, 0.01, 0.05, 0.04, 0.06)


def land_thud():
    return s.gain(s.vlowpass(s.white_noise(0.14), 500.0), 0.5) * s.exp_decay(0.14, 40.0)


def player_hurt():
    return s.gain(s.bandpass(s.white_noise(0.22), 300.0, 2000.0), 0.32) * s.env(0.22, 0.005, 0.06, 0.08, 0.08)


def player_death():
    tone = s.gain(s.sweep(220.0, 55.0, 1.1), 0.4) * s.env(1.1, 0.02, 0.2, 0.5, 0.35)
    noise = s.gain(s.vlowpass(s.white_noise(1.2), 700.0), 0.3) * s.exp_decay(1.2, 3.0)
    return s.mix(tone, noise)


# ------------------------------------------------------------------ enemies --
def enemy_alert_shout():
    """Short nasal bark, synthesised as a formant-ish swept tone."""
    base = s.gain(s.fm_tone(210.0, 190.0, 3.2, 0.42), 0.4)
    base *= s.env(0.42, 0.01, 0.08, 0.2, 0.13)
    formant = s.gain(s.bandpass(s.white_noise(0.4), 700.0, 3200.0), 0.14)
    formant *= s.env(0.4, 0.02, 0.1, 0.18, 0.1)
    return s.mix(base, formant)


def enemy_pain():
    base = s.gain(s.fm_tone(300.0, 130.0, 4.0, 0.3), 0.36)
    base *= s.env(0.3, 0.006, 0.06, 0.12, 0.1)
    return s.mix(base, s.gain(s.bandpass(s.white_noise(0.28), 500.0, 2600.0), 0.12))


def enemy_death():
    base = s.gain(s.fm_tone(240.0, 90.0, 5.0, 0.75), 0.36)
    base *= s.env(0.75, 0.008, 0.12, 0.3, 0.3)
    fall = s.gain(s.vlowpass(s.white_noise(0.6), 600.0), 0.35) * s.exp_decay(0.6, 6.0)
    return s.mix(base, fall)


def enemy_footstep():
    return s.gain(s.vlowpass(s.white_noise(0.08), 1200.0), 0.18) * s.exp_decay(0.08, 55.0)


def enemy_reload():
    return s.mix(
        s.gain(s.highpass(s.white_noise(0.06), 1800.0), 0.28) * s.exp_decay(0.06, 70.0),
        s.gain(s.pulse_train(800.0, 0.06, 0.3), 0.18) * s.exp_decay(0.06, 60.0),
    )


# ----------------------------------------------------------------- vehicles --
def truck_engine_loop():
    """Seamless ~2 s diesel idle: firing pulses plus a low rumble."""
    dur = 2.0
    t = np.arange(int(SAMPLE_RATE * dur)) / SAMPLE_RATE
    # 4 firing pulses per second for a heavy idle.
    pulse = 0.5 * (1.0 + np.sin(2.0 * np.pi * 4.0 * t))
    pulse = np.power(pulse, 3.0)
    knock = np.sin(2.0 * np.pi * 42.0 * t) * pulse
    rumble = 0.5 * np.sin(2.0 * np.pi * 26.0 * t + 0.3 * np.sin(2.0 * np.pi * 5.0 * t))
    hiss = s.gain(s.vlowpass(s.white_noise(dur), 900.0), 0.10)
    out = s.mix(s.gain(knock, 0.6), s.gain(rumble, 0.45), hiss)
    # Cross-fade the ends so looping is click-free.
    fade = int(SAMPLE_RATE * 0.05)
    out[:fade] *= np.linspace(0.0, 1.0, fade)
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    peak = np.max(np.abs(out))
    return out / peak * 0.8


def truck_moving_loop():
    dur = 1.5
    t = np.arange(int(SAMPLE_RATE * dur)) / SAMPLE_RATE
    pulse = np.power(0.5 * (1.0 + np.sin(2.0 * np.pi * 11.0 * t)), 2.5)
    knock = np.sin(2.0 * np.pi * 58.0 * t) * pulse
    rumble = np.sin(2.0 * np.pi * 34.0 * t)
    out = s.mix(s.gain(knock, 0.5), s.gain(rumble, 0.4),
                s.gain(s.vlowpass(s.white_noise(dur), 1200.0), 0.14))
    fade = int(SAMPLE_RATE * 0.05)
    out[:fade] *= np.linspace(0.0, 1.0, fade)
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    peak = np.max(np.abs(out))
    return out / peak * 0.85


def truck_horn():
    return s.mix(
        s.gain(s.square(233.0, 0.7, 0.5), 0.3) * s.env(0.7, 0.01, 0.05, 0.5, 0.14),
        s.gain(s.square(311.0, 0.7, 0.5), 0.24) * s.env(0.7, 0.01, 0.05, 0.5, 0.14),
    )


def truck_destroyed():
    boom = s.gain(s.sweep(190.0, 32.0, 1.4), 0.95) * s.exp_decay(1.4, 3.6)
    blast = s.gain(s.vlowpass(s.white_noise(2.0), 800.0), 0.8) * s.exp_decay(2.0, 2.2)
    debris = s.gain(s.bandpass(s.white_noise(1.4), 400.0, 4000.0), 0.35) * s.exp_decay(1.4, 2.6)
    return s.mix(boom, blast, debris)


# ----------------------------------------------------------------- cameras ---
def camera_servo_loop():
    dur = 1.2
    t = np.arange(int(SAMPLE_RATE * dur)) / SAMPLE_RATE
    hum = 0.3 * np.sin(2.0 * np.pi * 62.0 * t) + 0.15 * np.sin(2.0 * np.pi * 124.0 * t)
    friction = s.gain(s.vlowpass(s.white_noise(dur), 2100.0), 0.08)
    out = s.mix(hum, friction)
    fade = int(SAMPLE_RATE * 0.04)
    out[:fade] *= np.linspace(0.0, 1.0, fade)
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    return out * 0.5


def camera_detect_beep():
    return s.mix(
        s.gain(s.sine(1568.0, 0.1), 0.3) * s.env(0.1, 0.003, 0.02, 0.04, 0.03),
        s.gain(s.sine(2093.0, 0.08), 0.18) * s.env(0.08, 0.003, 0.02, 0.03, 0.02),
    )


def camera_destroyed():
    crackle = s.gain(s.highpass(s.white_noise(0.35), 1600.0), 0.6) * s.exp_decay(0.35, 12.0)
    pop = s.gain(s.sweep(900.0, 120.0, 0.15), 0.4) * s.exp_decay(0.15, 25.0)
    return s.mix(crackle, pop)


def alarm_siren():
    """Two-tone rising/falling siren, 2 s loop."""
    dur = 2.0
    t = np.arange(int(SAMPLE_RATE * dur)) / SAMPLE_RATE
    wobble = 0.5 * (1.0 + np.sin(2.0 * np.pi * 0.5 * t))
    freq = 520.0 + 300.0 * wobble
    phase = 2.0 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    tone = np.sin(phase) + 0.4 * np.sin(2.0 * phase)
    fade = int(SAMPLE_RATE * 0.02)
    tone[:fade] *= np.linspace(0.0, 1.0, fade)
    tone[-fade:] *= np.linspace(1.0, 0.0, fade)
    peak = np.max(np.abs(tone))
    return tone / peak * 0.7


def alarm_cancelled():
    parts = []
    for f in (880.0, 660.0, 440.0):
        tone = s.gain(s.sine(f, 0.22), 0.3) * s.env(0.22, 0.006, 0.05, 0.09, 0.07)
        parts.append(tone)
    return s.concat(*parts)


# --------------------------------------------------------------------- misc --
def ambient_night_loop():
    """Quiet outdoor bed: filtered noise plus a slow low drone."""
    dur = 6.0
    t = np.arange(int(SAMPLE_RATE * dur)) / SAMPLE_RATE
    wind = s.gain(s.vlowpass(s.white_noise(dur), 500.0), 0.5)
    drone = 0.25 * np.sin(2.0 * np.pi * 48.0 * t + 0.5 * np.sin(2.0 * np.pi * 0.4 * t))
    crickets = s.gain(s.pulse_train(4200.0, dur, 0.02), 0.05) * (0.5 + 0.5 * np.sin(2.0 * np.pi * 0.7 * t))
    out = s.mix(wind, drone, crickets)
    fade = int(SAMPLE_RATE * 0.4)
    out[:fade] *= np.linspace(0.0, 1.0, fade)
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    return out * 0.35


def ui_click():
    return s.gain(s.pulse_train(1500.0, 0.05, 0.25), 0.25) * s.exp_decay(0.05, 70.0)


def ui_move():
    return s.gain(s.pulse_train(900.0, 0.04, 0.25), 0.16) * s.exp_decay(0.04, 80.0)


def ui_confirm():
    return s.mix(
        s.gain(s.sine(660.0, 0.12), 0.3) * s.env(0.12, 0.004, 0.03, 0.05, 0.04),
        s.gain(s.sine(990.0, 0.14), 0.22) * s.env(0.14, 0.004, 0.03, 0.05, 0.06),
    )


def ui_error():
    return s.gain(s.square(160.0, 0.28, 0.5), 0.22) * s.env(0.28, 0.005, 0.05, 0.14, 0.08)


def bullet_whizz():
    return s.gain(s.bandpass(s.white_noise(0.14), 900.0, 3400.0), 0.3) * s.exp_decay(0.14, 22.0)


def glass_break():
    parts = [s.gain(s.bandpass(s.white_noise(0.4), 2000.0, 8000.0), 0.45) * s.exp_decay(0.4, 12.0)]
    for f in (2600.0, 3300.0, 4100.0):
        parts.append(s.gain(s.sine(f, 0.25), 0.10) * s.exp_decay(0.25, 16.0))
    return s.mix(*parts)


def door_open():
    creak = s.gain(s.sweep(180.0, 320.0, 0.6), 0.2) * s.env(0.6, 0.05, 0.1, 0.3, 0.15)
    return s.mix(creak, s.gain(s.vlowpass(s.white_noise(0.6), 900.0), 0.1))


def metal_clang():
    return s.mix(
        s.gain(s.bandpass(s.white_noise(0.3), 1200.0, 6000.0), 0.4) * s.exp_decay(0.3, 16.0),
        s.gain(s.sine(1800.0, 0.5), 0.14) * s.exp_decay(0.5, 7.0),
    )
