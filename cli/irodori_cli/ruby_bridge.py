"""Self-contained Koebuta v3 ruby bridge (host validation & remote/local selection)."""
from __future__ import annotations

import copy
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Any

from .text_conversion import strip_aozora_layout

from .ruby_core import (
    RubySyntaxError,
    RubyParseResult,
    RubySpan,
    StandaloneSpanScorer,
    apply_ruby_selections,
    convert_ruby_text,
    normalize_safe_ruby_formats,
    parse_aozora_ruby,
)


def create_local_irodori_scorer():
    """Instantiate the self-contained local scorer."""
    return StandaloneSpanScorer()


def _validate_and_parse_parts(
    normalized_source: str,
    raw_parts: Any,
    *,
    strict: bool = True,
):
    """Validate ruby inside `koebuta_tts_parts` and ensure part boundaries do not split kanji bases."""
    if not isinstance(raw_parts, list) or len(raw_parts) < 2 or any(
        not isinstance(p, str) or not p.strip() for p in raw_parts
    ):
        return None, None
    norm_parts = [normalize_safe_ruby_formats(p) for p in raw_parts]
    if ''.join(norm_parts) != normalized_source:
        raise RubySyntaxError('E_PARTS_MISMATCH: koebuta_tts_parts の連結値がルビ変換前の tts_text と一致しません')
    full_parsed = parse_aozora_ruby(normalized_source, strict=strict, allow_ascii_bar=True)
    part_parses = [parse_aozora_ruby(p, strict=strict, allow_ascii_bar=True) for p in norm_parts]
    flat_spans = [(s.surface, s.reading, s.explicit_bar) for pp in part_parses for s in pp.spans]
    full_spans = [(s.surface, s.reading, s.explicit_bar) for s in full_parsed.spans]
    if flat_spans != full_spans:
        raise RubySyntaxError('E_PARTS_RUBY_BOUNDARY: koebuta_tts_parts の分割境界がルビ親文字の途中を切断しています')
    return norm_parts, part_parses


def _speech_rows(scenario):
    rows = scenario.get('segments') if isinstance(scenario, dict) else None
    if isinstance(rows, list):
        yield from (row for row in rows if isinstance(row, dict)
                    and row.get('segment_type') != 'separator')


def _requires_ruby_resolution(row):
    if 'koebuta_added_ruby' in row:
        return True
    original = row.get('text')
    working = row.get('tts_text')
    if not isinstance(original, str) or 'koebuta_tts_parts' in row:
        return False
    if isinstance(working, str) and '｜' in working and '《' in working:
        return True
    fmt = row.get('text_format', 'aozora')
    if fmt in ('pixiv', 'narou', 'kakuyomu'):
        if not isinstance(working, str) or not working.strip():
            return False  # build_plan reads the original in its declared format.
        from .text_conversion import convert_with_map
        _, _, pieces = convert_with_map(original, fmt)
        return any(piece['operation'] == 'ruby' for piece in pieces)
    return '《' in original and bool(parse_aozora_ruby(original, strict=False).spans)


def requires_ruby_resolution(scenario):
    return any(_requires_ruby_resolution(row) for row in _speech_rows(scenario))


def has_automatic_ruby(scenario):
    for row in _speech_rows(scenario):
        entries = row.get('koebuta_added_ruby')
        if isinstance(entries, list) and any(isinstance(e, dict) and e.get('selection') == 'auto'
                                             for e in entries):
            return True
    return False


def check_notes(row):
    if 'notes' in row and (not isinstance(row['notes'], list)
                           or any(not isinstance(note, str) for note in row['notes'])):
        raise ValueError('notes は文字列の配列で指定してください')


