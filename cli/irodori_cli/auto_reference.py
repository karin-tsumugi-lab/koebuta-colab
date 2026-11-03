"""Deterministic reference preparation; no model imports or host GPU work."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import re
import struct
import uuid

from .core import atomic_json, digest, file_hash, identifier
from .jobs import inside, job_lock, wav_info
from .text_conversion import convert_project


def configuration(raw):
    if (not isinstance(raw, dict) or set(raw) - {'version', 'selections', 'sourceSegments'}
            or type(raw.get('version')) is not int or raw.get('version') != 1):
        raise ValueError('autoReferenceはversion: 1とselectionsのオブジェクトです')
    selections = raw.get('selections', {})
    if not isinstance(selections, dict):
        raise ValueError('autoReference.selectionsは話者ID（sharedではshared）→発話IDです')
    for group, segment in selections.items():
        identifier(group, 'reference group')
        identifier(segment, 'reference segment', 64)
    clean = {'version': 1, 'selections': dict(selections)}
    if 'sourceSegments' in raw:
        sources = raw['sourceSegments']
        if not isinstance(sources, dict) or len(sources) > 2000:
            raise ValueError('autoReference.sourceSegmentsは分割片ID→元発話IDのオブジェクトです')
        for segment, source in sources.items():
            identifier(segment, 'reference segment', 64)
            identifier(source, 'source segment', 64)
        clean['sourceSegments'] = dict(sources)
    return clean


def validate_supplied(path):
    """Validate the WAV container, not its spoken content or voice quality."""
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('参照音声は既存ファイルを指定してください')
    # Do not use wave.open here: it rejects valid IEEE-float WAVs that the
    # upstream soundfile decoder accepts. Inspect RIFF bounds, not spoken content.
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
            raise ValueError('指定された参照WAVが破損しているか未対応です')
        limit = struct.unpack('<I', header[4:8])[0] + 8
        if limit > path.stat().st_size:
            raise ValueError('参照WAVが途中で欠損しています')
        fmt = None
        data_sizes = []
        while stream.tell() < limit:
            chunk = stream.read(8)
            if len(chunk) != 8:
                raise ValueError('参照WAVのチャンクが欠損しています')
            size = struct.unpack('<I', chunk[4:])[0]
            end = stream.tell() + size
            if end > limit:
                raise ValueError('参照WAVのフレームが欠損しています')
            if chunk[:4] == b'fmt ':
                if size < 16:
                    raise ValueError('参照WAVの形式情報が欠損しています')
                fmt = struct.unpack('<HHIIHH', stream.read(16))
            elif chunk[:4] == b'data':
                data_sizes.append(size)
            stream.seek(min(limit, end + size % 2))
        if fmt is None or not data_sizes or not any(data_sizes):
            raise ValueError('参照WAVの音声が空です')
        encoding, channels, rate, _, align, bits = fmt
        if channels <= 0 or rate <= 0 or align <= 0:
            raise ValueError('参照WAVの形式情報が不正です')
        if encoding in (1, 3) and (bits <= 0 or bits % 8 or align != channels * (bits // 8)
                                  or any(size % align for size in data_sizes)):
            raise ValueError('参照WAVのフレームが不正です')
    return str(path)


def reference_plan(project, voices):
    """Return an effective project and reference groups without creating files."""
    effective = copy.deepcopy(project)
    cfg = effective.pop('autoReference', None)
    if cfg is None:
        return effective, []
    cfg = configuration(cfg)
    for path in voices.values():
        validate_supplied(path)
    shared = project['reading'] == 'shared'
    roles = {r['id']: r for r in effective['roles']}
    converted = {r['id']: r for r in convert_project(project)}
    speech = [s for s in project['segments'] if converted[s['id']]['segment_type'] == 'speech']
    groups = {'shared': speech} if shared else {key: [s for s in speech if s['role'] == key] for key in roles}
    if set(cfg['selections']) - set(groups):
        raise ValueError('autoReference.selectionsに未登録の声グループがあります')
    planned = []
    for group, segments in groups.items():
        if not segments:
            continue
        role = roles[segments[0]['role']]
        clone = project['voiceMode'] == 'clone' if shared or role['voice'] == 'voice_a' else role['voice'] != 'design'
        profile = 'voice_a' if shared else role['voice']
        selected = cfg['selections'].get(group)
        if not clone or profile in voices:
            if selected:
                raise ValueError(f'{group}: 明示WAVまたは参照なし指定に自動参照の選択は使えません')
            planned.append({'group': group, 'mode': 'supplied' if clone else 'design',
                            'profile': profile if clone else None, 'utterances': [s['id'] for s in segments]})
            continue
        candidates = [s for s in segments if 20 <= len(converted[s['id']]['tts_text']) <= 100
                      and s['emotion'] == 'neutral'
                      and not re.search(r'[!！?？…⋯]|\.{2,}', converted[s['id']]['tts_text'])
                      and not converted[s['id']]['blocking']]
        if selected and selected not in {s['id'] for s in candidates}:
            raise ValueError(f'{group}: 自動参照の指定文は20～100文字の平常発話を選んでください')
        chosen = next((s for s in candidates if s['id'] == selected), None) if selected else min(
            candidates, key=lambda s: abs(len(converted[s['id']]['tts_text']) - 60), default=None)
        caption = project['baseCaption'] if shared else role['caption']
        if not caption.strip():
            raise ValueError(f'{group}: 参照未設定の声には声質説明が必要です')
        origins = cfg.get('sourceSegments', {})
        original_count = len({origins.get(s['id'], s['id']) for s in segments})
        automatic = original_count > 1 and chosen is not None
        if selected and not automatic:
            raise ValueError(f'{group}: 単一発話には自動参照を作りません')
        # Generated profile names cannot collide with user-assigned profiles.
        generated_profile = 'auto_' + digest(group)[:24]
        if generated_profile in voices or any(r['voice'] == generated_profile for r in roles.values()):
            raise ValueError('自動参照用プロファイルIDが既存の割当と競合しています')
        if shared:
            effective['voiceMode'] = 'clone' if automatic else 'design'
            generated_profile = 'voice_a'
        else:
            roles[group]['voice'] = generated_profile if automatic else 'design'
        row = {'group': group, 'mode': 'automatic' if automatic else 'fallback',
               'profile': generated_profile if automatic else None,
               'utterances': [s['id'] for s in segments]}
        if automatic:
            row.update(segment=chosen['id'], text=converted[chosen['id']]['tts_text'], caption=caption,
                       request={'text': converted[chosen['id']]['tts_text'], 'caption': caption,
                                'no_ref': True, 'num_steps': project['steps'], 'seed': project['seed'],
                                'max_seconds': 30.0})
        else:
            row['warning'] = '参照なしで生成します。発話間で同じ声になる保証はありません'
        planned.append(row)
    return effective, planned


def prepare_references(project, voices, job, infer, engine):
    """Commit immutable references before any final speech can be synthesized.

    Metadata is committed per reference. A crash keeps verified earlier entries;
    incomplete temporary files are never reusable. Old takes stay immutable and
    become ineligible through changed reference-dependent speech fingerprints.
    """
    from .core import read_json
    effective, groups = reference_plan(project, voices)
    resolved = dict(voices)
    contexts = {}
    job = Path(job)
    metadata = job / 'references.json'
    with job_lock(job):
        state = read_json(metadata) if metadata.exists() else {'version': 1, 'entries': {}}
        if state.get('version') != 1 or not isinstance(state.get('entries'), dict):
            raise ValueError('自動参照メタデータの形式が不正です')
        for row in groups:
            if row['mode'] != 'automatic':
                continue
            if any((job / name).exists() for name in ('.pause', '.stop')):
                raise RuntimeError('自動参照の準備を中断しました。保存済み参照は再開時に再利用します')
            identity = {'version': 1, 'group': row['group'], 'segment': row['segment'],
                        'request': row['request'], 'engine': engine}
            signature = digest(identity)
            previous = state['entries'].get(row['group'])
            if previous and previous.get('signature') == signature:
                path = inside(job, previous['file'])
                # A corrupt committed reference must never silently select a new voice.
                if file_hash(path) != previous['sha256'] or wav_info(path) != previous['audio']:
                    raise ValueError(f'{row["group"]}: 保存済み自動参照が破損しています。復旧してください')
                print(f'PROGRESS 自動参照を再利用: {row["group"]}', flush=True)
            else:
                print(f'PROGRESS 自動参照を準備: {row["group"]} / {row["segment"]}', flush=True)
                path = job / 'references' / f'{signature}_{uuid.uuid4().hex[:12]}.wav'
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix('.partial.wav')
                try:
                    infer(row['request'], temporary)
                    audio = wav_info(temporary)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                state['entries'][row['group']] = {**identity, 'signature': signature,
                    'file': path.relative_to(job).as_posix(), 'sha256': file_hash(path), 'audio': audio}
                atomic_json(metadata, state)
            resolved[row['profile']] = str(path.resolve())
            contexts[row['profile']] = signature
        # Keep historical entries/files for recovery, but do not make an unused
        # (possibly corrupt) old reference a prerequisite for the current job.
        active = [row['group'] for row in groups if row['mode'] == 'automatic']
        if metadata.exists() or active:
            state['active_groups'] = active
            atomic_json(metadata, state)
    return effective, resolved, contexts


def active_reference_entries(state):
    if state.get('version') != 1 or not isinstance(state.get('entries'), dict):
        raise ValueError('自動参照メタデータの形式が不正です')
    entries = state['entries']
    # Older version-1 jobs contain only entries; every entry was then active.
    active = state.get('active_groups', list(entries))
    if (not isinstance(active, list) or any(not isinstance(key, str) for key in active)
            or len(set(active)) != len(active) or not set(active) <= set(entries)):
        raise ValueError('使用中の自動参照グループが不正です')
    return {key: entries[key] for key in active}


def verify_references(job):
    from .core import read_json
    job = Path(job)
    path = job / 'references.json'
    if not path.exists():
        return 0
    state = read_json(path)
    entries = active_reference_entries(state)
    for entry in entries.values():
        wav = inside(job, entry['file'])
        if file_hash(wav) != entry['sha256'] or wav_info(wav) != entry['audio']:
            raise ValueError('回収した自動参照WAVの検証に失敗しました')
    return len(entries)


def final_speech_plan(project, voices, contexts, engine):
    from .core import sampling_plan
    plan = sampling_plan(project, voices)
    for row in plan:
        context = contexts.get(row['reference']['profile']) if row['reference'] else None
        if context:
            row['reference']['preparation_sha256'] = context
        row['fingerprint'] = digest({'request': row['fingerprint'], 'engine': engine,
                                     **({'reference_preparation': context} if context else {})})
    return plan
