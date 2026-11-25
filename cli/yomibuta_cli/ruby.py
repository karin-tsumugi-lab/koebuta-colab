"""Deterministic ruby resolution for Aozora/Narou/Kakuyomu/Pixiv and koebuta_added_ruby.

Phase 1-2 policy for Drama-3:
- Author rubies and explicit `tts_text` rubies are always expanded.
- `koebuta_added_ruby` entries with `selection == "kana"` expand to `reading`.
- `selection == "surface"` keeps `surface`.
- `selection == "auto"` keeps `surface` and emits `W_RUBY_AUTO_DEFERRED`.
"""
from __future__ import annotations

import re

FORMATS = ("none", "aozora", "narou", "kakuyomu", "pixiv")
KANJI = r"\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002ffff々〆〇ヶヵ〻"
NAROU_KANA = r"ぁ-ゖァ-ヺー・ヴゝゞヽヾ　 "
_AOZORA_NOTE_RE = re.compile(r"［＃([^［］\n]*)］")
_KNOWN_AOZORA_LAYOUT = re.compile(
    r"(?:改ページ|改丁|改見開き|ここから[０-９0-9]+字下げ|ここで字下げ終わり|[０-９0-9]+字下げ|"
    r"「[^「」［］\n]+」に傍点|「[^「」［］\n]+」は[大中小]見出し|[大中小]見出し(?:終わり)?)"
)


def strip_aozora_layout(text: str) -> str:
    return _AOZORA_NOTE_RE.sub(lambda m: "" if _KNOWN_AOZORA_LAYOUT.fullmatch(m[1]) else m[0], text)


def expand_inline_ruby(body: str, fmt: str = "aozora") -> tuple[str, list[str]]:
    """Expand author/explicit inline rubies to their spoken readings."""
    if fmt not in FORMATS:
        raise ValueError(f"未対応のルビ形式です: {fmt}")
    if fmt == "none":
        return body, []

    warnings: list[str] = []
    text = body
    marker = "\ue000"
    while marker in text:
        marker += "\ue000"

    if fmt == "pixiv":
        text = re.sub(r"\[\[rb:([^\[\]\n>]+?)\s*>\s*([^\[\]\n]+?)\]\]", lambda m: m[2].strip(), text)
        if "[[" in text or "]]" in text:
            warnings.append("未対応または不正なpixiv記法があります")
    else:
        if fmt == "aozora":
            text = re.sub(r"※［＃小書き平仮名([ぁ-ゖ])、[0-9０-９]+[-－][0-9０-９]+］", lambda m: m[1], text)
            text = strip_aozora_layout(text)
        if fmt == "kakuyomu":
            text = re.sub(r"｜《([^《》\n]*)》", lambda m: f"{marker}O;{m[1]}{marker}C;", text)
            text = text.replace("｜《", f"{marker}A;")
            text = re.sub(r"《《([^《》\n]+)》》", r"\1", text)
        if fmt == "narou":
            text = re.sub(r"[｜|]([（(])", lambda m: f"{marker}{'P;' if m[1] == '(' else 'F;'}", text)
        bars = "｜" if fmt == "aozora" else "｜|"
        text = re.sub(rf"[{bars}]([^｜|《》\n]+)《([^《》\n]+)》", lambda m: m[2], text)
        text = re.sub(rf"[{KANJI}]+《([^《》\n]+)》", lambda m: m[1], text)
        if fmt == "narou":
            text = re.sub(rf"[{KANJI}]+\(([{NAROU_KANA}]+)\)", lambda m: m[1].strip(), text)
            text = re.sub(rf"[{KANJI}]+（([{NAROU_KANA}]+)）", lambda m: m[1].strip(), text)
        if any(mark in text for mark in ("《", "》", "［＃", "｜", "］")):
            warnings.append("未対応または不正なルビ・注記があります")
        text = (
            text.replace(f"{marker}O;", "《")
            .replace(f"{marker}C;", "》")
            .replace(f"{marker}A;", "《")
            .replace(f"{marker}P;", "(")
            .replace(f"{marker}F;", "（")
        )
    return text, warnings


