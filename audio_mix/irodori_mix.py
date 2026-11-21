#!/usr/bin/env python3
"""Koebuta v3 Audio Mixing Helper: Mix TTS utterances with SFX & ambience WAVs.

Standard-library only (Python 3.10+). Supports 16/24/32-bit PCM and 32-bit IEEE float WAVs,
automatic 48kHz stereo conversion, active-RMS category leveling with max gain cap,
90Hz high-pass filtering, utterance-gap SFX insertion, ducked ambience overlays,
and soft peak limiting (-1.0 dBFS).
"""
from __future__ import annotations

import argparse
from array import array
import json
import math
import os
from pathlib import Path
import struct
import sys
import wave
import zipfile

TARGET_SAMPLE_RATE = 48000

# Category presets relative to TTS active RMS (default TTS active RMS = -18.0 dBFS).
CATEGORIES: dict[str, dict[str, float | bool]] = {
    'action': {
        'rel_db': -8.0,      # Prominent action SE between utterances
        'peak_ceiling_db': -6.0,
        'max_gain_db': 24.0,
        'hpf_hz': 80.0,
    },
    'foley': {
        'rel_db': -16.0,     # Subtle foley (cloth, footsteps, rustling)
        'peak_ceiling_db': -10.0,
        'max_gain_db': 24.0,
        'hpf_hz': 100.0,
    },
    'ambience': {
        'rel_db': -22.0,     # Continuous background ambience under speech
        'peak_ceiling_db': -14.0,
        'max_gain_db': 24.0,
        'hpf_hz': 90.0,
    },
    'distant': {
        'rel_db': -28.0,     # Muffled / behind-door / distant background
        'peak_ceiling_db': -18.0,
        'max_gain_db': 24.0,
        'hpf_hz': 90.0,
    },
}


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def lin_to_db(val: float) -> float:
    return 20.0 * math.log10(val) if val > 1e-9 else -99.9


def read_wav_bytes(data: bytes, label: str = '<memory>') -> tuple[int, int, array, array, str]:
    """Decode PCM (16/24/32-bit) or IEEE 32-bit float WAV into stereo float32 arrays (L, R)."""
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError(f'WAV形式ではありません: {label}')
    pos = 12
    fmt_tag = ch = sr = bits = None
    pcm = None
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        sz = struct.unpack_from('<I', data, pos + 4)[0]
        body = data[pos + 8 : pos + 8 + sz]
        if cid == b'fmt ' and len(body) >= 16:
            fmt_tag, ch, sr, _, _, bits = struct.unpack_from('<HHIIHH', body, 0)
            if fmt_tag == 0xFFFE and len(body) >= 40:
                # WAVE_FORMAT_EXTENSIBLE: check SubFormat first 2 bytes
                sub_tag = struct.unpack_from('<H', body, 24)[0]
                fmt_tag = sub_tag
        elif cid == b'data':
            pcm = body
        pos += 8 + sz + (sz % 2)
    if pcm is None or fmt_tag is None or ch not in (1, 2) or not sr:
        raise ValueError(f'未対応のWAVフォーマットです（1ch/2chのPCMまたは32bit floatに対応）: {label}')

    bps = bits // 8
    total_samples = len(pcm) // bps
    frames = total_samples // ch
    if fmt_tag == 1 and bits == 16:
        raw = array('h')
        raw.frombytes(pcm[: frames * ch * 2])
        if sys.byteorder != 'little':
            raw.byteswap()
        scale = 1.0 / 32768.0
        interleaved = array('f', (v * scale for v in raw))
        fmt_desc = f'{sr}Hz {ch}ch 16bit-PCM'
    elif fmt_tag == 1 and bits == 24:
        scale = 1.0 / 8388608.0
        mv = memoryview(pcm)
        interleaved = array('f', (
            int.from_bytes(mv[i : i + 3], 'little', signed=True) * scale
            for i in range(0, frames * ch * 3, 3)
        ))
        fmt_desc = f'{sr}Hz {ch}ch 24bit-PCM'
    elif fmt_tag == 1 and bits == 32:
        raw = array('i')
        raw.frombytes(pcm[: frames * ch * 4])
        if sys.byteorder != 'little':
            raw.byteswap()
        scale = 1.0 / 2147483648.0
        interleaved = array('f', (v * scale for v in raw))
        fmt_desc = f'{sr}Hz {ch}ch 32bit-PCM'
    elif fmt_tag == 3 and bits == 32:
        interleaved = array('f')
        interleaved.frombytes(pcm[: frames * ch * 4])
        if sys.byteorder != 'little':
            interleaved.byteswap()
        for idx, v in enumerate(interleaved):
            if not math.isfinite(v):
                interleaved[idx] = 0.0
        fmt_desc = f'{sr}Hz {ch}ch 32bit-float'
    else:
        raise ValueError(f'未対応のWAVビット深度/形式です (tag={fmt_tag}, bits={bits}): {label}')

    if ch == 1:
        left = interleaved
        right = array('f', interleaved)
    else:
        left = interleaved[0::2]
        right = interleaved[1::2]
    return sr, ch, left, right, fmt_desc


