"""Compile source-owned annotations to existing project JSON, splitting last.

Imported/manual projects without a trusted map retain the legacy split guard.
This module never reconstructs an arbitrary manual reading from text similarity.
"""
import copy
import re
import unicodedata

from .core import EMOTIONS, normalize_project
from .source_document import validate_document
from .text_conversion import options, separator
from .text_map import TextMap, mapped_boundary, validate_map


def apply_readings(unit, annotations):
    """Apply validated, non-overlapping source-local annotations to a fresh map."""
    validate_map(unit['text'], unit['baseline_tts'], unit['source_to_baseline'])
    result = TextMap(unit['text'])
    result.pieces = [{k: copy.deepcopy(p[k]) for k in ('source_span', 'rendered', 'operation')}
                     for p in unit['source_to_baseline']]
    edits = []; used = set()
    for annotation in annotations:
        if set(annotation) != {'id', 'source_span', 'surface', 'value', 'operation'}:
            raise ValueError('読み注釈の項目が不正です')
        if not isinstance(annotation['id'], str) or annotation['id'] in used:
            raise ValueError('読み注釈のIDが重複しています')
        used.add(annotation['id'])
        span = annotation['source_span']
        if (not isinstance(span, list) or len(span) != 2
                or any(type(v) is not int for v in span)):
            raise ValueError('読み注釈の位置が不正です')
        a, b = span
        if (not 0 <= a < b <= len(unit['text']) or annotation['surface'] != unit['text'][a:b]
                or not isinstance(annotation['value'], str) or not annotation['value']
                or len(annotation['value']) > 80 or annotation['operation'] not in ('ai_reading', 'normalize')):
            raise ValueError('読み注釈と原文が一致しません')
        if any(a < p['source_span'][1] and p['source_span'][0] < b
               and p['operation'] != 'copy' for p in unit['source_to_baseline']):
            raise ValueError('明示ルビ・注記の変換範囲へ読み注釈を付けられません')
        x, y = (mapped_boundary(unit['source_to_baseline'], v) for v in (a, b))
        if x is None or y is None or any(a < end and start < b for start, end, *_ in edits):
            raise ValueError('読み注釈が重複または保護範囲内です')
        edits.append((a, b, x, y, annotation['value'], annotation['operation']))
    for _, _, x, y, value, operation in sorted(edits, reverse=True):
        result.replace(x, y, value, operation)
    return result.rendered, result.export()


def split_mapped(body, spoken, mapping, limit=80):
    """Choose shared source/reading cuts. Preserve every character in both."""
    if type(limit) is not int or limit < 8:
        raise ValueError('分割目安は8文字以上です')
    validate_map(body, spoken, mapping)
    safe = []
    for i in range(1, len(body) + 1):
        if i < len(body) and (unicodedata.combining(body[i]) or body[i] in ('\ufe0f', '\u200d')
                              or body[i - 1] == '\u200d'):
            continue
        target = mapped_boundary(mapping, i)
        if target is not None:
            safe.append((i, target))
    result = []; a = x = 0
    while a < len(body):
        candidates = [(b, y) for b, y in safe if a < b <= a + 5000
                      and 0 < y - x <= limit and spoken[x:y].strip()]
        if not candidates:
            raise ValueError('安全な位置で本文と読みを分割できません。長い語・ルビを確認してください')
        final = next(((b, y) for b, y in candidates if b == len(body)), None)
        if final:
            b, y = final
        else:
            # Prefer a sentence boundary, then phrase, then a safe copy boundary.
            sentences = [(b, y) for b, y in candidates if re.search(r'[。！？!?][」』”]*$', body[a:b])]
            phrases = [(b, y) for b, y in candidates if body[b - 1] in '、，,；;：: \t\n']
            b, y = (sentences or phrases or candidates)[-1]
        result.append({'text': body[a:b], 'tts_text': spoken[x:y],
                       'text_span': [a, b], 'tts_span': [x, y]})
        a, x = b, y
    if ''.join(p['text'] for p in result) != body or ''.join(p['tts_text'] for p in result) != spoken:
        raise ValueError('分割前後の本文・読みが一致しません')
    return result


