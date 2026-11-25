"""CPU-only scenario/settings validation and Drama-3 request planning (schema v1 & v2)."""
from __future__ import annotations

import math
import re
from pathlib import Path

from .core import (
    CONTRACT,
    DEFAULT_BACKEND,
    DEFAULT_MODEL,
    DEFAULT_QUANT,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SGLANG_PIP_SPEC,
    GGUF_SPECS,
    digest,
    file_hash,
    identifier,
)
from .drama3_tags import (
    V1_EMOTION_TO_DRAMA3,
    convert_v1_emojis_to_drama3,
    find_forbidden_control_tokens,
    find_inline_brackets,
    find_unknown_inline_tags,
    spoken_length,
    strip_inline_tags,
)
from .ruby import FORMATS, apply_added_ruby, expand_inline_ruby

ALLOWED_SETTINGS_KEYS = {
    "title",
    "ttsEngine",
    "ttsModel",
    "backend",
    "quant",
    "sampleRate",
    "normalizeRmsDb",
    "reading",
    "voiceMode",
    "baseCaption",
    "acting",
    "cloneCaption",
    "emotion",
    "narratorEmotion",
    "seed",
    "pause",
    "blankLinePauseMs",
    "speakerVoices",
    "voices",
    "textOptions",
    "engineOptions",
}

ALLOWED_SEGMENT_KEYS = {
    "id",
    "speaker_id",
    "text",
    "tts_text",
    "emotion",
    "acting_description",
    "scene_caption",
    "pause_after_ms",
    "blank_lines_after",
    "blank_line_pause_ms",
    "segment_type",
    "text_format",
    "koebuta_added_ruby",
    "notes",
    "seed",
    "koebuta_edit",
    "koebuta_tts_parts",
    "koebuta_merge_backup",
    "tts_text_origin",
    "reading_correction",
}

DEFAULT_ENGINE_OPTIONS = {
    "temperature": 0.8,
    "top_p": 0.85,
    "top_k": 30,
    "max_seconds": 47.55,
    "max_pause_frames": 36,
    "experts_on_cpu": False,
    "sglang_pip_spec": DEFAULT_SGLANG_PIP_SPEC,
}

DEFAULT_SETTINGS = {
    "title": "新しい朗読",
    "ttsEngine": "drama3",
    "ttsModel": DEFAULT_MODEL,
    "backend": DEFAULT_BACKEND,
    "quant": DEFAULT_QUANT,
    "sampleRate": DEFAULT_SAMPLE_RATE,
    "normalizeRmsDb": -18.0,
    "reading": "shared",
    "voiceMode": "design",
    "baseCaption": "落ち着いた明瞭な日本語の朗読。",
    "acting": True,
    "cloneCaption": False,
    "emotion": True,
    "narratorEmotion": True,
    "seed": 314,
    "pause": 0.28,
    "blankLinePauseMs": None,
}

_PINNED_GIT_REF_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|v?\d+\.\d+(?:\.\d+)?(?:[-._A-Za-z0-9]+)?)$")


def _is_finite_num(val: object) -> bool:
    return type(val) in (int, float) and math.isfinite(val)


class PlanError(ValueError):
    def __init__(self, diagnostics: list[dict]):
        self.diagnostics = diagnostics
        lines = [
            f"{d['code']} {d.get('segment_id') or '全体'} / {d['field']}: {d['message']}"
            for d in diagnostics
            if d["level"] == "error"
        ]
        super().__init__("\n".join(lines))