def read_wav_file(path: Path) -> tuple[int, int, array, array, str]:
    return read_wav_bytes(path.read_bytes(), str(path))


def resample_channel(samples: array, src_sr: int, dst_sr: int) -> array:
    if src_sr == dst_sr or not samples:
        return samples
    n_src = len(samples)
    n_dst = max(1, int(round(n_src * dst_sr / src_sr)))
    ratio = src_sr / dst_sr
    out = array('f', [0.0]) * n_dst
    last = n_src - 1
    for i in range(n_dst):
        pos = i * ratio
        idx = int(pos)
        if idx >= last:
            out[i] = samples[last]
        else:
            frac = pos - idx
            out[i] = samples[idx] * (1.0 - frac) + samples[idx + 1] * frac
    return out


def apply_hpf_1st_order(samples: array, sr: int, cutoff_hz: float) -> array:
    """Apply a lightweight 1st-order high-pass filter to remove low-frequency rumble."""
    if cutoff_hz <= 0.0 or not samples:
        return samples
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / sr
    alpha = rc / (rc + dt)
    out = array('f', [0.0]) * len(samples)
    prev_y = 0.0
    prev_x = samples[0]
    for i, x in enumerate(samples):
        y = alpha * (prev_y + x - prev_x)
        out[i] = y
        prev_y = y
        prev_x = x
    return out


