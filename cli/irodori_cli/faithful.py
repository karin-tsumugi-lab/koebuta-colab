"""Versioned, CPU-only planning for authored scenarios. Never repairs the script."""
from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from pathlib import Path

from .core import ATTRS, MODEL, TTS_MODELS, digest, file_hash, identifier
from .emoji_tags import EMOTIONS, ALL_TAGS, TAG_PATTERN
from .text_conversion import FORMATS, reading

CONTRACT = 'koebuta-faithful-v1'
SETTINGS = {'title', 'reading', 'voiceMode', 'baseCaption', 'seed', 'steps', 'pause',
            'ttsModel', 'acting', 'emotion', 'narratorEmotion', 'textOptions',
            'speakerVoices', 'voices'}
DEFAULTS = dict(title='新しい朗読', reading='shared', voiceMode='design',
                baseCaption='自然で聞き取りやすい日本語の朗読。', seed=314, steps=40,
                pause=.28, ttsModel=MODEL, acting=True, emotion=True, narratorEmotion=True)


class PlanError(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__('\n'.join(f"{d['code']} {d.get('segment_id') or '全体'}"
                                  f"{('#' + str(d['part_index'])) if d.get('part_index') else ''}"
                                  f" / {d['field']}: {d['message']}"
                                  for d in diagnostics if d['level'] == 'error'))


def load_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('重複したJSONキー: ' + key)
            out[key] = value
        return out
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('JSONは2MiB以内にしてください')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('非有限値: ' + v)))


def project_document(raw):
    """Transport adapter; legacy documents keep their original validation path."""
    if isinstance(raw, dict) and 'contract' in raw:
        if raw.get('contract') != CONTRACT or not isinstance(raw.get('scenario'), dict) or not isinstance(raw.get('settings'), dict):
            raise ValueError('未対応または不正な忠実生成の実行契約です')
        return copy.deepcopy(raw)
    from .core import normalize_project
    return normalize_project(raw)


def plan_signature(plan):
    # Host and Colab paths differ. Audio bytes, not their locations, identify voices.
    return digest({'contract': CONTRACT, 'requests': [
        {k: v for k, v in row.items() if k != 'request'} |
        {'request': {k: v for k, v in row['request'].items() if k != 'ref_wav'}}
        for row in plan['requests']], 'execution': plan['execution'],
        'scenario_sha256': plan['scenario_sha256'], 'settings': plan['settings']})


def _safe_boundary(text, offset):
    left, right = text[offset - 1], text[offset]
    if (unicodedata.category(right).startswith('M') or right in ('\ufe0e', '\ufe0f', '\u200d')
            or right == '\u200c' or left == '\u200d' or unicodedata.combining(left) == 9
            or 0x1f3fb <= ord(right) <= 0x1f3ff):
        return False
    if left == '\r' and right == '\n' or 0xe0020 <= ord(right) <= 0xe007f:
        return False
    def hangul(char):
        n = ord(char)
        if 0x1100 <= n <= 0x115f or 0xa960 <= n <= 0xa97c: return 'L'
        if 0x1160 <= n <= 0x11a7 or 0xd7b0 <= n <= 0xd7c6: return 'V'
        if 0x11a8 <= n <= 0x11ff or 0xd7cb <= n <= 0xd7fb: return 'T'
        if 0xac00 <= n <= 0xd7a3: return 'LV' if (n - 0xac00) % 28 == 0 else 'LVT'
        return ''
    a, b = hangul(left), hangul(right)
    if (a == 'L' and b in ('L', 'V', 'LV', 'LVT') or
            a in ('LV', 'V') and b in ('V', 'T') or a in ('LVT', 'T') and b == 'T'):
        return False
    if 0x1f1e6 <= ord(left) <= 0x1f1ff and 0x1f1e6 <= ord(right) <= 0x1f1ff:
        run = 0
        for char in reversed(text[:offset]):
            if not 0x1f1e6 <= ord(char) <= 0x1f1ff:
                break
            run += 1
        if run % 2:
            return False
    return not any(match.start() < offset < match.end() for match in TAG_PATTERN.finditer(text))