def _normalize_voice_clips(profile: str, raw_entry: object, base_dir: Path, require_transcript: bool, add_error) -> list[dict]:
    items = raw_entry if isinstance(raw_entry, list) else [raw_entry]
    if not items or len(items) > 3:
        add_error(f"voices.{profile}", "参照音声は1〜3クリップの範囲で指定してください", code="E_REFERENCE")
        return []
    clips: list[dict] = []
    for idx, item in enumerate(items):
        if isinstance(item, str):
            wav_rel = item.strip()
            transcript = ""
        elif isinstance(item, dict):
            raw_w = item.get("wav")
            raw_t = item.get("transcript", "")
            wav_rel = raw_w.strip() if isinstance(raw_w, str) else ""
            transcript = raw_t.strip() if isinstance(raw_t, str) else ""
        else:
            add_error(f"voices.{profile}[{idx}]", "文字列パスまたは {wav, transcript} オブジェクトが必要です", code="E_REFERENCE")
            continue
        if not wav_rel:
            add_error(f"voices.{profile}[{idx}]", "wav パスが空です", code="E_REFERENCE")
            continue
        wav_path = (base_dir / wav_rel).resolve()
        if not wav_path.is_file():
            add_error(f"voices.{profile}[{idx}]", f"参照WAVが見つかりません: {wav_path}", code="E_REFERENCE")
            continue
        if require_transcript and not transcript:
            add_error(
                f"voices.{profile}[{idx}].transcript",
                "Drama-3 クローンでは各参照音声の文字起こし（transcript）が必須です",
                code="E_REFERENCE_TRANSCRIPT_REQUIRED",
            )
            continue
        clips.append(
            {
                "wav": str(wav_path),
                "wav_rel": wav_rel,
                "wav_sha256": file_hash(wav_path),
                "transcript": transcript,
            }
        )
    return clips


def _compose_caption(parts: list[str]) -> str:
    cleaned = [p.strip().strip("[]") for p in parts if isinstance(p, str) and p.strip()]
    return " ".join(cleaned)