def compile_document(document, project, roles, assignments, *, readings=None,
                     emotions=None, reading_notes=None, limit=80):
    """New manuscript path only. Return a candidate; do not write a project."""
    validate_document(document)
    original = normalize_project(project)
    if original['analyzed']:
        raise ValueError('既存シナリオは互換経路で扱います。新規原稿のコンパイルでは上書きしません')
    protected = ('tts_text', 'pause_after_ms', 'emotion_locked', 'reading_correction')
    if any(any(k in s for k in protected) or s['reviewed'] or s['acting']
           or s['emotion'] != 'neutral' for s in original['segments']):
        raise ValueError('個別に編集された設定があります。新規原稿の結果を自動で適用できません')
    if document['source'] != original['source']:
        raise ValueError('原稿が解析開始時と変わっています')
    if any(i['severity'] == 'blocking' for i in document['issues']):
        raise ValueError('ルビ・注記の確認が必要です。原文は保持しています')
    cfg = options(original.get('textOptions', {}))
    if cfg['format'] != document['parse_policy']['format']:
        raise ValueError('ルビ形式が解析開始時と変わっています')
    readings = readings or {}; emotions = emotions or {};reading_notes=reading_notes or {}
    units = {u['id'] for u in document['units']}
    role_ids = {r['id'] for r in roles}
    if set(assignments) != units or not set(readings) <= units or not set(emotions) <= units:
        raise ValueError('原稿と注釈の対象IDが一致しません')
    result = copy.deepcopy(original); segments = []; segment_map = []
    for u in document['units']:
        key = u['id']; role = assignments[key]
        if role not in role_ids or emotions.get(key, 'neutral') not in EMOTIONS:
            raise ValueError('配役または感情が不正です')
        spoken, mapping = apply_readings(u, readings.get(key, []))
        layout_only = not spoken.strip()
        is_separator = layout_only or cfg['symbolSeparators'] and separator(u['text'])
        if is_separator:
            parts = [{'text': u['text'], 'tts_text': '', 'text_span': [0, len(u['text'])],
                      'tts_span': [0, len(spoken)]}]
        else:
            parts = split_mapped(u['text'], spoken, mapping, limit)
        gap = re.match(r'[ \t\u3000]*(?:\r?\n[ \t\u3000]*)+', document['source'][u['source_span'][1]:])
        blank_count = max(0, gap[0].count('\n') - 1) if gap else 0
        for index, part in enumerate(parts):
            segment_id = f'{key}_{index + 1:03d}'
            row = {'id': segment_id, 'role': role, 'text': part['text'],
                   'emotion': emotions.get(key, 'neutral'), 'acting': '', 'reviewed': False}
            if is_separator:
                row['segment_type'] = 'separator'
            else:
                a, b = part['text_span']
                x, y = (mapped_boundary(u['source_to_baseline'], v) for v in (a, b))
                if x is None or y is None:raise ValueError('補正前の読みの分割位置が一致しません')
                baseline = u['baseline_tts'][x:y]
                # Keep the complete generated reading for safe downstream TTS
                # admission, plus reversible per-child correction history.
                row['tts_text'] = part['tts_text']
                row['tts_text_origin'] = 'analysis'
                if baseline != part['tts_text'] or reading_notes.get(key):
                    row['reading_correction'] = {'before': baseline, 'after': part['tts_text'],
                        'mode': cfg.get('readingMode', 'selective') if cfg.get('readingMode', 'off') != 'off' else 'selective',
                        'note': reading_notes.get(key,'')[:1000]}
            if index == len(parts) - 1 and blank_count:
                row['blank_lines_after'] = blank_count
            segments.append(row)
            start = u['source_span'][0]
            segment_map.append({'segment_id': segment_id, 'unit_id': key,
                                'source_span': [start + v for v in part['text_span']],
                                'unit_text_span': part['text_span'], 'tts_span': part['tts_span'],
                                'mapping': mapping,
                                'annotation_ids': [a['id'] for a in readings.get(key, [])]})
    result.update(roles=roles, segments=segments, analyzed=True, stage=1)
    return normalize_project(result), segment_map
