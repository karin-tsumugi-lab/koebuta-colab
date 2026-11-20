"""Self-contained Koebuta v3 ruby bridge (host validation & remote/local selection)."""
from __future__ import annotations

import copy
from typing import Any

from .ruby_core import (
    RubySyntaxError,
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
