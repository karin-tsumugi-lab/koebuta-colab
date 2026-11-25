"""44.1 kHz 16-bit mono PCM WAV inspection, RMS normalization, assembly, and segments.zip packaging.

Note on normalization scope:
- `assemble_wavs(..., normalize_rms_db=...)` normalizes utterance levels when building `result.wav`.
- Individual utterance WAVs stored in `segments.zip` remain unmodified raw engine outputs so
  downstream tools (such as `audio_mix`) can apply their own gain staging without double compression.
"""
from __future__ import annotations

import array
import math
import sys
import wave
import zipfile
from pathlib import Path

from .core import DEFAULT_SAMPLE_RATE, file_hash

_STREAM_FRAMES = 262144  # ~512 KiB per chunk (16-bit mono), keeping peak RAM < 4 MiB even on multi-hour WAVs


def wav_info(path: str | Path) -> dict:
    p = Path(path)
    peak_int = 0
    active_sq = 0.0
    active_cnt = 0
    actual_frames = 0

    with wave.open(str(p), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        frames = wf.getnframes()
        frame_bytes = ch * sw
        if ch <= 0 or sw <= 0 or sr <= 0:
            raise ValueError(f"不正なWAVヘッダです: {p}")

        while True:
            chunk = wf.readframes(_STREAM_FRAMES)
            if not chunk:
                break
            if len(chunk) % frame_bytes != 0:
                raise ValueError(f"WAVフレーム境界が途中で切断されています: {p}")
            actual_frames += len(chunk) // frame_bytes
            if sw == 2:
                buf = array.array("h")
                buf.frombytes(chunk)
                if sys.byteorder != "little":
                    buf.byteswap()
                if buf:
                    chunk_peak = max(abs(min(buf)), abs(max(buf)))
                    if chunk_peak > peak_int:
                        peak_int = chunk_peak
                    for s in buf:
                        if abs(s) >= 184:
                            v = s / 32768.0
                            active_sq += v * v
                            active_cnt += 1

    if actual_frames != frames:
        raise ValueError(f"WAVデータ長がヘッダと一致しません (header={frames}, actual={actual_frames}): {p}")

    duration = frames / sr if sr else 0.0
    info = {
        "bytes": p.stat().st_size,
        "channels": ch,
        "sampwidth": sw,
        "sample_rate": sr,
        "frames": frames,
        "seconds": round(duration, 3),
        "sha256": file_hash(p),
    }
    if sw == 2 and frames > 0:
        peak = peak_int / 32768.0
        rms_active = math.sqrt(active_sq / active_cnt) if active_cnt else 0.0
        info["peak_dbfs"] = round(20 * math.log10(peak), 2) if peak > 0 else -120.0
        info["rms_active_dbfs"] = round(20 * math.log10(rms_active), 2) if rms_active > 0 else -120.0
    return info


def _normalize_pcm16_bytes(
    raw: bytes,
    *,
    target_rms_db: float,
    max_boost_db: float = 12.0,
    max_cut_db: float = 18.0,
    limiter_db: float = -1.0,
) -> tuple[bytes, float]:
    """Apply bounded active-RMS loudness normalization with a soft tanh limiter."""
    if not raw:
        return raw, 0.0
    if len(raw) % 2 != 0:
        raise ValueError("16bit PCMデータのバイト長が奇数です")

    ceiling = 10.0 ** (limiter_db / 20.0)
    knee = ceiling * 0.85

    try:
        import numpy as np  # Fast vectorized path when available (e.g. on Colab)

        arr = np.frombuffer(raw, dtype="<i2").astype(np.float64)
        active_mask = np.abs(arr) >= 184.0
        if not np.any(active_mask):
            return raw, 0.0
        rms = float(np.sqrt(np.mean((arr[active_mask] / 32768.0) ** 2)))
        cur_db = 20.0 * math.log10(rms)
        gain_db = max(-max_cut_db, min(max_boost_db, target_rms_db - cur_db))
        gain = 10.0 ** (gain_db / 20.0)
        v = (arr / 32768.0) * gain
        av = np.abs(v)
        over = av > knee
        if np.any(over):
            excess = (av[over] - knee) / max(1e-9, ceiling - knee)
            limited = knee + (ceiling - knee) * np.tanh(excess)
            v[over] = np.where(v[over] >= 0, limited, -limited)
        out_np = np.clip(np.rint(v * 32767.0), -32768, 32767).astype("<i2")
        return out_np.tobytes(), round(gain_db, 2)
    except ImportError:
        pass

    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    active_sq = 0.0
    active_cnt = 0
    for s in samples:
        if abs(s) >= 184:
            v = s / 32768.0
            active_sq += v * v
            active_cnt += 1
    if active_cnt == 0:
        return raw, 0.0
    rms = math.sqrt(active_sq / active_cnt)
    cur_db = 20.0 * math.log10(rms)
    gain_db = max(-max_cut_db, min(max_boost_db, target_rms_db - cur_db))
    gain = 10.0 ** (gain_db / 20.0)

    out = array.array("h", [0] * len(samples))
    for i, s in enumerate(samples):
        v = (s / 32768.0) * gain
        av = abs(v)
        if av > knee:
            excess = (av - knee) / max(1e-9, ceiling - knee)
            limited = knee + (ceiling - knee) * math.tanh(excess)
            v = limited if v >= 0 else -limited
        iv = int(round(v * 32767.0))
        out[i] = -32768 if iv < -32768 else (32767 if iv > 32767 else iv)
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes(), round(gain_db, 2)


def assemble_wavs(
    takes: list[dict],
    out_wav: str | Path,
    *,
    expected_sample_rate: int = DEFAULT_SAMPLE_RATE,
    normalize_rms_db: float | None = None,
) -> dict:
    """Concatenate utterance WAVs with `pause_after_ms` silence gaps (no trailing silence)."""
    if not takes:
        raise ValueError("結合対象の発話WAVがありません")
    out_path = Path(out_wav)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_frames = 0
    applied_gains: dict[str, float] = {}
    with wave.open(str(out_path), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(expected_sample_rate)
        for idx, take in enumerate(takes):
            src_path = Path(take["path"])
            with wave.open(str(src_path), "rb") as src:
                if src.getnchannels() != 1 or src.getsampwidth() != 2 or src.getframerate() != expected_sample_rate:
                    raise ValueError(
                        f"WAV形式が一致しません ({take['segment_id']}): "
                        f"{src.getframerate()}Hz {src.getnchannels()}ch {src.getsampwidth() * 8}bit "
                        f"(期待: {expected_sample_rate}Hz 1ch 16bit)"
                    )
                frames = src.getnframes()
                pcm = src.readframes(frames)
                if len(pcm) != frames * 2:
                    raise ValueError(
                        f"WAVデータが途中切断されています ({take['segment_id']}): expected {frames * 2}B, got {len(pcm)}B"
                    )
                if normalize_rms_db is not None:
                    pcm, gain_db = _normalize_pcm16_bytes(pcm, target_rms_db=float(normalize_rms_db))
                    applied_gains[take["segment_id"]] = gain_db
                dst.writeframes(pcm)
                total_frames += frames
            if idx < len(takes) - 1:
                pause_ms = int(take.get("pause_after_ms", 0))
                if pause_ms > 0:
                    silence_frames = int(round(expected_sample_rate * pause_ms / 1000.0))
                    dst.writeframes(b"\x00\x00" * silence_frames)
                    total_frames += silence_frames

    meta = wav_info(out_path)
    if meta["frames"] != total_frames:
        raise RuntimeError("結合WAVのフレーム数検証に失敗しました")
    if applied_gains:
        meta["normalize_rms_db"] = float(normalize_rms_db)
        meta["applied_gains_db"] = applied_gains
    return meta


def pack_segments_zip(takes: list[dict], out_zip: str | Path) -> dict:
    zip_path = Path(out_zip)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for take in takes:
            zf.write(take["path"], f"audio/{take['filename']}")
    return {"file": zip_path.name, "bytes": zip_path.stat().st_size, "sha256": file_hash(zip_path)}
