"""macOS-style camera shutter sound synthesizer and non-blocking Windows playback."""

from __future__ import annotations

import logging
import math
import random
import struct
import sys
import wave
from pathlib import Path
from typing import Optional

from snapfloat.config import get_app_data_dir

logger = logging.getLogger(__name__)


def _generate_macos_shutter_wav(target_path: Path) -> bool:
    """
    Synthesize a crisp, authentic macOS-style two-stage mechanical mirror/curtain
    camera shutter sound effect (44.1 kHz, 16-bit mono PCM WAV).
    """
    try:
        sample_rate = 44100
        duration_sec = 0.24
        num_samples = int(sample_rate * duration_sec)

        rng = random.Random(42)  # Deterministic acoustic profile
        samples: list[int] = []

        # Bandpass / resonance state variables for mechanical body filter
        lp1 = 0.0
        lp2 = 0.0

        for i in range(num_samples):
            t = i / sample_rate

            # White noise source
            white = rng.uniform(-1.0, 1.0)

            # Simple 2-pole filter to shape noise into a crisp mechanical snap
            lp1 += 0.58 * (white - lp1)
            lp2 += 0.22 * (lp1 - lp2)
            band_noise = lp1 - lp2

            sample = 0.0

            # --- Stage 1: First curtain release + mirror flip (t = 0.005s .. 0.065s) ---
            if t >= 0.005:
                dt1 = t - 0.005
                # Ultra-sharp initial transient click
                click1_env = math.exp(-dt1 * 180.0)
                # High-pitched metallic contact + body resonance
                metallic1 = (
                    0.55 * math.sin(2.0 * math.pi * 2450.0 * dt1) * math.exp(-dt1 * 320.0)
                    + 0.35 * math.sin(2.0 * math.pi * 1180.0 * dt1) * math.exp(-dt1 * 210.0)
                    + 0.25 * math.sin(2.0 * math.pi * 4200.0 * dt1) * math.exp(-dt1 * 480.0)
                )
                sample += (band_noise * 0.85 * click1_env) + metallic1

            # Brief mechanical travel air/friction between curtains (t = 0.025s .. 0.078s)
            if 0.025 <= t <= 0.080:
                dt_mid = t - 0.025
                mid_env = math.sin(math.pi * (dt_mid / 0.055)) * 0.14
                sample += band_noise * mid_env

            # --- Stage 2: Second curtain latch & dampened thud (t = 0.078s .. 0.220s) ---
            if t >= 0.078:
                dt2 = t - 0.078
                click2_env = math.exp(-dt2 * 135.0)
                # Slightly warmer/lower pitch closure transient
                metallic2 = (
                    0.50 * math.sin(2.0 * math.pi * 1850.0 * dt2) * math.exp(-dt2 * 260.0)
                    + 0.45 * math.sin(2.0 * math.pi * 760.0 * dt2) * math.exp(-dt2 * 150.0)
                    + 0.22 * math.sin(2.0 * math.pi * 3300.0 * dt2) * math.exp(-dt2 * 400.0)
                )
                sample += (band_noise * 0.95 * click2_env) + metallic2

            # Soft master saturation & scaling
            sample = max(-0.98, min(0.98, sample * 0.82))
            samples.append(int(sample * 32767.0))

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            packed = struct.pack(f"<{len(samples)}h", *samples)
            wav_file.writeframes(packed)

        return True
    except Exception as exc:
        logger.warning("Failed to generate macOS shutter WAV at %s: %s", target_path, exc)
        return False


classShutterPathCache: Optional[Path] = None


def ensure_shutter_wav_path() -> Optional[Path]:
    """Return the path to the cached macOS shutter WAV file, generating it if needed."""
    global classShutterPathCache
    if classShutterPathCache is not None and classShutterPathCache.exists():
        return classShutterPathCache

    wav_path = get_app_data_dir() / "macos_shutter.wav"
    if not wav_path.exists() or wav_path.stat().st_size < 1024:
        if not _generate_macos_shutter_wav(wav_path):
            return None

    classShutterPathCache = wav_path
    return wav_path


def play_shutter_sound() -> None:
    """Play the macOS camera shutter sound asynchronously on Windows via winsound."""
    if sys.platform != "win32":
        return

    wav_path = ensure_shutter_wav_path()
    if wav_path is None:
        return

    try:
        import winsound

        flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        winsound.PlaySound(str(wav_path), flags)
    except Exception as exc:
        logger.warning("Failed to play shutter sound: %s", exc)