def build_plan(scenario, settings, *, base='.', voices=None, selected=None, ruby_deferred=False):
    from .ruby_bridge import check_notes
    diagnostics = []

    def add(level, code, field, message, sid=None, part=None):
        item = dict(level=level, code=code, segment_id=sid, field=field, message=str(message))
        if part is not None:
            item['part_index'] = part
        diagnostics.append(item)

    def error(field, message, sid=None, code='E_STRUCTURE'):
        add('error', code, field, message, sid)

    def stop():
        if any(d['level'] == 'error' for d in diagnostics):
            raise PlanError(diagnostics)

    def valid_id(value, label, sid=None):
        try:
            identifier(value, label, 40 if label == 'voice profile' else 64)
            return True
        except ValueError as exc:
            error(label, exc, sid)
            return False

    if not isinstance(settings, dict):
        error('settings', '生成設定はオブジェクトが必要です', code='E_SETTINGS')
        stop()
    for key in settings.keys() - SETTINGS:
        error(key, '未対応の生成設定です', code='E_SETTINGS')
    cfg = {**DEFAULTS, **settings}
    for key in ('acting', 'emotion', 'narratorEmotion'):
        if type(cfg[key]) is not bool:
            error(key, '真偽値が必要です', code='E_SETTINGS')
    for key, allowed in [('reading', ('shared', 'cast')), ('voiceMode', ('design', 'clone')), ('ttsModel', TTS_MODELS)]:
        if cfg[key] not in allowed:
            error(key, '対応する値を指定してください', code='E_SETTINGS')
    if type(cfg['seed']) is not int or not 0 <= cfg['seed'] <= 2147483647:
        error('seed', '0〜2147483647の整数が必要です', code='E_SETTINGS')
    if type(cfg['steps']) is not int or cfg['steps'] not in (20, 40, 60):
        error('steps', '20 / 40 / 60を指定してください', code='E_SETTINGS')
    if type(cfg['pause']) not in (int, float) or not math.isfinite(cfg['pause']) or not 0 <= cfg['pause'] <= 10:
        error('pause', '0〜10の有限な秒数が必要です', code='E_SETTINGS')
    for key in ('title', 'baseCaption'):
        if not isinstance(cfg[key], str):
            error(key, '文字列が必要です', code='E_SETTINGS')
    options = cfg.get('textOptions', {})
    if not isinstance(options, dict):
        error('textOptions', 'オブジェクトが必要です', code='E_SETTINGS')
        options = {}
    for key in options.keys() - {'format', 'blankMode', 'blankPauseMs', 'symbolSeparators', 'readingMode'}:
        error('textOptions.' + key, '未対応の指定です', code='E_SETTINGS')
    if options.get('format', 'none') not in FORMATS:
        error('textOptions.format', '未対応のルビ形式です', code='E_SETTINGS')
    for key, default in [('blankMode', 'off'), ('symbolSeparators', False), ('readingMode', 'off')]:
        if type(options.get(key, default)) is not type(default) or options.get(key, default) != default:
            error('textOptions.' + key, '自動処理は廃止しました。明示的な区切り・間・tts_textを指定してください', code='E_SETTINGS')
    if 'blankPauseMs' in options and (type(options['blankPauseMs']) is not int or not 0 <= options['blankPauseMs'] <= 10000):
        error('textOptions.blankPauseMs', '0〜10000の整数が必要です', code='E_SETTINGS')
    elif 'blankPauseMs' in options:
        add('warning', 'W_LAYOUT_IGNORED', 'textOptions.blankPauseMs', '自動空行休止には使用しません')
    assignments, declared = cfg.get('speakerVoices', {}), cfg.get('voices', {})
    if not isinstance(assignments, dict) or not isinstance(declared, dict):
        error('voices', '声の割り当てはオブジェクトが必要です', code='E_SETTINGS')
        stop()
    if assignments and cfg['reading'] != 'cast':
        error('speakerVoices', '人物別の割り当てにはreading=castが必要です', code='E_SETTINGS')
    for profile, path in declared.items():
        valid_id(profile, 'voice profile')
        if not isinstance(path, str) or not path.strip():
            error('voices.' + profile, '空でないパスが必要です', code='E_REFERENCE')
    if not isinstance(scenario, dict) or type(scenario.get('schema_version')) is not int or scenario.get('schema_version') != 1:
        error('schema_version', '交換形式v1のオブジェクトが必要です')
        stop()
    speakers, segments = scenario.get('speakers'), scenario.get('segments')
    if not isinstance(speakers, dict) or not speakers:
        error('speakers', '空でない話者一覧が必要です')
        stop()
    for sid, speaker in speakers.items():
        valid_id(sid, 'speaker_id', sid)
        if not isinstance(speaker, dict):
            error('speaker', 'オブジェクトが必要です', sid)
            continue
        if not isinstance(speaker.get('name'), str) or not speaker['name'].strip():
            error('name', '空でない話者名が必要です', sid)
        if speaker.get('kind') not in ('narrator', 'character'):
            error('kind', 'narrator / characterが必要です', sid)
        for key in ('bio', 'voice_caption', 'acting_description'):
            if key in speaker and not isinstance(speaker[key], str):
                error(key, '文字列が必要です', sid)
        for key, allowed in ATTRS.items():
            if key in speaker and speaker[key] not in allowed:
                error(key, '不正な話者属性です', sid)
    for sid, profile in assignments.items():
        if sid not in speakers:
            error('speakerVoices', '未登録の話者です', sid, 'E_REFERENCE')
        valid_id(profile, 'voice profile', sid)
    if not isinstance(segments, list) or not segments:
        error('segments', '空でない配列が必要です')
        stop()
    seen, speech, units = set(), [], []
    for row in segments:
        if not isinstance(row, dict):
            error('segment', 'オブジェクトが必要です')
            continue
        sid = row.get('id')
        try:
            check_notes(row)
        except ValueError as exc:
            error('notes', str(exc), sid)
        valid_id(sid, 'segment.id')
        if isinstance(sid, str):
            if sid in seen:
                error('id', '発話IDが重複しています', sid)
            seen.add(sid)
        typ = row.get('segment_type', 'speech')
        if typ not in ('speech', 'separator'):
            error('segment_type', '未知の項目種別です', sid)
        if not isinstance(row.get('emotion'), str) or row['emotion'] not in EMOTIONS:
            error('emotion', '必須の感情IDが欠落または不正です', sid)
        if 'pause_after_ms' in row and (type(row['pause_after_ms']) is not int or not 0 <= row['pause_after_ms'] <= 10000):
            error('pause_after_ms', '0〜10000の整数が必要です', sid)
        if 'blank_lines_after' in row:
            val = row['blank_lines_after']
            if type(val) is not int or val < 0:
                error('blank_lines_after', '0以上の整数が必要です', sid)
            elif val:
                add('warning', 'W_LAYOUT_IGNORED', 'blank_lines_after', '空行数から休止を推定しません', sid)
        if typ == 'separator':
            if 'speaker_id' in row and (not isinstance(row['speaker_id'], str) or row['speaker_id'] not in speakers):
                error('speaker_id', '未登録の話者です', sid, 'E_REFERENCE')
            if 'text' in row and not isinstance(row['text'], str):
                error('text', '区切りの本文は文字列です', sid)
            if 'koebuta_tts_parts' in row:
                error('koebuta_tts_parts', '区切りには指定できません', sid, 'E_PARTS')
            continue
        if typ != 'speech':
            continue
        if not isinstance(row.get('speaker_id'), str) or row['speaker_id'] not in speakers:
            error('speaker_id', '未登録の話者です', sid, 'E_REFERENCE')
        if not isinstance(row.get('text'), str) or not row['text'].strip():
            error('text', '空でない本文が必要です', sid)
            continue
        if 'acting_description' in row and not isinstance(row['acting_description'], str):
            error('acting_description', '文字列が必要です', sid)
        fmt = row.get('text_format', options.get('format', 'none'))
        if fmt not in FORMATS:
            error('text_format', '未対応のルビ形式です', sid)
            continue
        spoken = row.get('tts_text')
        if spoken is not None and not isinstance(spoken, str):
            error('tts_text', '文字列が必要です', sid)
            continue
        if isinstance(spoken, str) and not spoken.strip():
            add('warning', 'W_READING_IGNORED', 'tts_text', '空の読み上げ文は未指定として扱います', sid)
        if not spoken or not spoken.strip():
            spoken, issues = reading(row['text'], fmt)
            for issue in issues:
                error('text', issue, sid)
        parts = row.get('koebuta_tts_parts')
        if 'koebuta_tts_parts' in row:
            if (not isinstance(parts, list) or len(parts) < 2
                    or any(not isinstance(p, str) or not p.strip() for p in parts)
                    or not isinstance(row.get('tts_text'), str) or not row['tts_text'].strip()
                    or ''.join(parts) != row['tts_text']):
                error('koebuta_tts_parts', '2個以上の非空文字列と、連結値に完全一致するtts_textが必要です', sid, 'E_PARTS')
                continue
            offset = 0
            for part in parts[:-1]:
                offset += len(part)
                if not _safe_boundary(spoken, offset):
                    error('koebuta_tts_parts', '結合文字・絵文字タグの途中で分割されています', sid, 'E_PARTS')
        else:
            parts = [spoken]
        speech.append(row)
        for index, part in enumerate(parts, 1):
            units.append(dict(id=sid if len(parts) == 1 else f'{sid}#{index}',
                              segment_id=sid, part_index=index, part_count=len(parts),
                              spoken=part, row=row))
    if not speech:
        error('segments', '読み上げる発話がありません')
    source = scenario.get('source')
    if 'source' in scenario and not isinstance(source, str):
        error('source', '元原稿は文字列が必要です')
    elif source is None:
        add('info', 'I_SOURCE_UNCHECKED', 'source', '元原稿がないため原文照合は未実施です')
    else:
        cursor = 0
        for row in segments:
            body = row.get('text') if isinstance(row, dict) else None
            if isinstance(body, str) and body:
                found = source.find(body, cursor)
                if found < 0:
                    add('warning', 'W_SOURCE_MISMATCH', 'source', '順序付き部分照合の不一致。許可済み改変か本文差分かを確認してください', row.get('id'))
                    break
                cursor = found + len(body)
    stop()
    # Resolve one gap per authored boundary. Never infer gaps from text or layout.
    gap_after, leading, pending = {}, 0, []
    previous = None

    def boundary(left, separators, edge=False):
        values = [r['pause_after_ms'] for r in separators if 'pause_after_ms' in r]
        if left is not None and 'pause_after_ms' in left:
            value = left['pause_after_ms']
        elif values:
            value = max(values)
        else:
            value = 0 if edge else round(cfg['pause'] * 1000)
        competing = values + ([left['pause_after_ms']] if left is not None and 'pause_after_ms' in left else [])
        if any(v != value for v in competing):
            add('warning', 'W_PAUSE_CONFLICT', 'pause_after_ms', f'境界には{value}msを適用します（合算なし）', left['id'] if left else None)
        return value

    for row in segments:
        if row.get('segment_type', 'speech') == 'separator':
            pending.append(row)
        else:
            if previous is None:
                leading = boundary(None, pending, True)
            else:
                gap_after[previous['id']] = boundary(previous, pending)
            previous, pending = row, []
    gap_after[previous['id']] = boundary(previous, pending, True)
    chosen = None
    if selected is not None:
        chosen = set()
        if not isinstance(selected, str) or not selected:
            error('ids', '空の対象指定です', code='E_SELECTION')
        else:
            for selector in selected.split(','):
                matches = [u['id'] for u in units if u['segment_id'] == selector or u['id'] == selector]
                if not matches:
                    error('ids', f'存在しない発話・片、または区切りIDです: {selector}', code='E_SELECTION')
                chosen.update(matches)
    stop()
    selected_units = [u for u in units if chosen is None or u['id'] in chosen]
    used_voices, requests = {}, []
    overrides = voices or {}
    for unit in selected_units:
        row, sid = unit['row'], unit['segment_id']
        person = speakers[row['speaker_id']]
        profile = 'voice_a' if cfg['reading'] == 'shared' else assignments.get(row['speaker_id'], 'voice_a')
        clone = cfg['voiceMode'] == 'clone' if cfg['reading'] == 'shared' or profile == 'voice_a' else profile != 'design'
        reference = None
        if clone:
            value = overrides.get(profile, declared.get(profile))
            try:
                if not value:
                    raise ValueError('参照音声が未指定です')
                path = Path(value).expanduser()
                path = path if path.is_absolute() else Path(base) / path
                path = path.resolve(strict=True)
                if not path.is_file():
                    raise ValueError('参照音声はファイルが必要です')
                reference = dict(profile=profile, sha256=file_hash(path))
                used_voices[profile] = str(path)
            except (ValueError, OSError) as exc:
                error('voices.' + profile, exc, sid, 'E_REFERENCE')
                continue
        caption = cfg['baseCaption'] if cfg['reading'] == 'shared' or clone else person.get('voice_caption', '')
        if not clone and not caption.strip():
            error('voice_caption', 'VoiceDesignの声質説明が空です', sid)
        acting = [person.get('acting_description', ''), row.get('acting_description', '')]
        if cfg['acting']:
            caption = '\n'.join(p for p in [caption.rstrip(), *(p.strip() for p in acting)] if p)
        elif any(acting):
            add('warning', 'W_DIRECTIVE_DISABLED', 'acting', '演技説明の反映は無効です', sid, unit['part_index'])
        apply_emotion = cfg['emotion'] and (cfg['narratorEmotion'] or person['kind'] != 'narrator')
        if not apply_emotion and row['emotion'] != 'neutral':
            add('warning', 'W_DIRECTIVE_DISABLED', 'emotion', '感情タグの反映は無効です', sid, unit['part_index'])
        spoken_text = unit['spoken']
        if ruby_deferred and '《' in spoken_text:
            from .ruby_core import parse_aozora_ruby
            spoken_text = parse_aozora_ruby(spoken_text, strict=False, allow_ascii_bar=True).plain_text
        spoken_count = len(''.join(c for c in TAG_PATTERN.sub('', spoken_text) if not c.isspace()))
        if spoken_count < 20 or spoken_count > 80:
            severity = '強い警告' if spoken_count < 10 else ('短文警告' if spoken_count < 15 else '推奨範囲外の通知')
            add('warning' if spoken_count < 15 else 'info', 'W_LENGTH', 'tts_text',
                f'{severity}: {spoken_count}文字（20〜80は推奨範囲）。自動分割・結合はしません', sid, unit['part_index'])
        request = dict(text=(EMOTIONS[row['emotion']] if apply_emotion else '') + unit['spoken'],
                       caption=caption or None, no_ref=not clone, seed=cfg['seed'], num_steps=cfg['steps'])
        if clone:
            request.update(ref_wav=used_voices[profile], max_ref_seconds=30)
        identity = {k: v for k, v in request.items() if k != 'ref_wav'}
        requests.append(dict(id=unit['id'], unit_id=unit['id'], segment_id=sid,
                             part_index=unit['part_index'], part_count=unit['part_count'],
                             role=row['speaker_id'], request=request, reference=reference,
                             fingerprint=digest(dict(contract=CONTRACT, request=identity, reference=reference,
                                 segment_id=sid, parts=row.get('koebuta_tts_parts'))),
                             pause_after_ms=gap_after[sid] if unit['part_index'] == unit['part_count'] else 0))
    stop()
    complete_parents = [r['id'] for r in speech if all(u['id'] in {q['id'] for q in requests}
                          for u in units if u['segment_id'] == r['id'])]
    execution = dict(contract=CONTRACT, scope='full' if selected is None else 'selection',
                     selection=selected, total_unit_count=len(units), selected_unit_count=len(requests),
                     selected_unit_ids=[r['id'] for r in requests], complete_segment_ids=complete_parents,
                     leading_pause_ms=leading if selected_units[0]['id'] == units[0]['id'] else 0,
                     trailing_pause_ms=gap_after[speech[-1]['id']] if selected_units[-1]['id'] == units[-1]['id'] else 0)
    return dict(contract=CONTRACT, requests=requests, execution=execution, diagnostics=diagnostics,
                scenario_sha256=digest(scenario),
                settings={k: cfg[k] for k in DEFAULTS}, voices=used_voices)