def _project_source_ruby(original, source_format):
    """Keep original bases, readings and offsets from the existing format parser."""
    from .text_conversion import convert_with_map

    _, issues, source_map = convert_with_map(original, source_format)
    if issues:
        raise RubySyntaxError('原文のルビを特定できません: ' + ' / '.join(issues))
    parts, spans, cursor = [], [], 0
    for piece in source_map:
        value = piece['rendered']
        if piece['operation'] == 'ruby':
            start, end = piece['source_span']
            markup = original[start:end]
            if source_format == 'pixiv':
                surface = markup[5:-2].split('>', 1)[0].strip()
            elif '《' in markup:
                surface = markup.split('《', 1)[0].lstrip('｜|')
            else:
                surface = markup.replace('（', '(', 1).split('(', 1)[0]
            if not surface:
                raise RubySyntaxError(f'原文のルビの親文字を特定できません: {markup}')
            spans.append(RubySpan(surface, value, cursor, cursor + len(surface), True))
            value = surface
        parts.append(value)
        piece['tts_span'] = [cursor, cursor + len(value)]
        cursor += len(value)
    return RubyParseResult(original, ''.join(parts), tuple(spans)), source_map


def _managed_ruby(row, mode, threshold, single_threshold, scorer):
    """Resolve authored readings, retaining unrelated edits and TTS boundaries."""
    def parse(text):
        if normalize_safe_ruby_formats(text) != text or '《《' in text:
            raise RubySyntaxError('読み上げ文のルビは青空文庫形式（｜親文字《読み》）に変換してください')
        return parse_aozora_ruby(strip_aozora_layout(text), strict=True)

    original = row['text']
    source_format = row.get('text_format', 'aozora')
    source_map = None
    raw_tts = row.get('tts_text')
    if source_format in ('narou', 'kakuyomu', 'pixiv'):
        from .text_conversion import convert_with_map
        from .text_map import mapped_boundary

        if not raw_tts or not raw_tts.strip():
            raise RubySyntaxError('原文を保持し、青空文庫形式に変換した読み上げ文を tts_text に指定してください')
        if source_format == 'narou':
            _, _, tts_map = convert_with_map(raw_tts, source_format)
            if any(piece['operation'] == 'ruby' and '《' not in raw_tts[slice(*piece['source_span'])]
                   for piece in tts_map):
                raise RubySyntaxError('なろう形式のルビを青空文庫形式へ変換してください')
        authored, source_map = _project_source_ruby(original, source_format)
    else:
        authored = parse(original)
    raw_tts = raw_tts or original
    if not raw_tts.strip():
        raw_tts = original
    resolved = parse(raw_tts)
    plain = resolved.plain_text
    mandatory = {(s.plain_start, s.plain_end): s for s in resolved.spans}
    edits = (SequenceMatcher(None, authored.plain_text, plain, autojunk=False).get_opcodes()
             if authored.plain_text != plain else ())

    def locate(start, end, surface, reading=None):
        if authored.plain_text == plain:
            return start, end
        mapped = []
        for pos in (start, end):
            candidates = {c + pos - a for tag, a, b, c, d in edits if tag == 'equal' and a <= pos <= b}
            candidates.update(c for tag, a, b, c, d in edits if tag == 'replace' and pos == a)
            candidates.update(d for tag, a, b, c, d in edits if tag == 'replace' and pos == b)
            mapped.append(candidates)
        if reading is not None and all(len(m) == 1 for m in mapped):
            left, right = (next(iter(m)) for m in mapped)
            if plain[left:right] == reading:
                return left, right
        for tag, a, b, c, d in edits:
            if (tag == 'equal' and a <= start < end <= b
                    and authored.plain_text.count(surface) == plain.count(surface) == 1):
                return c + start - a, c + end - a
            if tag == 'replace' and (a, b) == (start, end) and plain[c:d] == reading:
                return c, d
        raise RubySyntaxError(f'読み上げ文で対象「{surface}」を特定できません。要確認')

    for span in authored.spans:
        loc = locate(span.plain_start, span.plain_end, span.surface, span.reading)
        existing = mandatory.get(loc)
        if existing is not None and existing.reading != span.reading:
            raise RubySyntaxError(
                f'原文ルビ「{span.surface}《{span.reading}》」と'
                f'読み上げ文のルビ「{existing.reading}」が一致しません。要確認')
        mandatory[loc] = replace(span, plain_start=loc[0], plain_end=loc[1])
    replacements = [(a, b, span.reading) for (a, b), span in mandatory.items()]
    entries = row.get('koebuta_added_ruby', [])
    if not isinstance(entries, list):
        raise RubySyntaxError('koebuta_added_ruby は配列で指定してください')
    occupied = []
    decisions = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RubySyntaxError('追加ルビはオブジェクトで指定してください')
        a, b, surface, reading, selection = (
            entry.get(key) for key in ('start', 'end', 'surface', 'reading', 'selection'))
        if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(original)
                or original[a:b] != surface or not isinstance(reading, str) or not reading.strip()
                or selection not in ('auto', 'kana', 'surface')):
            raise RubySyntaxError(f'追加ルビの対象範囲・表記・読み・採用状態を確認してください: {surface}')
        if any(a < end and start < b for start, end in occupied):
            raise RubySyntaxError(f'追加ルビが重複しています: {surface}')
        occupied.append((a, b))
        if source_map is not None:
            if any(piece['operation'] == 'ruby' and a < piece['source_span'][1]
                   and piece['source_span'][0] < b for piece in source_map):
                continue
            def source_boundary(pos):
                boundary = mapped_boundary(source_map, pos)
                if boundary is not None:
                    return boundary
                for piece in source_map:
                    left, right = piece['source_span']
                    if piece['operation'] == 'emphasis' and left + 2 <= pos <= right - 2:
                        return piece['tts_span'][0] + pos - left - 2
                return None

            start, end = source_boundary(a), source_boundary(b)
            if start is None or end is None:
                raise RubySyntaxError(f'追加ルビの対象位置を確認してください: {surface}')
        else:
            prefix = strip_aozora_layout(original[:a])
            start = len(parse_aozora_ruby(prefix, strict=False).plain_text)
            end = start + len(surface)
        if authored.plain_text[start:end] != surface:
            raise RubySyntaxError(f'追加ルビの対象位置を確認してください: {surface}')
        if any(start < span.plain_end and span.plain_start < end for span in authored.spans):
            continue
        loc = locate(start, end, surface, reading if selection == 'kana' else None)
        start, end = loc
        if plain[start:end] != surface:  # A confirmed addition was already expanded.
            continue
        if any(start < right and left < end for left, right in mandatory):
            continue
        use_kana = selection == 'kana'
        score = None
        if selection == 'auto' and mode == 'auto_select':
            encoded = f'{plain[:start]}｜{surface}《{reading}》{plain[end:]}'
            result = convert_ruby_text(encoded, mode='auto_select', threshold=threshold,
                                       single_token_threshold=single_threshold, scorer=scorer, strict=True)
            decision, = result.decisions
            score, use_kana = decision.score, decision.selected == 'kana'
        if use_kana:
            replacements.append((start, end, reading))
        decisions.append(dict(surface=surface, reading=reading, plain_start=start,
                              plain_end=end, score=score, selection=selection,
                              selected='kana' if use_kana else 'kanji'))
    replacements.sort()
    if any(left[1] > right[0] for left, right in zip(replacements, replacements[1:])):
        raise RubySyntaxError('必須ルビの範囲が重なっています。要確認')

    def render(start, end):
        result = plain[start:end]
        for a, b, value in reversed(replacements):
            if start <= a < b <= end:
                result = result[:a-start] + value + result[b-start:]
            elif a < end and start < b:
                raise RubySyntaxError('ルビの途中にTTS片の境界があります。要確認')
        return result

    if 'koebuta_tts_parts' in row:
        raise RubySyntaxError('v3ではTTS片を作成できません。発話IDを分けたシナリオを使用してください')
    row['tts_text'] = render(0, len(plain))
    return dict(segment_id=row.get('id'), plain_text=plain,
                tts_text=row['tts_text'], decisions=decisions)


