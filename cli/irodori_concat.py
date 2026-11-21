#!/usr/bin/env python3
"""Join recovered Koebuta chapter WAVs with the resolved boundary pauses."""

import argparse
import json
from pathlib import Path
import sys
import wave


BLOCK_FRAMES = 65536


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_chapter(directory):
    plan = read_json(directory / 'plan.json')
    execution = plan['execution']
    pipeline = read_json(directory / 'pipeline.json')
    if pipeline.get('status') != 'complete' or pipeline.get('execution') != execution:
        raise ValueError(f'回収が完了した章の出力フォルダーを指定してください: {directory}')

    requests = plan['requests']
    segment_ids = list(dict.fromkeys(row['segment_id'] for row in requests))
    if not requests or segment_ids != execution['complete_segment_ids']:
        raise ValueError(f'章内の発話をすべて生成してから結合してください: {directory}')
    return directory / 'result.wav', segment_ids, requests[-1]['pause_after_ms'], execution


def concat_chapters(scenario, directories, destination):
    expected_ids = [row['id'] for row in read_json(scenario)['segments']
                    if row.get('segment_type', 'speech') == 'speech']
    chapters = [read_chapter(directory) for directory in directories]
    ids = [sid for _, segment_ids, _, _ in chapters for sid in segment_ids]
    if ids != expected_ids or len(set(ids)) != len(ids):
        raise ValueError('章をシナリオ順に指定し、発話に抜けや重複がないことを確認してください')

    rate = None
    frame_counts = []
    gaps = []
    for index, (path, _, pause_ms, execution) in enumerate(chapters):
        if index and execution['leading_pause_ms']:
            raise ValueError(f'途中の章のWAVに冒頭の休止が含まれています: {path}')
        if index < len(chapters) - 1 and execution['trailing_pause_ms']:
            raise ValueError(f'途中の章のWAVに末尾の休止が含まれています: {path}')
        if type(pause_ms) is not int or not 0 <= pause_ms <= 10000:
            raise ValueError(f'章境界の休止が不正です: {path}')
        with wave.open(str(path), 'rb') as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise ValueError(f'Koebuta CLIのモノラル16 bit PCM WAVを指定してください: {path}')
            if rate is not None and rate != audio.getframerate():
                raise ValueError(f'章のサンプルレートが一致しません: {path}')
            rate = audio.getframerate()
            frames = audio.getnframes()
            if not frames:
                raise ValueError(f'章のWAVが空です: {path}')
        frame_counts.append(frames)
        gaps.append(int(rate * (pause_ms / 1000)) if index < len(chapters) - 1 else 0)

    total_frames = sum(frame_counts) + sum(gaps)
    if total_frames * 2 + 36 > 0xFFFFFFFF:
        raise ValueError('結合結果がWAVのサイズ上限を超えます。複数の音声に分けてください')

    with destination.open('xb') as output_file:
        try:
            with wave.open(output_file, 'wb') as output:
                output.setparams((1, 2, rate, total_frames, 'NONE', 'not compressed'))
                for (path, _, _, _), frames, gap in zip(chapters, frame_counts, gaps):
                    with wave.open(str(path), 'rb') as audio:
                        remaining = frames
                        while remaining:
                            chunk = audio.readframes(min(remaining, BLOCK_FRAMES))
                            if not chunk or len(chunk) % 2:
                                raise ValueError(f'章のWAVが途中で途切れています: {path}')
                            output.writeframesraw(chunk)
                            remaining -= len(chunk) // 2
                    while gap:
                        block = min(gap, BLOCK_FRAMES)
                        output.writeframesraw(bytes(block * 2))
                        gap -= block
        except (Exception, KeyboardInterrupt):
            output_file.close()
            destination.unlink()
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Koebuta CLIで回収した章別WAVをローカルで結合')
    parser.add_argument('--scenario', required=True, type=Path, help='全編のシナリオJSON')
    parser.add_argument('--out', required=True, type=Path, help='未作成の出力WAV（親フォルダーは作成済み）')
    parser.add_argument('chapters', nargs='+', type=Path, help='章別のCLI出力フォルダーをシナリオ順に指定')
    args = parser.parse_args(argv)
    if len(args.chapters) < 2:
        parser.error('章別の出力フォルダーを2つ以上指定してください')
    try:
        concat_chapters(args.scenario, args.chapters, args.out)
    except (OSError, ValueError, TypeError, KeyError, EOFError, wave.Error) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    print(f'CONCAT_READY {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
