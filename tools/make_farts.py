"""Синтезирует звуки пуков в assets/sfx/ (запускать вручную: python tools/make_farts.py).

Нужны numpy и scipy, но только для генерации — сама игра читает готовые WAV.
Модель: «хлопающий клапан» — поток коротких импульсов с дрожащим периодом,
пропущенный через резонансы, плюс воздух, мокрые щелчки и пузыри.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 32000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sfx")


def smooth_noise(n, rate_hz, rng):
    """Медленный случайный дрейф от -1 до 1."""
    k = max(2, int(n / SR * rate_hz) + 2)
    pts = rng.uniform(-1, 1, k)
    return np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)


def bandpass(x, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def lowpass(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x)


def highpass(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x)


def fart(seed, dur, f0, f1=None, wobble=0.15, jitter=0.12, rough=0.3, wet=0.0, air=0.25,
         formants=((180, 1.0), (520, 0.6), (1300, 0.25)), drive=2.5, gate=None, open_q=0.45,
         sputter_tail=0.0):
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    f1 = f0 if f1 is None else f1
    f0_curve = f0 + (f1 - f0) * (t / dur) ** 0.8
    f0_curve *= 1 + wobble * smooth_noise(n, 9, rng)
    if sputter_tail:
        tail = np.clip((t / dur - (1 - sputter_tail)) / sputter_tail, 0, 1)
        f0_curve *= 1 - 0.55 * tail

    # общая громкость: быстрый вход, неровное «тело», хвост
    env = np.minimum(1, t / 0.012) * np.clip((dur - t) / (0.12 * dur + 0.02), 0, 1) ** 0.8
    env *= 1 + 0.35 * smooth_noise(n, 14, rng)
    if gate is not None:
        env *= gate(t)

    # поток импульсов клапана
    exc = np.zeros(n)
    pos = 0.0
    while pos < n:
        i = int(pos)
        period = SR / max(15, f0_curve[min(i, n - 1)]) * (1 + jitter * rng.standard_normal())
        period = max(SR / 900, period)
        width = max(3, int(period * open_q * rng.uniform(0.8, 1.2)))
        amp = env[min(i, n - 1)] * (1 + rough * rng.standard_normal())
        if rng.random() < rough * 0.25:
            amp *= 0.2  # клапан «захлебнулся»
        seg = np.sin(np.linspace(0, np.pi, width)) ** 1.5
        seg = np.concatenate([seg, -0.35 * seg[: width // 2]])
        j = min(n, i + len(seg))
        exc[i:j] += amp * seg[: j - i]
        pos += period

    # резонансы тела
    out = np.zeros(n)
    for fc, g in formants:
        bw = fc * 0.35
        out += g * bandpass(exc, max(20, fc - bw), min(SR / 2 - 100, fc + bw))
    out += 0.6 * lowpass(exc, 400)

    # воздух
    noise = rng.standard_normal(n)
    out += air * lowpass(noise, 2200) * lowpass(np.abs(exc), 60) * 3

    # мокрые щелчки и пузыри
    if wet:
        k = int(dur * wet * 70)
        for _ in range(k):
            i = int(rng.uniform(0, n - 400))
            a = env[i] * rng.uniform(0.3, 1.0) * wet
            if rng.random() < 0.6:
                ln = int(SR * rng.uniform(0.002, 0.008))
                burst = bandpass(rng.standard_normal(ln + 64), 700, 3500)[64:] * np.exp(-np.arange(ln) / (ln / 4))
                out[i:i + ln] += 0.9 * a * burst
            else:
                ln = int(SR * rng.uniform(0.008, 0.025))
                tt = np.arange(ln) / SR
                fb = rng.uniform(250, 700)
                pop = np.sin(2 * np.pi * (fb * tt + 0.5 * fb * 6 * tt * tt)) * np.exp(-tt / (ln / SR / 3))
                out[i:i + ln] += 0.7 * a * pop

    out = highpass(out, 35)
    out /= np.max(np.abs(out)) + 1e-9
    out = np.tanh(drive * out) / np.tanh(drive)
    out = lowpass(out, 3800 if wet else 3000, order=4)  # приглушить: звук идёт «из-под» зверя
    fade = int(SR * 0.02)
    out[-fade:] *= np.linspace(1, 0, fade)
    out[:64] *= np.linspace(0, 1, 64)
    return out / (np.max(np.abs(out)) + 1e-9) * 0.92


def bursts(times, length):
    def g(t):
        m = np.zeros_like(t)
        for s in times:
            m += np.clip(1 - np.abs((t - s - length / 2) / (length / 2)) ** 3, 0, 1)
        return np.clip(m, 0, 1)
    return g


VARIANTS = {
    "short_pfft": dict(seed=1, dur=0.28, f0=150, f1=110, air=0.45, rough=0.25),
    "classic_brap": dict(seed=2, dur=0.75, f0=85, f1=62, wobble=0.2, rough=0.35, wet=0.15),
    "long_rumble": dict(seed=3, dur=1.5, f0=58, f1=42, rough=0.45, drive=3.5, sputter_tail=0.35,
                        formants=((140, 1.0), (380, 0.7), (900, 0.2))),
    "squeaker": dict(seed=4, dur=0.65, f0=260, f1=430, wobble=0.08, jitter=0.05, rough=0.1, air=0.1,
                     formants=((450, 1.0), (1100, 0.5), (2200, 0.2)), open_q=0.3),
    "wet_splat": dict(seed=5, dur=0.55, f0=70, f1=55, wet=1.0, rough=0.5, air=0.35),
    "staccato": dict(seed=6, dur=0.9, f0=120, f1=95, gate=bursts([0.0, 0.2, 0.38, 0.55, 0.72], 0.13),
                     rough=0.3, air=0.35),
    "bass_bomb": dict(seed=7, dur=0.95, f0=40, f1=34, drive=4.5, rough=0.4,
                      formants=((110, 1.0), (300, 0.8), (700, 0.3))),
    "trumpet": dict(seed=8, dur=0.85, f0=165, f1=140, wobble=0.12, jitter=0.04, rough=0.15,
                    formants=((300, 1.0), (800, 0.7), (1700, 0.3))),
    "sputter": dict(seed=9, dur=1.1, f0=95, f1=48, wet=0.35, rough=0.55,
                    gate=lambda t: 0.35 + 0.65 * (np.sin(2 * np.pi * (7 + 5 * t) * t) > -0.3)),
    "whine": dict(seed=10, dur=1.2, f0=340, f1=230, wobble=0.12, jitter=0.06, rough=0.12, air=0.15,
                  formants=((500, 1.0), (1200, 0.5), (2500, 0.15)), open_q=0.3),
    "wet_long": dict(seed=11, dur=1.15, f0=66, f1=50, wet=0.75, rough=0.45, sputter_tail=0.3),
    "tiny_toot": dict(seed=12, dur=0.2, f0=230, f1=200, jitter=0.05, rough=0.1, air=0.2,
                      formants=((420, 1.0), (1000, 0.4))),
}


def save(path, x):
    data = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, params in VARIANTS.items():
        save(os.path.join(OUT, f"fart_{name}.wav"), fart(**params))
        print("ok", name)


if __name__ == "__main__":
    main()