def prepare_remote_ruby_scenario(
    scenario: dict[str, Any],
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Validate ruby syntax and normalize safe formats on host before sending to Colab GPU.

    Preserves `text` and `source` untouched; stores normalized ruby text into `tts_text`
    (and `koebuta_tts_parts` when present) without stripping ruby tags.
    """
    updated = copy.deepcopy(scenario)
    if requires_ruby_resolution(scenario):
        apply_ruby_to_scenario(scenario)  # Validate attachments before starting a runtime.
        return updated
    segments = updated.get('segments')
    if not isinstance(segments, list):
        return updated

    for row in segments:
        if not isinstance(row, dict) or row.get('segment_type') == 'separator':
            continue
        raw_tts = row.get('tts_text')
        source_field = raw_tts if isinstance(raw_tts, str) and raw_tts.strip() else row.get('text')
        if not isinstance(source_field, str) or not source_field.strip():
            continue
        normalized = normalize_safe_ruby_formats(source_field)
        parse_aozora_ruby(normalized, strict=strict, allow_ascii_bar=True)
        if 'koebuta_tts_parts' in row:
            norm_parts, _ = _validate_and_parse_parts(normalized, row.get('koebuta_tts_parts'), strict=strict)
            if norm_parts is not None:
                row['koebuta_tts_parts'] = norm_parts
        row['tts_text'] = normalized
    return updated


def apply_ruby_to_scenario(
    scenario: dict[str, Any],
    *,
    mode: str = 'none',
    threshold: float = 0.8327,
    single_token_threshold: float | None = 0.65,
    strict: bool = True,
    scorer: Any = None,
    selected_segment_ids: set[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply ruby conversion to scenario `tts_text` (and `koebuta_tts_parts` when present)."""
    managed = requires_ruby_resolution(scenario)
    if managed:
        updated = copy.deepcopy(scenario)
        reports = []
        for row in updated['segments']:
            if (not isinstance(row, dict) or row.get('segment_type') == 'separator'
                    or not _requires_ruby_resolution(row) or not isinstance(row.get('text'), str)
                    or (row.get('tts_text') is not None and not isinstance(row['tts_text'], str))):
                continue
            if selected_segment_ids is not None and row.get('id') not in selected_segment_ids:
                continue
            try:
                if mode == 'auto_select' and scorer is None and has_automatic_ruby({'segments': [row]}):
                    scorer = create_local_irodori_scorer()
                reports.append(_managed_ruby(row, mode, threshold, single_token_threshold, scorer))
            except RubySyntaxError as exc:
                raise RubySyntaxError(f"{row.get('id', '?')}: {exc}") from exc
        return updated, reports
    if mode == 'none':
        return scenario, []

    if mode == 'auto_select' and scorer is None:
        scorer = create_local_irodori_scorer()

    updated = copy.deepcopy(scenario)
    report: list[dict[str, Any]] = []
    segments = updated.get('segments')
    if not isinstance(segments, list):
        return updated, report

    for row in segments:
        if not isinstance(row, dict) or row.get('segment_type') == 'separator':
            continue
        sid = row.get('id')
        raw_tts = row.get('tts_text')
        source_field = raw_tts if isinstance(raw_tts, str) and raw_tts.strip() else row.get('text')
        if not isinstance(source_field, str) or not source_field.strip():
            continue

        normalized_source = normalize_safe_ruby_formats(source_field)
        part_parses = None
        if 'koebuta_tts_parts' in row:
            _, part_parses = _validate_and_parse_parts(normalized_source, row.get('koebuta_tts_parts'), strict=strict)

        if selected_segment_ids is not None and sid not in selected_segment_ids:
            # Keep unselected segments structurally valid without invoking heavy scoring.
            parse_aozora_ruby(normalized_source, strict=strict, allow_ascii_bar=True)
            continue

        result = convert_ruby_text(
            normalized_source,
            mode=mode,
            threshold=threshold,
            single_token_threshold=single_token_threshold,
            scorer=scorer,
            strict=strict,
            allow_ascii_bar=True,
        )
        row['tts_text'] = result.tts_text
        if part_parses is not None:
            flags = [d.selected == 'kana' for d in result.decisions]
            converted_parts: list[str] = []
            offset = 0
            for pp in part_parses:
                k = len(pp.spans)
                converted_parts.append(apply_ruby_selections(pp.plain_text, pp.spans, flags[offset : offset + k]))
                offset += k
            row['koebuta_tts_parts'] = converted_parts

        if result.decisions:
            report.append({
                'segment_id': sid,
                'plain_text': result.plain_text,
                'tts_text': result.tts_text,
                'decisions': [
                    {
                        'surface': d.span.surface,
                        'reading': d.span.reading,
                        'plain_start': d.span.plain_start,
                        'plain_end': d.span.plain_end,
                        'score': round(d.score, 6),
                        'selected': d.selected,
                    }
                    for d in result.decisions
                ],
            })
    return updated, report