def measure_levels(left: array, right: array, sr: int) -> dict[str, float]:
    """Compute Peak, overall RMS, active RMS (above -50dB or top energy frames), and max 200ms RMS."""
    n = len(left)
    if n == 0:
        return {'peak_db': -99.9, 'rms_db': -99.9, 'active_rms_db': -99.9, 'max_200ms_db': -99.9}

    # Subsample at ~12kHz for fast yet accurate RMS/peak measurement
    stride = max(1, sr // 12000)
    peak = 0.0
    sum_sq = 0.0
    count = 0
    win_samples = max(1, int(0.2 * sr / stride))
    win_energies: list[float] = []
    cur_sq = 0.0
    cur_cnt = 0

    for i in range(0, n, stride):
        lv = left[i]
        rv = right[i]
        al = abs(lv)
        ar = abs(rv)
        if al > peak:
            peak = al
        if ar > peak:
            peak = ar
        e = 0.5 * (lv * lv + rv * rv)
        sum_sq += e
        count += 1
        cur_sq += e
        cur_cnt += 1
        if cur_cnt >= win_samples:
            win_energies.append(cur_sq / cur_cnt)
            cur_sq = 0.0
            cur_cnt = 0
    if cur_cnt > 0:
        win_energies.append(cur_sq / cur_cnt)

    rms = math.sqrt(sum_sq / count) if count else 0.0
    max_win = math.sqrt(max(win_energies)) if win_energies else rms

    # Active RMS: average energy of 200ms windows within 20 dB of the loudest window
    if win_energies and max_win > 1e-9:
        gate = (max_win * db_to_lin(-20.0)) ** 2
        active_wins = [e for e in win_energies if e >= gate]
        active_rms = math.sqrt(sum(active_wins) / len(active_wins)) if active_wins else rms
    else:
        active_rms = rms

    return {
        'peak_db': round(lin_to_db(peak), 2),
        'rms_db': round(lin_to_db(rms), 2),
        'active_rms_db': round(lin_to_db(active_rms), 2),
        'max_200ms_db': round(lin_to_db(max_win), 2),
    }


def compute_category_gain(
    stats: dict[str, float],
    category: str,
    target_tts_rms_db: float,
    *,
    gain_offset_db: float = 0.0,
    max_gain_db: float | None = None,
) -> tuple[float, bool]:
    """Compute gain in dB for an SFX/ambience asset based on category preset and caps."""
    if category not in CATEGORIES:
        raise ValueError(f'未対応のカテゴリです: {category}（選択可能: {", ".join(CATEGORIES)}）')
    preset = CATEGORIES[category]
    target_rms = target_tts_rms_db + float(preset['rel_db']) + float(gain_offset_db)
    src_rms = stats['active_rms_db']
    if src_rms <= -95.0:
        return 0.0, False
    desired_gain = target_rms - src_rms
    cap = float(preset['max_gain_db']) if max_gain_db is None else float(max_gain_db)
    capped = False
    if desired_gain > cap:
        desired_gain = cap
        capped = True
    # Also respect peak ceiling so transients don't jump too loudly
    peak_ceiling = float(preset['peak_ceiling_db']) + float(gain_offset_db)
    if stats['peak_db'] + desired_gain > peak_ceiling:
        desired_gain = peak_ceiling - stats['peak_db']
    return round(desired_gain, 2), capped


def apply_fade(left: array, right: array, sr: int, fade_in_ms: int, fade_out_ms: int) -> None:
    n = len(left)
    fi = min(n, max(0, int(sr * fade_in_ms / 1000)))
    fo = min(n, max(0, int(sr * fade_out_ms / 1000)))
    if fi > 0:
        inv = 1.0 / fi
        for i in range(fi):
            g = i * inv
            left[i] *= g
            right[i] *= g
    if fo > 0:
        inv = 1.0 / fo
        start = n - fo
        for i in range(fo):
            g = (fo - i) * inv
            left[start + i] *= g
            right[start + i] *= g


def slice_audio(left: array, right: array, sr: int, start_ms: int | None, end_ms: int | None) -> tuple[array, array]:
    n = len(left)
    a = max(0, int(sr * start_ms / 1000)) if start_ms is not None else 0
    b = min(n, int(sr * end_ms / 1000)) if end_ms is not None else n
    if a >= b:
        return array('f'), array('f')
    return left[a:b], right[a:b]


def write_stereo_wav16(path: Path, left: array, right: array, sr: int, ceiling_db: float = -1.0) -> dict[str, float]:
    """Soft-limit at ceiling_db and write 16-bit PCM stereo WAV."""
    ceiling = db_to_lin(ceiling_db)
    knee = ceiling * 0.85
    n = len(left)
    pcm = array('h', [0]) * (n * 2)
    peak_out = 0.0
    limited_samples = 0

    def soft_limit(x: float) -> float:
        nonlocal limited_samples
        ax = abs(x)
        if ax <= knee:
            return x
        limited_samples += 1
        # Smooth tanh saturation from knee to ceiling
        excess = (ax - knee) / max(1e-6, (ceiling - knee))
        y = knee + (ceiling - knee) * math.tanh(excess)
        return y if x >= 0.0 else -y

    for i in range(n):
        lv = soft_limit(left[i])
        rv = soft_limit(right[i])
        al = abs(lv)
        ar = abs(rv)
        if al > peak_out:
            peak_out = al
        if ar > peak_out:
            peak_out = ar
        pcm[i * 2] = max(-32768, min(32767, int(round(lv * 32767.0))))
        pcm[i * 2 + 1] = max(-32768, min(32767, int(round(rv * 32767.0))))

    if sys.byteorder != 'little':
        pcm.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output_file, wave.open(output_file, 'wb') as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(sr)
        out.writeframes(pcm.tobytes())
    return {
        'duration_seconds': round(n / sr, 3),
        'output_peak_db': round(lin_to_db(peak_out), 2),
        'limited_samples': limited_samples,
    }


def init_plan(plan_path: Path, run_dir: Path, scenario_path: Path | None = None, overwrite: bool = False) -> int:
    plan_path = plan_path.expanduser().resolve()
    if plan_path.exists() and not overwrite:
        raise FileExistsError(f'出力先が既に存在します（上書きする場合は --overwrite）: {plan_path}')
    run_dir = run_dir.expanduser().resolve()
    seg_zip = run_dir / 'segments.zip'
    plan_json = run_dir / 'plan.json'
    if not seg_zip.is_file():
        raise FileNotFoundError(f'segments.zip が見つかりません: {seg_zip}')
    if not plan_json.is_file():
        raise FileNotFoundError(f'plan.json が見つかりません: {plan_json}')

    cli_plan = json.loads(plan_json.read_text(encoding='utf-8'))
    notes_map: dict[str, list[str]] = {}
    if scenario_path is not None:
        sc = json.loads(scenario_path.expanduser().resolve().read_text(encoding='utf-8'))
        for row in sc.get('segments', []):
            if isinstance(row, dict) and row.get('id') and row.get('notes'):
                notes_map[row['id']] = list(row['notes'])

    with zipfile.ZipFile(seg_zip, 'r') as zf:
        zip_files = [name for name in zf.namelist() if name.startswith('audio/') and name.endswith('.wav')]

    utterances = []
    for req in cli_plan.get('requests', []):
        uid = req['id']
        sid = req.get('segment_id', uid)
        # CLI filenames end with the fingerprint and take ID after the full utterance ID.
        matched = next((f for f in zip_files
                        if f.removeprefix('audio/').removesuffix('.wav').rsplit('_', 2)[0] == uid), None)
        if matched is None:
            raise FileNotFoundError(f'segments.zip 内に発話 {uid} のWAVが見つかりません')
        entry: dict = {
            'id': uid,
            'file': matched,
            'pause_after_ms': int(req.get('pause_after_ms', 280)),
        }
        if sid in notes_map:
            entry['notes'] = notes_map[sid]
            entry['insert_after'] = []
        utterances.append(entry)

    try:
        rel_zip = Path(os.path.relpath(seg_zip, plan_path.parent)).as_posix()
    except ValueError:
        rel_zip = str(seg_zip)

    mix_doc = {
        'target_tts_rms_db': -18.0,
        'sample_rate': TARGET_SAMPLE_RATE,
        'segments_zip': rel_zip,
        'leading_pause_ms': int(cli_plan.get('execution', {}).get('leading_pause_ms', 0)),
        'trailing_pause_ms': int(cli_plan.get('execution', {}).get('trailing_pause_ms', 0)),
        'utterances': utterances,
        'overlays': [],
    }
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(mix_doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'MIX_PLAN_READY {plan_path} ({len(utterances)} utterances)')
    return 0


def inspect_wavs(paths: list[Path], target_tts_rms_db: float) -> int:
    for raw in paths:
        p = raw.expanduser().resolve()
        sr, _, left, right, desc = read_wav_file(p)
        stats = measure_levels(left, right, sr)
        dur = len(left) / sr
        print(f'=== {p.name} ({desc}, {dur:.2f}s) ===')
        print(f'  Peak: {stats["peak_db"]:6.1f} dB | RMS: {stats["rms_db"]:6.1f} dB | ActiveRMS: {stats["active_rms_db"]:6.1f} dB')
        rec = []
        for cat in CATEGORIES:
            g, capped = compute_category_gain(stats, cat, target_tts_rms_db)
            tag = '(上限到達)' if capped else ''
            rec.append(f'{cat}: {g:+.1f}dB{tag}')
        print('  推奨ゲイン (TTS=-18dB基準): ' + ' / '.join(rec))
    return 0


def run_mix(plan_path: Path, out_path: Path | None, *, dry_run: bool = False) -> int:
    if not dry_run:
        if out_path is None:
            raise ValueError('書き出し先 --out <出力.wav> を指定してください')
        out_path = out_path.expanduser().absolute()
        if out_path.exists() or out_path.is_symlink():
            raise FileExistsError(f'出力先が既に存在します。別のWAVファイル名を指定してください: {out_path}')

    plan_path = plan_path.expanduser().resolve()
    base_dir = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding='utf-8'))

    sr = int(plan.get('sample_rate', TARGET_SAMPLE_RATE))
    target_tts_rms = float(plan.get('target_tts_rms_db', -18.0))
    explicit_tts_gain = plan.get('tts_gain_db')
    utterances = plan.get('utterances', [])
    if not utterances:
        raise ValueError('utterances が空です')

    seg_zip_rel = plan.get('segments_zip')
    zf = zipfile.ZipFile((base_dir / seg_zip_rel).resolve(), 'r') if seg_zip_rel else None

    def load_audio_source(spec_path: str, from_zip: bool = False) -> tuple[array, array, str]:
        if from_zip and zf is not None:
            src_sr, _, l_arr, r_arr, desc = read_wav_bytes(zf.read(spec_path), spec_path)
        else:
            p = Path(spec_path).expanduser()
            if not p.is_absolute():
                p = (base_dir / p).resolve()
            src_sr, _, l_arr, r_arr, desc = read_wav_file(p)
        if src_sr != sr:
            l_arr = resample_channel(l_arr, src_sr, sr)
            r_arr = resample_channel(r_arr, src_sr, sr)
            desc += f' -> {sr}Hz'
        return l_arr, r_arr, desc

    try:
        # 1. Load all TTS utterances and measure overall TTS active RMS
        loaded_utts = []
        all_tts_rms_vals = []
        for u in utterances:
            l_arr, r_arr, desc = load_audio_source(u['file'], from_zip=(zf is not None and not Path(u['file']).is_absolute()))
            stats = measure_levels(l_arr, r_arr, sr)
            if stats['active_rms_db'] > -90.0:
                all_tts_rms_vals.append(stats['active_rms_db'])
            loaded_utts.append((u, l_arr, r_arr, stats, desc))

        avg_tts_rms = sum(all_tts_rms_vals) / len(all_tts_rms_vals) if all_tts_rms_vals else target_tts_rms
        tts_gain_db = float(explicit_tts_gain) if explicit_tts_gain is not None else round(target_tts_rms - avg_tts_rms, 2)
        tts_gain_lin = db_to_lin(tts_gain_db)

        # 2. Build main timeline (utterances + inserted SEs + pauses) and record utterance spans
        timeline_items: list[tuple[str, str, int, int, array | None, array | None]] = []
        cursor = max(0, int(sr * int(plan.get('leading_pause_ms', 0)) / 1000))
        utt_spans: dict[str, tuple[int, int]] = {}
        speech_regions: list[tuple[int, int]] = []
        se_reports = []

        for idx, (u, l_arr, r_arr, _, _) in enumerate(loaded_utts):
            uid = u['id']
            start_frame = cursor
            end_frame = cursor + len(l_arr)
            utt_spans[uid] = (start_frame, end_frame)
            speech_regions.append((start_frame, end_frame))
            timeline_items.append(('tts', uid, start_frame, end_frame, l_arr, r_arr))
            cursor = end_frame

            inserts = u.get('insert_after') or []
            if inserts:
                for ins in inserts:
                    cat = ins.get('category', 'action')
                    pre_ms = int(ins.get('pre_gap_ms', 200))
                    post_ms = int(ins.get('post_gap_ms', 250))
                    se_l, se_r, se_desc = load_audio_source(ins['wav'], from_zip=False)
                    se_l, se_r = slice_audio(se_l, se_r, sr, ins.get('trim_start_ms'), ins.get('trim_end_ms'))
                    hpf_hz = float(ins.get('hpf_hz', CATEGORIES[cat]['hpf_hz']))
                    if hpf_hz > 0:
                        se_l = apply_hpf_1st_order(se_l, sr, hpf_hz)
                        se_r = apply_hpf_1st_order(se_r, sr, hpf_hz)
                    se_stats = measure_levels(se_l, se_r, sr)
                    gain_db, capped = compute_category_gain(
                        se_stats,
                        cat,
                        target_tts_rms,
                        gain_offset_db=float(ins.get('gain_offset_db', 0.0)),
                        max_gain_db=ins.get('max_gain_db'),
                    )
                    apply_fade(se_l, se_r, sr, int(ins.get('fade_in_ms', 30)), int(ins.get('fade_out_ms', 50)))
                    g_lin = db_to_lin(gain_db)
                    for i in range(len(se_l)):
                        se_l[i] *= g_lin
                        se_r[i] *= g_lin

                    cursor += max(0, int(sr * pre_ms / 1000))
                    se_start = cursor
                    se_end = cursor + len(se_l)
                    timeline_items.append(('se', ins['wav'], se_start, se_end, se_l, se_r))
                    cursor = se_end + max(0, int(sr * post_ms / 1000))
                    se_reports.append({
                        'type': 'insert_after',
                        'after_id': uid,
                        'wav': ins['wav'],
                        'format': se_desc,
                        'category': cat,
                        'source_active_rms_db': se_stats['active_rms_db'],
                        'applied_gain_db': gain_db,
                        'gain_capped': capped,
                        'duration_seconds': round(len(se_l) / sr, 3),
                    })
            else:
                if idx < len(loaded_utts) - 1:
                    cursor += max(0, int(sr * int(u.get('pause_after_ms', 280)) / 1000))

        cursor += max(0, int(sr * int(plan.get('trailing_pause_ms', 0)) / 1000))
        total_frames = cursor

        # 3. Prepare overlays (ambience / background tracks)
        overlay_tracks = []
        for ov in plan.get('overlays', []):
            cat = ov.get('category', 'ambience')
            start_id = ov.get('start_id')
            end_id = ov.get('end_id')
            if start_id and start_id not in utt_spans:
                raise ValueError(f'overlays.start_id が見つかりません: {start_id}')
            if end_id and end_id not in utt_spans:
                raise ValueError(f'overlays.end_id が見つかりません: {end_id}')
            ov_start = utt_spans[start_id][0] if start_id else 0
            ov_end = utt_spans[end_id][1] if end_id else total_frames
            if ov_end <= ov_start:
                raise ValueError(f'overlay 区間が不正です: {start_id} .. {end_id}')

            ov_l, ov_r, ov_desc = load_audio_source(ov['wav'], from_zip=False)
            ov_l, ov_r = slice_audio(ov_l, ov_r, sr, ov.get('trim_start_ms'), ov.get('trim_end_ms'))
            hpf_hz = float(ov.get('hpf_hz', CATEGORIES[cat]['hpf_hz']))
            if hpf_hz > 0:
                ov_l = apply_hpf_1st_order(ov_l, sr, hpf_hz)
                ov_r = apply_hpf_1st_order(ov_r, sr, hpf_hz)
            ov_stats = measure_levels(ov_l, ov_r, sr)
            gain_db, capped = compute_category_gain(
                ov_stats,
                cat,
                target_tts_rms,
                gain_offset_db=float(ov.get('gain_offset_db', 0.0)),
                max_gain_db=ov.get('max_gain_db'),
            )
            duck_db = float(ov.get('duck_db', -4.0 if cat == 'ambience' else 0.0))
            overlay_tracks.append((ov, ov_start, ov_end, ov_l, ov_r, gain_db, duck_db))
            se_reports.append({
                'type': 'overlay',
                'span': f'{start_id or "START"}..{end_id or "END"}',
                'wav': ov['wav'],
                'format': ov_desc,
                'category': cat,
                'source_active_rms_db': ov_stats['active_rms_db'],
                'applied_gain_db': gain_db,
                'duck_db': duck_db,
                'gain_capped': capped,
                'span_seconds': round((ov_end - ov_start) / sr, 3),
            })

        report = {
            'status': 'dry_run_ok' if dry_run else 'mixed',
            'sample_rate': sr,
            'channels': 2,
            'utterance_count': len(loaded_utts),
            'measured_tts_active_rms_db': round(avg_tts_rms, 2),
            'target_tts_rms_db': target_tts_rms,
            'applied_tts_gain_db': tts_gain_db,
            'total_duration_seconds': round(total_frames / sr, 3),
            'tracks': se_reports,
        }
        if dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        assert out_path is not None

        # 4. Render master stereo float32 buffer
        mix_l = array('f', [0.0]) * total_frames
        mix_r = array('f', [0.0]) * total_frames

        for kind, _, st, en, l_arr, r_arr in timeline_items:
            if l_arr is None or r_arr is None:
                continue
            g = tts_gain_lin if kind == 'tts' else 1.0
            for i in range(en - st):
                mix_l[st + i] += l_arr[i] * g
                mix_r[st + i] += r_arr[i] * g

        # Build smooth ducking envelope (1.0 during silence, duck_lin during speech)
        for ov, ov_start, ov_end, ov_l, ov_r, gain_db, duck_db in overlay_tracks:
            span_len = ov_end - ov_start
            if not ov_l or span_len <= 0:
                continue
            loop = bool(ov.get('loop', True))
            src_len = len(ov_l)
            buf_l = array('f', [0.0]) * span_len
            buf_r = array('f', [0.0]) * span_len
            if loop:
                for i in range(span_len):
                    idx_s = i % src_len
                    buf_l[i] = ov_l[idx_s]
                    buf_r[i] = ov_r[idx_s]
            else:
                copy_len = min(span_len, src_len)
                buf_l[:copy_len] = ov_l[:copy_len]
                buf_r[:copy_len] = ov_r[:copy_len]

            apply_fade(buf_l, buf_r, sr, int(ov.get('fade_in_ms', 800)), int(ov.get('fade_out_ms', 1000)))
            base_g = db_to_lin(gain_db)
            duck_g = db_to_lin(duck_db)

            # Fast block-based ducking envelope (10ms steps with linear interpolation)
            if duck_db < -0.1:
                step = max(1, sr // 100)  # 10ms
                env_blocks = (span_len + step - 1) // step + 1
                is_speech = [False] * env_blocks
                for sp_a, sp_b in speech_regions:
                    a = max(0, sp_a - ov_start)
                    b = min(span_len, sp_b - ov_start)
                    if a < b:
                        ba = a // step
                        bb = min(env_blocks - 1, b // step)
                        for bi in range(ba, bb + 1):
                            is_speech[bi] = True
                # Smooth attack (~80ms) and release (~250ms)
                env = [1.0] * env_blocks
                cur = 1.0
                for bi in range(env_blocks):
                    target = duck_g if is_speech[bi] else 1.0
                    alpha = 0.25 if target < cur else 0.08
                    cur = cur + (target - cur) * alpha
                    env[bi] = cur
                for i in range(span_len):
                    g = base_g * env[i // step]
                    mix_l[ov_start + i] += buf_l[i] * g
                    mix_r[ov_start + i] += buf_r[i] * g
            else:
                for i in range(span_len):
                    mix_l[ov_start + i] += buf_l[i] * base_g
                    mix_r[ov_start + i] += buf_r[i] * base_g

        out_info = write_stereo_wav16(out_path, mix_l, mix_r, sr, ceiling_db=-1.0)
        report.update(out_info)
        report['output_wav'] = str(out_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f'MIX_READY {out_path}', flush=True)
        return 0
    finally:
        if zf is not None:
            zf.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Koebuta v3 効果音・環境音 自動ミキシング補助スクリプト（標準Pythonのみ）'
    )
    parser.add_argument('--init-plan', type=Path, metavar='JSON', help='CLI出力から mix_plan.json のひな形を生成')
    parser.add_argument('--run-dir', type=Path, help='Koebuta CLI の生成出力フォルダー（--init-plan と併用）')
    parser.add_argument('--scenario', type=Path, help='notes を転記するシナリオJSON（--init-plan と併用・任意）')
    parser.add_argument('--overwrite', action='store_true', help='--init-plan 時に既存JSONを上書きする')
    parser.add_argument('--inspect', type=Path, nargs='+', metavar='WAV', help='効果音・環境音WAVの音量と推奨ゲインを表示')
    parser.add_argument('--plan', type=Path, help='ミキシング計画JSON（mix_plan.json）')
    parser.add_argument('--out', type=Path, help='合成後のステレオWAVの新規出力先')
    parser.add_argument('--dry-run', action='store_true', help='WAVを書き出さず、測定値と適用ゲイン計画のみ表示')
    args = parser.parse_args(argv)

    if args.inspect:
        return inspect_wavs(args.inspect, target_tts_rms_db=-18.0)
    if args.init_plan:
        if not args.run_dir:
            parser.error('--init-plan には --run-dir <CLI出力フォルダー> が必要です')
        return init_plan(args.init_plan, args.run_dir, args.scenario, overwrite=args.overwrite)
    if args.plan:
        return run_mix(args.plan, args.out, dry_run=args.dry_run)
    parser.error('--inspect / --init-plan / --plan のいずれかを指定してください（--help で詳細表示）')
    return 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