def build_plan(
    scenario: dict,
    settings: dict,
    *,
    base_dir: str | Path = ".",
    selected_ids: list[str] | None = None,
) -> dict:
    diagnostics: list[dict] = []
    base = Path(base_dir).resolve()

    def add(level: str, code: str, field: str, message: str, sid: str | None = None) -> None:
        diagnostics.append(
            {"level": level, "code": code, "segment_id": sid, "field": field, "message": str(message)}
        )

    def error(field: str, message: str, sid: str | None = None, code: str = "E_STRUCTURE") -> None:
        add("error", code, field, message, sid)

    def stop_if_errors() -> None:
        if any(d["level"] == "error" for d in diagnostics):
            raise PlanError(diagnostics)

    if not isinstance(settings, dict):
        error("settings", "生成設定はオブジェクトが必要です", code="E_SETTINGS")
        stop_if_errors()

    unknown_keys = set(settings.keys()) - ALLOWED_SETTINGS_KEYS
    for key in sorted(unknown_keys):
        error(key, "未対応の生成設定です", code="E_SETTINGS")

    cfg = {**DEFAULT_SETTINGS, **settings}
    if cfg["ttsEngine"] != "drama3":
        error("ttsEngine", "Yomibutaでは ttsEngine='drama3' のみ対応しています", code="E_SETTINGS")
    if not isinstance(cfg["backend"], str) or cfg["backend"] not in ("speech_cpp_gguf", "official"):
        error("backend", f"backend は 'speech_cpp_gguf' または 'official' を指定してください: {cfg['backend']!r}", code="E_SETTINGS")
    elif cfg["backend"] == "speech_cpp_gguf":
        if not isinstance(cfg["quant"], str) or cfg["quant"] not in GGUF_SPECS:
            error("quant", f"未対応の量子化です: {cfg['quant']!r} (対応: {sorted(GGUF_SPECS)})", code="E_SETTINGS")
    else:
        qval = cfg.get("quant")
        if qval is not None and (not isinstance(qval, str) or qval not in ("none", "bf16", "fp8")):
            error("quant", "backend='official' では quant='none' / 'bf16' / 'fp8' を指定してください", code="E_SETTINGS")

    if type(cfg["sampleRate"]) is not int or cfg["sampleRate"] != DEFAULT_SAMPLE_RATE:
        error("sampleRate", f"Drama-3は {DEFAULT_SAMPLE_RATE} Hz 統一です", code="E_SETTINGS")
    norm_rms = cfg.get("normalizeRmsDb")
    if norm_rms is not None and (not _is_finite_num(norm_rms) or not (-36.0 <= float(norm_rms) <= -6.0)):
        error("normalizeRmsDb", "null または -36.0〜-6.0 の有限数値を指定してください", code="E_SETTINGS")
    if not isinstance(cfg["reading"], str) or cfg["reading"] not in ("shared", "cast"):
        error("reading", "'shared' または 'cast' を指定してください", code="E_SETTINGS")
    if not isinstance(cfg["voiceMode"], str) or cfg["voiceMode"] not in ("design", "clone"):
        error("voiceMode", "'design' または 'clone' を指定してください", code="E_SETTINGS")
    for bkey in ("acting", "cloneCaption", "emotion", "narratorEmotion"):
        if type(cfg[bkey]) is not bool:
            error(bkey, "真偽値が必要です", code="E_SETTINGS")
    if not isinstance(cfg["title"], str) or not isinstance(cfg["baseCaption"], str):
        error("title/baseCaption", "文字列が必要です", code="E_SETTINGS")
    if type(cfg["seed"]) is not int or not (0 <= cfg["seed"] <= 9007199254740991):
        error("seed", "0〜9007199254740991の整数が必要です", code="E_SETTINGS")
    if not _is_finite_num(cfg["pause"]) or not (0 <= float(cfg["pause"]) <= 10):
        error("pause", "0〜10の有限な秒数が必要です", code="E_SETTINGS")
    if cfg["blankLinePauseMs"] is not None and (type(cfg["blankLinePauseMs"]) is not int or not (0 <= cfg["blankLinePauseMs"] <= 10000)):
        error("blankLinePauseMs", "null または 0〜10000の整数(ms)が必要です", code="E_SETTINGS")

    # Engine options validation
    raw_eo = cfg.get("engineOptions") if cfg.get("engineOptions") is not None else {}
    if not isinstance(raw_eo, dict):
        error("engineOptions", "オブジェクトが必要です", code="E_SETTINGS")
        raw_eo = {}
    unknown_eo = set(raw_eo.keys()) - set(DEFAULT_ENGINE_OPTIONS.keys())
    for k in sorted(unknown_eo):
        error(f"engineOptions.{k}", "未対応のエンジンオプションです", code="E_SETTINGS")
    eo = {**DEFAULT_ENGINE_OPTIONS, **raw_eo}
    if not _is_finite_num(eo["temperature"]) or not (0 < float(eo["temperature"]) <= 2.0):
        error("engineOptions.temperature", "0 < temperature <= 2.0 の有限数値が必要です", code="E_SETTINGS")
    if not _is_finite_num(eo["top_p"]) or not (0 < float(eo["top_p"]) <= 1.0):
        error("engineOptions.top_p", "0 < top_p <= 1.0 の有限数値が必要です", code="E_SETTINGS")
    if type(eo["top_k"]) is not int or not (1 <= eo["top_k"] <= 4097):
        error("engineOptions.top_k", "1〜4097の整数が必要です", code="E_SETTINGS")
    if not _is_finite_num(eo["max_seconds"]) or not (0 < float(eo["max_seconds"]) <= 95.10893424036281):
        error("engineOptions.max_seconds", "0 < max_seconds <= 95.10 の有限数値が必要です", code="E_SETTINGS")
    if type(eo["max_pause_frames"]) is not int or not (1 <= eo["max_pause_frames"] <= 200):
        error("engineOptions.max_pause_frames", "1〜200の整数が必要です", code="E_SETTINGS")
    if type(eo["experts_on_cpu"]) is not bool:
        error("engineOptions.experts_on_cpu", "真偽値が必要です", code="E_SETTINGS")
    if not isinstance(eo["sglang_pip_spec"], str) or not eo["sglang_pip_spec"].strip():
        error("engineOptions.sglang_pip_spec", "空でないパッケージ指定文字列が必要です", code="E_SETTINGS")
    elif "git+" in eo["sglang_pip_spec"]:
        git_tail = eo["sglang_pip_spec"].split("git+", 1)[1]
        ref = git_tail.rsplit("@", 1)[1] if "@" in git_tail else ""
        if not _PINNED_GIT_REF_RE.fullmatch(ref):
            error(
                "engineOptions.sglang_pip_spec",
                "git URL を指定する場合はブランチ名(main等)ではなく 40桁コミットSHA または vX.Y.Z タグで固定してください",
                code="E_SETTINGS",
            )

    # Scenario validation (schema_version 1 or 2)
    if not isinstance(scenario, dict):
        error("scenario", "シナリオはJSONオブジェクトが必要です")
        stop_if_errors()
    schema_version = scenario.get("schema_version")
    if type(schema_version) is not int or schema_version not in (1, 2):
        error("schema_version", f"対応する schema_version は 1 または 2 です: {schema_version!r}")
        stop_if_errors()

    speakers = scenario.get("speakers")
    segments = scenario.get("segments")
    if not isinstance(speakers, dict) or not speakers:
        error("speakers", "空でない話者一覧が必要です")
    if not isinstance(segments, list) or not segments:
        error("segments", "空でない台本項目配列が必要です")
    stop_if_errors()

    valid_speakers: dict[str, dict] = {}
    for spk_id, spk in speakers.items():
        id_ok = True
        try:
            identifier(spk_id, "speaker_id", 64)
        except ValueError as exc:
            error("speaker_id", str(exc), str(spk_id))
            id_ok = False
        if not isinstance(spk, dict):
            error("speakers", "話者エントリはオブジェクトが必要です", str(spk_id))
            continue
        if not isinstance(spk.get("name"), str) or not spk["name"].strip():
            error("speakers", "話者には空でない name が必要です", str(spk_id))
            continue
        if id_ok:
            valid_speakers[spk_id] = spk

    # Voices validation (also supports fallback from `scenario.speakers[].reference_clips` edited in Inspector v4)
    declared_voices = cfg.get("voices") if cfg.get("voices") is not None else {}
    speaker_voices = cfg.get("speakerVoices") if cfg.get("speakerVoices") is not None else {}
    if not isinstance(declared_voices, dict) or not isinstance(speaker_voices, dict):
        error("voices", "voices / speakerVoices はオブジェクトが必要です", code="E_SETTINGS")
        stop_if_errors()

    effective_declared = dict(declared_voices)
    effective_speaker_voices = dict(speaker_voices)
    if cfg["voiceMode"] == "clone" and not effective_declared:
        # Bridge from Inspector v4 `speakers[spk_id].reference_clips` when `settings.voices` is omitted
        for spk_id, spk in valid_speakers.items():
            if isinstance(spk.get("reference_clips"), list) and spk["reference_clips"]:
                effective_declared[spk_id] = spk["reference_clips"]
                if cfg["reading"] == "cast" and spk_id not in effective_speaker_voices:
                    effective_speaker_voices[spk_id] = spk_id

    normalized_voices: dict[str, list[dict]] = {}
    if cfg["voiceMode"] == "clone":
        if not effective_declared:
            error("voices", "voiceMode='clone' では settings.voices（または speakers[].reference_clips）の指定が必須です", code="E_REFERENCE")
        for profile, raw_entry in effective_declared.items():
            try:
                identifier(profile, "voice profile", 40)
            except ValueError as exc:
                error(f"voices.{profile}", str(exc), code="E_REFERENCE")
                continue
            clips = _normalize_voice_clips(profile, raw_entry, base, True, error)
            if clips:
                normalized_voices[profile] = clips

    text_options = cfg.get("textOptions") if cfg.get("textOptions") is not None else {}
    if not isinstance(text_options, dict):
        error("textOptions", "オブジェクトが必要です", code="E_SETTINGS")
        text_options = {}
    default_fmt = text_options.get("format", "aozora")
    if not isinstance(default_fmt, str) or default_fmt not in FORMATS:
        error("textOptions.format", f"未対応のルビ形式です: {default_fmt!r}", code="E_SETTINGS")
        default_fmt = "aozora"

    seen_ids: set[str] = set()
    warned_shared_voice_caption: set[str] = set()
    speech_rows: list[dict] = []
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            error("segments", f"segments[{idx}] はオブジェクトが必要です")
            continue
        sid = seg.get("id")
        try:
            identifier(sid, "segment id", 64)
        except ValueError as exc:
            error("id", str(exc))
            continue
        if sid in seen_ids:
            error("id", f"発話IDが重複しています: {sid}", sid)
            continue
        seen_ids.add(sid)

        unknown_seg_keys = set(seg.keys()) - ALLOWED_SEGMENT_KEYS
        if unknown_seg_keys:
            error("segment", f"未対応の発話キーが含まれます: {sorted(unknown_seg_keys)}", sid)
            continue

        seg_type = seg.get("segment_type", "speech")
        if not isinstance(seg_type, str) or seg_type not in ("speech", "separator"):
            error("segment_type", f"不正な segment_type です: {seg_type!r}", sid)
            continue
        if seg_type == "separator":
            sep_p = seg.get("pause_after_ms")
            if sep_p is not None and (type(sep_p) is not int or not (0 <= sep_p <= 10000)):
                error("pause_after_ms", "0〜10000の整数が必要です", sid)
            continue

        spk_id = seg.get("speaker_id")
        if not isinstance(spk_id, str) or spk_id not in valid_speakers:
            error("speaker_id", f"未登録または不正な話者IDです: {spk_id!r}", sid)
            continue
        spk = valid_speakers[spk_id]

        raw_text = seg.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            error("text", "発話には空でない text が必要です", sid)
            continue

        emotion = seg.get("emotion")
        if schema_version == 1 and emotion is None:
            error("emotion", "schema_version 1 では emotion が必須です", sid, code="E_EMOTION")
            continue
        if emotion is None:
            emotion = "neutral"
        if not isinstance(emotion, str) or emotion not in V1_EMOTION_TO_DRAMA3:
            error(
                "emotion",
                f"未定義の emotion ID です: {emotion!r} (対応: {sorted(V1_EMOTION_TO_DRAMA3)})",
                sid,
                code="E_EMOTION",
            )
            continue

        seg_fmt = seg.get("text_format", default_fmt)
        if not isinstance(seg_fmt, str) or seg_fmt not in FORMATS:
            error("text_format", f"未対応の text_format です: {seg_fmt!r}", sid, code="E_SETTINGS")
            continue

        # Always validate `koebuta_added_ruby` if present, even when `tts_text` overrides it
        added_ruby = seg.get("koebuta_added_ruby")
        explicit_tts = seg.get("tts_text")
        if added_ruby is not None and added_ruby != []:
            try:
                with_added, added_diags = apply_added_ruby(raw_text, added_ruby, sid=sid, fmt=seg_fmt)
            except ValueError as exc:
                error("koebuta_added_ruby", str(exc), sid, code="E_RUBY")
                continue
        else:
            with_added, added_diags = raw_text, []

        if explicit_tts is not None:
            if not isinstance(explicit_tts, str) or not explicit_tts.strip():
                error("tts_text", "tts_text に空文字は指定できません", sid)
                continue
            if added_ruby:
                add(
                    "warning",
                    "W_ADDED_RUBY_IGNORED_BY_TTS_TEXT",
                    "koebuta_added_ruby",
                    "tts_text が指定されているため koebuta_added_ruby は適用されません",
                    sid,
                )
            resolved_text, r_warns = expand_inline_ruby(explicit_tts, "aozora")
            for w in r_warns:
                add("warning", "W_RUBY_SYNTAX", "tts_text", w, sid)
            unknown_tags = find_unknown_inline_tags(resolved_text)
            if unknown_tags:
                add(
                    "warning",
                    "W_UNKNOWN_INLINE_TAG",
                    "tts_text",
                    f"TAG_LIST.md にない未学習インラインタグが含まれます（読み崩れの原因になります）: {unknown_tags}",
                    sid,
                )
        else:
            diagnostics.extend(added_diags)
            raw_brackets = find_inline_brackets(raw_text)
            if raw_brackets:
                add(
                    "warning",
                    "W_RAW_BRACKET_IN_TEXT",
                    "text",
                    f"原文に半角角括弧が含まれます（Drama-3が演技タグと誤認する可能性）: {raw_brackets}",
                    sid,
                )
            resolved_text, r_warns = expand_inline_ruby(with_added, seg_fmt)
            for w in r_warns:
                add("warning", "W_RUBY_SYNTAX", "text", w, sid)

        # Convert legacy Irodori emojis if present
        resolved_text, emoji_count = convert_v1_emojis_to_drama3(resolved_text)
        if emoji_count:
            add("warning", "W_V1_EMOJI_CONVERTED", "tts_text", f"Irodori用絵文字 {emoji_count} 件をDrama-3タグへ変換しました", sid)

        # Prepend v1 emotion tag if enabled and not already tagged at start
        is_narrator = spk.get("kind") == "narrator"
        use_emotion = cfg["emotion"] and (cfg["narratorEmotion"] or not is_narrator)
        if use_emotion and emotion != "neutral":
            mapped_tag = V1_EMOTION_TO_DRAMA3[emotion]
            if mapped_tag and not resolved_text.lstrip().startswith("["):
                resolved_text = mapped_tag + resolved_text

        caption_parts: list[str] = []
        if cfg["voiceMode"] == "design":
            if cfg["reading"] == "cast" and spk.get("voice_caption"):
                caption_parts.append(spk["voice_caption"])
            else:
                if (
                    cfg["reading"] == "shared"
                    and isinstance(spk.get("voice_caption"), str)
                    and spk["voice_caption"].strip()
                    and spk_id not in warned_shared_voice_caption
                ):
                    warned_shared_voice_caption.add(spk_id)
                    add(
                        "warning",
                        "W_SPEAKER_VOICE_CAPTION_IGNORED",
                        "speakers.voice_caption",
                        f"reading='shared' のため話者 '{spk_id}' の voice_caption は無視され baseCaption が使用されます（話者別にする場合は reading='cast'）",
                        sid,
                    )
                if cfg.get("baseCaption"):
                    caption_parts.append(cfg["baseCaption"])
            if cfg["acting"]:
                if spk.get("acting_description"):
                    caption_parts.append(spk["acting_description"])
                if seg.get("scene_caption"):
                    caption_parts.append(seg["scene_caption"])
                if seg.get("acting_description"):
                    caption_parts.append(seg["acting_description"])
        elif cfg["cloneCaption"] and cfg["acting"]:
            if seg.get("scene_caption"):
                caption_parts.append(seg["scene_caption"])
            if seg.get("acting_description"):
                caption_parts.append(seg["acting_description"])

        caption = _compose_caption(caption_parts)
        prompt_text = f"[{caption}] {resolved_text}" if caption else resolved_text

        # Check forbidden `<|...|>` control tokens across the ENTIRE prompt (including captions!)
        forbidden = find_forbidden_control_tokens(prompt_text)
        if forbidden:
            error(
                "prompt",
                f"単一話者Drama-3では制御トークンを含められません（本文・caption共通）: {forbidden}",
                sid,
                code="E_FORBIDDEN_CONTROL_TOKEN",
            )
            continue

        if spoken_length(resolved_text) == 0:
            error("text", "タグ除去後に読み上げる文字がありません", sid)
            continue

        voice_profile = "none"
        if cfg["voiceMode"] == "clone":
            if cfg["reading"] == "shared":
                voice_profile = next(iter(normalized_voices)) if normalized_voices else "none"
            else:
                vp_raw = effective_speaker_voices.get(spk_id, "")
                voice_profile = vp_raw if isinstance(vp_raw, str) else ""
                if not voice_profile or voice_profile not in normalized_voices:
                    error("speakerVoices", f"話者 '{spk_id}' の参照音声プロファイルが未設定です", sid, code="E_REFERENCE")
                    continue
            plain_utterance = strip_inline_tags(resolved_text)
            for clip in normalized_voices.get(voice_profile, []):
                if plain_utterance and plain_utterance == clip["transcript"].strip():
                    add(
                        "warning",
                        "W_SAME_AS_REFERENCE_TRANSCRIPT",
                        "text",
                        "参照音声の transcript と同一のセリフです（自己回帰モデルで読み飛ばしが起きやすくなります）",
                        sid,
                    )

        blanks_after = seg.get("blank_lines_after")
        if blanks_after is not None and (type(blanks_after) is not int or blanks_after < 0):
            error("blank_lines_after", "0以上の整数が必要です", sid)
            continue
        blank_pause_override = seg.get("blank_line_pause_ms")
        if blank_pause_override is not None and (type(blank_pause_override) is not int or not (0 <= blank_pause_override <= 10000)):
            error("blank_line_pause_ms", "0〜10000の整数が必要です", sid)
            continue

        pause_ms_explicit = seg.get("pause_after_ms")
        if pause_ms_explicit is not None and (type(pause_ms_explicit) is not int or not (0 <= pause_ms_explicit <= 10000)):
            error("pause_after_ms", "0〜10000の整数が必要です", sid)
            continue

        sep_pauses: list[int] = []
        j = idx + 1
        while j < len(segments) and isinstance(segments[j], dict) and segments[j].get("segment_type") == "separator":
            sp = segments[j].get("pause_after_ms")
            if type(sp) is int and 0 <= sp <= 10000:
                sep_pauses.append(sp)
            j += 1

        # Faithful pause resolution (Koebuta `faithful.py` compatible):
        # 1. Explicit `seg.pause_after_ms` wins.
        # 2. Otherwise explicit `separator.pause_after_ms` (max of adjacent separators, even if < common pause) wins.
        # 3. Otherwise opt-in blank-line pause applies ONLY if `blank_line_pause_ms` or `settings.blankLinePauseMs` is explicitly configured.
        # 4. Otherwise default `settings.pause` (e.g. 280ms) applies.
        if pause_ms_explicit is not None:
            pause_ms = pause_ms_explicit
        elif sep_pauses:
            pause_ms = max(sep_pauses)
        elif type(blanks_after) is int and blanks_after > 0 and (blank_pause_override is not None or cfg["blankLinePauseMs"] is not None):
            pause_ms = blank_pause_override if blank_pause_override is not None else int(cfg["blankLinePauseMs"])
        else:
            pause_ms = int(round(float(cfg["pause"]) * 1000))

        competing = sep_pauses + ([pause_ms_explicit] if pause_ms_explicit is not None else [])
        if any(v != pause_ms for v in competing):
            add("warning", "W_PAUSE_CONFLICT", "pause_after_ms", f"境界には {pause_ms}ms を適用します（合算なし）", sid)

        seg_seed = seg.get("seed", cfg["seed"])
        if type(seg_seed) is not int or not (0 <= seg_seed <= 9007199254740991):
            error("seed", "発話の seed は 0〜9007199254740991 の整数が必要です", sid)
            continue

        req = {
            "prompt": prompt_text,
            "spoken_text": resolved_text,
            "caption": caption,
            "voice_profile": voice_profile,
            "seed": seg_seed,
            "engine_options": eo,
        }
        speech_rows.append(
            {
                "segment_id": sid,
                "speaker_id": spk_id,
                "pause_after_ms": pause_ms,
                "spoken_chars": spoken_length(resolved_text),
                "request": req,
                "fingerprint": digest(
                    {
                        "contract": CONTRACT,
                        "model": cfg["ttsModel"],
                        "backend": cfg["backend"],
                        "quant": cfg.get("quant"),
                        "request": req,
                        "voice_hashes": [c["wav_sha256"] for c in normalized_voices.get(voice_profile, [])],
                        "voice_transcripts": [c["transcript"] for c in normalized_voices.get(voice_profile, [])],
                    }
                ),
            }
        )

    stop_if_errors()

    if selected_ids is not None:
        wanted = set(selected_ids)
        found = {r["segment_id"] for r in speech_rows}
        missing = sorted(wanted - found)
        if missing:
            error("ids", f"存在しない発話IDが指定されました: {missing}", code="E_SELECTION")
            stop_if_errors()
        speech_rows = [r for r in speech_rows if r["segment_id"] in wanted]

    plan = {
        "contract": CONTRACT,
        "schema_version": schema_version,
        "settings": {
            "title": cfg["title"],
            "ttsEngine": cfg["ttsEngine"],
            "ttsModel": cfg["ttsModel"],
            "backend": cfg["backend"],
            "quant": cfg.get("quant"),
            "sampleRate": cfg["sampleRate"],
            "normalizeRmsDb": cfg.get("normalizeRmsDb"),
            "reading": cfg["reading"],
            "voiceMode": cfg["voiceMode"],
            "cloneCaption": cfg["cloneCaption"],
            "seed": cfg["seed"],
            "pause": cfg["pause"],
            "blankLinePauseMs": cfg["blankLinePauseMs"],
            "engineOptions": eo,
        },
        "voices": normalized_voices,
        "requests": speech_rows,
        "diagnostics": diagnostics,
    }
    plan["plan_signature"] = digest(
        {
            "contract": CONTRACT,
            "settings": plan["settings"],
            "requests": [{"segment_id": r["segment_id"], "fingerprint": r["fingerprint"], "pause_after_ms": r["pause_after_ms"]} for r in speech_rows],
        }
    )
    return plan