def _inline_ruby_spans(text: str, fmt: str) -> list[tuple[int, int]]:
    if fmt not in FORMATS or fmt == "none":
        return []
    patterns: list[str] = []
    if fmt == "pixiv":
        patterns.append(r"\[\[rb:[^\[\]\n]+\]\]")
    else:
        if fmt == "aozora":
            patterns.append(r"※?［＃[^［］\n]*］")
        if fmt == "kakuyomu":
            patterns.append(r"《《[^《》\n]+》》")
        bars = "｜" if fmt == "aozora" else "｜|"
        patterns.append(rf"[{bars}][^｜|《》\n]+《[^《》\n]+》")
        patterns.append(rf"[{KANJI}]+《[^《》\n]+》")
        if fmt == "narou":
            patterns.append(rf"[{KANJI}]+\([{NAROU_KANA}]+\)")
            patterns.append(rf"[{KANJI}]+（[{NAROU_KANA}]+）")
    return sorted((m.start(), m.end()) for pat in patterns for m in re.finditer(pat, text))


def apply_added_ruby(
    source_text: str,
    entries: object,
    *,
    sid: str,
    fmt: str = "aozora",
) -> tuple[str, list[dict]]:
    """Validate and apply `koebuta_added_ruby` entries to `source_text`."""
    if entries is None or entries == []:
        return source_text, []
    if not isinstance(entries, list):
        raise ValueError(f"{sid}: koebuta_added_ruby は配列が必要です")

    diags: list[dict] = []
    author_spans = _inline_ruby_spans(source_text, fmt)
    validated: list[tuple[int, int, str, str, str]] = []
    for idx, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError(f"{sid}: koebuta_added_ruby[{idx}] はオブジェクトが必要です")
        start = item.get("start")
        end = item.get("end")
        surface = item.get("surface")
        reading = item.get("reading")
        selection = item.get("selection", "auto")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > len(source_text):
            raise ValueError(f"{sid}: koebuta_added_ruby[{idx}] の範囲 [{start}, {end}) が不正です")
        if not isinstance(surface, str) or source_text[start:end] != surface:
            raise ValueError(
                f"{sid}: koebuta_added_ruby[{idx}] の表記が一致しません "
                f"(期待={surface!r}, 実体={source_text[start:end]!r})"
            )
        if not isinstance(reading, str) or not reading.strip():
            raise ValueError(f"{sid}: koebuta_added_ruby[{idx}] の読みが空です")
        if selection not in ("auto", "kana", "surface"):
            raise ValueError(f"{sid}: koebuta_added_ruby[{idx}] の selection が不正です: {selection!r}")
        if any(a < end and start < b for a, b in author_spans):
            raise ValueError(f"{sid}: koebuta_added_ruby[{idx}] が原文の作者ルビ・注記範囲と重複しています")
        validated.append((start, end, surface, reading, selection))

    validated.sort(key=lambda x: x[0])
    for prev, curr in zip(validated, validated[1:]):
        if curr[0] < prev[1]:
            raise ValueError(f"{sid}: koebuta_added_ruby の範囲が重複しています")

    out: list[str] = []
    cursor = 0
    for start, end, surface, reading, selection in validated:
        out.append(source_text[cursor:start])
        if selection == "kana":
            out.append(reading)
        elif selection == "surface":
            out.append(surface)
        else:
            out.append(surface)
            diags.append(
                {
                    "level": "warning",
                    "code": "W_RUBY_AUTO_DEFERRED",
                    "segment_id": sid,
                    "field": "koebuta_added_ruby",
                    "message": f"自動ルビ判定は未有効のため元表記を維持します: {surface} ({reading})",
                }
            )
        cursor = end
    out.append(source_text[cursor:])
    return "".join(out), diags
