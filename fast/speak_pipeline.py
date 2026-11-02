#!/usr/bin/env python3
"""Koebuta v1 準拠の単一話者・高速自動読み上げパイプライン。

入力:
  * SPEAK_PROMPT_JA.md の短い台本テキスト（見出し省略時は neutral）
  * Koebuta v1 のシナリオJSON（単一話者のみ）

台本テキストは Koebuta v1 JSON に正規化し、音声生成時に限って
短文を隣接発話へ吸収する。原文のシナリオJSONは書き換えない。

  python3 speak_pipeline.py --input reply.txt --ref voice.wav --out speech_out
  python3 speak_pipeline.py --input reply.txt --emit-json > scenario.json
  python3 speak_pipeline.py --input scenario.json --plan-only

単一話者の参照音声・声質はユーザー指定。Colabへの転送・接続は扱わない。
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path

MODEL_ID = 'Aratako/Irodori-TTS-v4.1-Small'
MODEL_REVISION = '2b28324dc263ed5e6638b3cf3dd94c82ead07b4b'
CODEC_ID = 'Aratako/Semantic-DACVAE-Japanese-32dim'
CODEC_REVISION = '47376ee24834d7a05a48ebabfe3cde29b3c5e214'

EMOTIONS = dict(zip(
    ('neutral', 'joy', 'anger', 'sad', 'kind', 'tease', 'anxiety', 'tension',
     'surprise', 'tired', 'whisper', 'giggle', 'fear', 'sleepy', 'resolve'),
    ('', '😆', '😠', '😭', '🫶', '😏', '🥺', '😰', '😲', '😮‍💨', '👂', '🤭', '😱', '😪', '💥')))
EMOTION_JA = dict(zip(EMOTIONS, (
    '平静', '喜び', '怒り', '悲しみ', '優しさ', 'からかい', '不安', '緊張',
    '驚き', '疲れ', '囁き', '忍び笑い', '恐怖', '眠気', '強調')))

MIN_CHARS = 10                 # 絶対的な品質保証ではなく運用上の目安
MAX_CHARS = 80                 # 合成単位の目安
PAUSE_MS = 280                 # 発話間の既定無音
HEADER = re.compile(r'^\[\s*([a-z]+)\s*(?:/\s*(.*?))?\]\s*$')
DELIMITER = re.compile(r'[。！？!?、，,；;：:\n\s]')
RUBY_LIKE = re.compile(r'｜[^《\n]+《[^》\n]+》|[一-龥々]+《[^》\n]+》|\[\[rb:')


def parse_script(text: str) -> list[dict]:
    """省トークン台本を解析する。見出しや空行は構文、本文は原則保持。"""
    chunks: list[dict] = []
    current: dict | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines, current
        if current is not None:
            body = '\n'.join(lines).strip()
            if body:
                chunks.append({'emotion': current['emotion'],
                               'acting': current['acting'], 'text': body})
        current, lines = None, []

    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        match = HEADER.fullmatch(line.strip())
        if match is not None:
            flush()
            emotion = match.group(1)
            if emotion not in EMOTIONS:
                print(f'警告: 未知の感情ID {emotion!r} を neutral として扱います', file=sys.stderr)
                emotion = 'neutral'
            current = {'emotion': emotion, 'acting': (match.group(2) or '').strip()}
        elif not line.strip():
            flush()
        else:
            if current is None:
                current = {'emotion': 'neutral', 'acting': ''}
            lines.append(line)
    flush()
    return chunks


def script_to_scenario(script: str) -> dict:
    """LLMの台本を Koebuta v1 交換形式へ変換。原稿全文 source は捏造しない。"""
    chunks = parse_script(script)
    if not chunks:
        raise ValueError('読み上げる本文がありません')
    segments = []
    for i, c in enumerate(chunks, 1):
        seg = {'id': f't{i:04d}', 'speaker_id': 'assistant',
               'text': c['text'], 'emotion': c['emotion']}
        if c['acting']:
            seg['acting_description'] = c['acting']
        segments.append(seg)
    return {'schema_version': 1,
            'speakers': {'assistant': {'name': 'アシスタント', 'kind': 'character'}},
            'segments': segments}


def load_scenario(raw: str, input_format: str = 'auto') -> dict:
    """自動判別は { で始まる場合JSONとして解析。JSON不正なら黙って本文にしない。"""
    if input_format not in ('auto', 'script', 'json'):
        raise ValueError('不明な入力形式です')
    if input_format == 'script' or (input_format == 'auto' and not raw.lstrip().startswith('{')):
        scenario = script_to_scenario(raw)
    else:
        scenario = json.loads(raw)
    validate_scenario(scenario)
    return scenario


def validate_scenario(scenario: dict) -> None:
    """最小限のKoebuta v1構造を検査。単一話者以外は誤った声で読まず停止。"""
    if not isinstance(scenario, dict) or type(scenario.get('schema_version')) is not int or scenario['schema_version'] != 1:
        raise ValueError('Koebuta schema_version: 1 のJSONが必要です')
    speakers = scenario.get('speakers')
    segments = scenario.get('segments')
    if not isinstance(speakers, dict) or len(speakers) != 1:
        raise ValueError('簡素版は単一話者の speakers のみ対応します')
    speaker_id, speaker = next(iter(speakers.items()))
    if not isinstance(speaker_id, str) or not speaker_id or not isinstance(speaker, dict):
        raise ValueError('話者IDと話者情報が不正です')
    if speaker.get('kind') not in ('character', 'narrator'):
        raise ValueError('話者の kind は character または narrator にしてください')
    if not isinstance(segments, list):
        raise ValueError('segments は配列でなければなりません')
    ids = set()
    has_speech = False
    for i, seg in enumerate(segments, 1):
        if not isinstance(seg, dict):
            raise ValueError(f'segments[{i}] はオブジェクトが必要です')
        seg_id = seg.get('id')
        if not isinstance(seg_id, str) or not seg_id or seg_id in ids:
            raise ValueError(f'segments[{i}] の id が欠落・重複しています')
        ids.add(seg_id)
        kind = seg.get('segment_type', 'speech')
        if kind == 'separator':
            # 区切りは発話しない
            pass
        elif kind == 'speech':
            has_speech = True
            if seg.get('speaker_id') != speaker_id:
                raise ValueError(f'{seg_id}: speaker_id が未定義です')
            if not isinstance(seg.get('text'), str) or not seg['text'].strip():
                raise ValueError(f'{seg_id}: 空または不正な text')
            emotion = seg.get('emotion', 'neutral')
            if not isinstance(emotion, str) or emotion not in EMOTIONS:
                print(f'警告: {seg_id} の未知のemotionを neutral として扱います', file=sys.stderr)
            reading = seg.get('tts_text')
            if reading is not None and not isinstance(reading, str):
                print(f'警告: {seg_id} の不正なtts_textを無視します', file=sys.stderr)
            fmt = seg.get('text_format')
            if fmt not in (None, 'none') and not (isinstance(reading, str) and reading.strip()):
                # この軽量版はKoebutaの各サイト用ルビ展開エンジンを実装していない
                raise ValueError(f'{seg_id}: text_format={fmt!r} は読み変換が必要です。tts_textを指定してください')
            if RUBY_LIKE.search(seg['text']) and not (isinstance(reading, str) and reading.strip()):
                raise ValueError(f'{seg_id}: 未展開のルビが含まれます。tts_textを指定してください')
        else:
            raise ValueError(f'{seg_id}: 未知の segment_type={kind!r}')
        for key in ('pause_after_ms', 'blank_lines_after'):
            if key in seg and (type(seg[key]) is not int or seg[key] < 0):
                raise ValueError(f'{seg_id}: {key} は0以上の整数にしてください')
    if not has_speech:
        raise ValueError('読み上げる発話がありません')


def _safe_cut(text: str, pos: int) -> int:
    """結合文字やZWJ、異体字セレクタの途中をできるだけ避ける。"""
    while 1 < pos < len(text) and (
        unicodedata.combining(text[pos]) or text[pos] in ('\ufe0f', '\u200d')
        or text[pos - 1] == '\u200d'
    ):
        pos -= 1
    return pos


def split_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    """本文を一切消さずに分割。文末→読点等→文字数の順で選択。"""
    if limit < 2:
        raise ValueError('limit は2以上にしてください')
    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        choices = []
        for m in DELIMITER.finditer(remaining[:limit]):
            pos = _safe_cut(remaining, m.end())
            if pos >= MIN_CHARS and (len(remaining) - pos >= MIN_CHARS):
                # 文末優先。末尾が句点+閉じ括弧なら括弧も残す
                if remaining[pos - 1] in '。！？!?':
                    while pos < len(remaining) and remaining[pos] in '」』”"）)]':
                        pos += 1
                    priority = 0
                elif remaining[pos - 1] == '\n':
                    priority = 1
                else:
                    priority = 2
                if pos <= limit:
                    choices.append((priority, abs(pos - min(60, limit)), -pos, pos))
        pos = min(choices)[-1] if choices else _safe_cut(remaining, limit)
        # 末尾が1～9文字だけ取り残されるケースを先に回避。
        # 自然な区切りを優先できないときは少し前で切る。
        if len(remaining) - pos < MIN_CHARS:
            reserve = _safe_cut(remaining, len(remaining) - MIN_CHARS)
            if MIN_CHARS <= reserve <= limit:
                pos = reserve
        if pos < 1:
            pos = limit
        parts.append(remaining[:pos])
        remaining = remaining[pos:]
    if remaining:
        parts.append(remaining)
    assert ''.join(parts) == text
    return parts


def _make_unit(text: str, emotion: str, acting: str, origin: str, pause: int | None) -> dict:
    return {'text': text, 'emotion': emotion, 'acting': acting, 'origin': origin,
            'pause_after_ms': pause, 'barrier_after': pause is not None,
            'spans': [(text, emotion, acting)]}


def _merge_units(left: dict, right: dict) -> dict:
    spans = left['spans'] + right['spans']
    totals: dict[str, int] = defaultdict(int)
    for piece, emotion, _ in spans:
        totals[emotion] += len(piece)
    # 最も多くの文字を占める感情を採用。同点なら左側が優先。
    emotion = max(totals, key=totals.get)
    cues = []
    for _, e, a in spans:
        cue = f'{EMOTION_JA[e]}（{a}）' if a else EMOTION_JA[e]
        if not cues or cues[-1] != cue:
            cues.append(cue)
    acting = (spans[0][2] if len(cues) == 1 else '発話の流れに沿って、' + 'から'.join(cues) + 'へ移る')
    return {'text': left['text'] + right['text'], 'emotion': emotion,
            'acting': acting, 'origin': left['origin'] + '+' + right['origin'],
            'pause_after_ms': right['pause_after_ms'],
            'barrier_after': right['barrier_after'], 'spans': spans}


def plan_units(scenario: dict, min_chars: int = MIN_CHARS, max_chars: int = MAX_CHARS) -> list[dict]:
    """KoebutaのJSONを変更せず、音声生成用の発話単位のみ分割・短文結合。"""
    validate_scenario(scenario)
    units: list[dict] = []
    for seg in scenario['segments']:
        if seg.get('segment_type', 'speech') == 'separator':
            if units:
                units[-1]['barrier_after'] = True
                if units[-1]['pause_after_ms'] is None:
                    units[-1]['pause_after_ms'] = seg.get('pause_after_ms', PAUSE_MS)
            continue
        reading = seg.get('tts_text')
        if not isinstance(reading, str) or not reading.strip():
            reading = seg['text']
        emotion = seg.get('emotion', 'neutral')
        if not isinstance(emotion, str) or emotion not in EMOTIONS:
            emotion = 'neutral'
        acting = seg.get('acting_description')
        if not isinstance(acting, str):
            acting = ''
        parts = split_text(reading, max_chars)
        for j, part in enumerate(parts):
            # 明示的な間は最終生成単位の直後だけに適用
            last = j == len(parts) - 1
            pause = seg.get('pause_after_ms') if last else None
            unit = _make_unit(part, emotion, acting, seg['id'], pause)
            if last and seg.get('blank_lines_after', 0) > 0:
                unit['barrier_after'] = True
            units.append(unit)

    # 隣接要素の短文を、感情一致・長さ・語順を考慮して吸収。前後どちらも評価する。
    i = 0
    while i < len(units):
        if len(units[i]['text'].strip()) >= min_chars:
            i += 1
            continue
        options = []
        for j in (i - 1, i + 1):
            if not 0 <= j < len(units):
                continue
            left_i = min(i, j)
            left, right = units[left_i], units[left_i + 1]
            if left['barrier_after'] or len(left['text'] + right['text']) > max_chars:
                continue
            total = len(left['text'] + right['text'])
            mismatch = int(left['emotion'] != right['emotion']) + int(left['acting'] != right['acting'])
            score = (total < min_chars, mismatch, abs(total - 40), j != i + 1)
            options.append((score, left_i))
        if not options:
            i += 1
            continue
        left_i = min(options)[1]
        units[left_i:left_i + 2] = [_merge_units(units[left_i], units[left_i + 1])]
        i = max(0, left_i - 1)
    # どうしても吸収できない短文は水増しせず警告する。
    for u in units:
        if len(u['text'].strip()) < min_chars:
            print(f'警告: {u["origin"]} は{min_chars}文字未満ですが、結合可能な隣接発話がありません', file=sys.stderr)
    # 下流に内部spanを公開しない
    return [{k: v for k, v in u.items() if k != 'spans'} for u in units]


def build_requests(units: list[dict], ref_wav: str, base_caption: str,
                   seed: int, steps: int, *, use_emotion: bool = True) -> list[dict]:
    """Koebutaと同じ感情ID→絵文字の変換。話者の声は指定WAVで固定。"""
    requests = []
    for u in units:
        caption = '\n'.join(p for p in (base_caption.strip(), u['acting'].strip()) if p)
        requests.append({
            'text': (EMOTIONS[u['emotion']] if use_emotion else '') + u['text'],
            'caption': caption or None,
            'ref_wav': ref_wav, 'no_ref': False,
            'max_ref_seconds': 30, 'num_steps': steps, 'seed': seed,
        })
    return requests


class Speaker:
    """Irodoriランタイムは生成中に一度だけ読み込む。"""

    def __init__(self, irodori_dir: str | None = None):
        if irodori_dir:
            sys.path.insert(0, irodori_dir)
        from huggingface_hub import hf_hub_download
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey
        ckpt = hf_hub_download(MODEL_ID, 'model.safetensors', revision=MODEL_REVISION)
        codec = hf_hub_download(CODEC_ID, 'weights.pth', revision=CODEC_REVISION)
        self.runtime = InferenceRuntime.from_key(RuntimeKey(
            checkpoint=ckpt, codec_repo=codec,
            model_device='cuda', codec_device='cuda',
            model_precision='fp32', codec_precision='fp32'))

    def synthesize(self, request: dict):
        import numpy as np
        from irodori_tts.inference_runtime import SamplingRequest
        result = self.runtime.synthesize(SamplingRequest(**request))
        audio = result.audios[0].detach().cpu().float().view(-1).numpy()
        if not audio.size or not np.isfinite(audio).all():
            raise RuntimeError('空または異常な音声が生成されました')
        return audio, int(result.sample_rate)


def play_worker(play_queue: queue.Queue) -> None:
    """音声生成と再生は別スレッド。"""
    while True:
        path = play_queue.get()
        try:
            if path is None:
                return
            subprocess.run(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', str(path)],
                           check=False)
        finally:
            play_queue.task_done()


def run(script_text: str, ref_wav: str, base_caption: str = '', out_dir: str = 'speech_out',
        seed: int = 314, steps: int = 40, play: bool = False,
        irodori_dir: str | None = None, input_format: str = 'auto') -> Path:
    """逐次書き込みで全発話分の音声配列をメモリに保持しない。"""
    import numpy as np
    import soundfile as sf

    scenario = load_scenario(script_text, input_format)
    units = plan_units(scenario)
    speaker_info = next(iter(scenario['speakers'].values()))
    requests = build_requests(units, ref_wav, base_caption, seed, steps,
                              use_emotion=speaker_info['kind'] != 'narrator')
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if play and shutil.which('ffplay') is None:
        raise RuntimeError('--play の利用には ffplay が必要です')
    speaker = Speaker(irodori_dir)
    play_queue = queue.Queue() if play else None
    thread = None
    if play_queue is not None:
        thread = threading.Thread(target=play_worker, args=(play_queue,), daemon=True)
        thread.start()

    full_path = out / 'speech.wav'
    temp_path = out / 'speech.partial.wav'
    merged = None
    sample_rate = None
    pending_pause = None
    try:
        for i, (unit, request) in enumerate(zip(units, requests), 1):
            audio, sr = speaker.synthesize(request)
            if merged is None:
                sample_rate = sr
                merged = sf.SoundFile(str(temp_path), mode='w', samplerate=sr,
                                      channels=1, subtype='PCM_16')
            if sr != sample_rate:
                raise RuntimeError('生成単位ごとにサンプリング周波数が変化しました')
            if i > 1:
                ms = pending_pause if pending_pause is not None else PAUSE_MS
                # 長い無音もまとめて巨大な配列にしない
                samples = int(sample_rate * ms / 1000)
                while samples:
                    count = min(samples, sample_rate)
                    merged.write(np.zeros(count, dtype='float32'))
                    samples -= count
            merged.write(audio)
            pending_pause = unit['pause_after_ms']
            part_path = out / f'chunk_{i:03d}.wav'
            sf.write(str(part_path), audio, sr, subtype='PCM_16')
            print(f'[{i}/{len(requests)}] {unit["origin"]} {unit["text"][:30]}', file=sys.stderr)
            if play_queue is not None:
                play_queue.put(part_path)
        if merged is not None:
            merged.close()
            merged = None
        temp_path.replace(full_path)
    finally:
        if merged is not None:
            merged.close()
        if play_queue is not None:
            play_queue.put(None)
            play_queue.join()
            if thread:
                thread.join()
    return full_path


def main() -> None:
    ap = argparse.ArgumentParser(description='単一話者のKoebuta v1自動読み上げ（台本テキスト／JSON）')
    ap.add_argument('--ref', help='参照WAV（音声生成時に必須）')
    ap.add_argument('--caption-file', help='共通の声・話し方の説明文ファイル')
    ap.add_argument('--input', help='台本テキストまたはKoebuta JSON。省略時は標準入力')
    ap.add_argument('--format', choices=('auto', 'script', 'json'), default='auto')
    ap.add_argument('--out', default='speech_out', help='音声の保存先')
    ap.add_argument('--seed', type=int, default=314)
    ap.add_argument('--steps', type=int, choices=(20, 40, 60), default=40)
    ap.add_argument('--play', action='store_true', help='合成と並行してffplayで再生')
    ap.add_argument('--irodori-dir', help='Irodori-TTSのチェックアウト場所')
    ap.add_argument('--emit-json', action='store_true', help='Koebuta v1 JSONを標準出力して終了（GPU不要）')
    ap.add_argument('--plan-only', action='store_true', help='音声生成単位をJSON表示して終了（GPU不要）')
    args = ap.parse_args()
    if args.emit_json and args.plan_only:
        ap.error('--emit-json と --plan-only は同時に使えません')
    if (args.emit_json or args.plan_only) and args.play:
        ap.error('--play は音声生成時だけ指定できます')
    if not (args.emit_json or args.plan_only):
        if not args.ref:
            ap.error('音声生成時は --ref が必要です')
        if not Path(args.ref).is_file():
            ap.error(f'参照WAVが見つかりません: {args.ref}')
    raw = Path(args.input).read_text(encoding='utf-8') if args.input else sys.stdin.read()
    try:
        scenario = load_scenario(raw, args.format)
        if args.emit_json:
            print(json.dumps(scenario, ensure_ascii=False, indent=2))
            return
        if args.plan_only:
            units = plan_units(scenario)
            print(json.dumps({'planned_units': [{k: v for k, v in u.items() if k != 'barrier_after'}
                                                 for u in units], 'min_chars': MIN_CHARS,
                              'max_chars': MAX_CHARS}, ensure_ascii=False, indent=2))
            return
        caption = Path(args.caption_file).read_text(encoding='utf-8') if args.caption_file else ''
        full = run(raw, args.ref, caption, args.out, args.seed, args.steps,
                   args.play, args.irodori_dir, args.format)
        print(full)
    except (ValueError, json.JSONDecodeError) as exc:
        ap.exit(2, f'入力エラー: {exc}\n')


if __name__ == '__main__':
    main()
