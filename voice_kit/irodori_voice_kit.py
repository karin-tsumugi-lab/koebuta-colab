#!/usr/bin/env python3
"""Koebuta v3 Voice Kit: Generate multiple seed candidates for cloning reference WAVs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
CLI_GENERATE = ROOT / 'cli' / 'irodori_generate.py'

DEFAULT_SAMPLE_TEXT = (
    '窓の外では静かに雨が降り続いていた。'
    '「ねえ、これからどこへ向かうつもりなの？」'
    '落ち着いた声が、静かな部屋に柔らかく響く。'
)
DEFAULT_SEEDS = (101, 202, 303, 404, 505)

PRESETS: dict[str, dict[str, str]] = {
    'female_narrator': {
        'label': '落ち着いた女性ナレーター（小説全般・標準）',
        'caption': '落ち着いた明瞭な声の成人女性。やや低めで、ゆったりと丁寧に話す。穏やかで聞き取りやすい朗読調。',
        'text': DEFAULT_SAMPLE_TEXT,
    },
    'male_narrator': {
        'label': '深みのある男性ナレーター（文芸・歴史・シリアス）',
        'caption': '落ち着いた深みのある声の成人男性。中低音で響きがよく、一定のテンポで明瞭に語る。静かで安定感のある朗読調。',
        'text': '長い坂道を登りきると、眼下には夕暮れの街並みが広がっていた。「ようやくここまで来たな」彼は静かに息をつき、遠くの空を見上げた。',
    },
    'bright_heroine': {
        'label': '明るく清楚な若い女性（ヒロイン・青春・会話劇）',
        'caption': '明るく澄んだ声の若い女性。やや高めでハリがあり、表情豊かにハキハキと話す。親しみやすく自然な距離感。',
        'text': '朝の光がカーテン越しに差し込んでくる。「おはよう！今日はいいお天気だから、少し遠くまで歩いてみようよ」彼女は笑顔で扉を開けた。',
    },
    'gentle_girl': {
        'label': '穏やかで柔らかい少女（ファンタジー・癒やし系）',
        'caption': '柔らかく透明感のある少女の声。息遣いが優しく、少し控えめに丁寧な口調で話す。耳元に近い穏やかな距離感。',
        'text': '小さな花びらが風に揺れて、水面へと落ちていく。「大丈夫ですよ、私がずっとそばにいますから」彼女はそっと微笑んで手を差し伸べた。',
    },
    'whisper_sister': {
        'label': '包容力のあるお姉さん（囁き寄り・近距離）',
        'caption': '包容力のある柔らかい大人の女性の声。息多めで温かみがあり、耳元で語りかけるような近い距離感でゆったりと話す。',
        'text': '今日も一日、本当にお疲れさまでした。「無理をしなくてもいいんですよ。ゆっくり目を閉じて、少しだけ休んでくださいね」',
    },
    'cool_youth': {
        'label': 'クールで知的な青年（ミステリー・現代劇）',
        'caption': '落ち着いたクリアな声の若い男性。感情の起伏を抑えたクールな口調で、明瞭かつ淡々と話す。少し乾いたスマートな響き。',
        'text': '机の上に置かれた資料に目を落とし、彼は静かに口を開いた。「状況はすべて把握している。あとは君がどう決断するか、それだけだ」',
    },
    'energetic_boy': {
        'label': '元気でまっすぐな少年（冒険・ファンタジー）',
        'caption': '明るくハリのある少年の声。やや高めで勢いがあり、まっすぐにはっきりと話す。裏表のない快活なトーン。',
        'text': '向こうの丘の上に、見たこともない大きな塔がそびえ立っていた。「すごいな、あそこに行けばきっと新しい手がかりが見つかるはずだよ！」',
    },
    'veteran_butler': {
        'label': '渋く品のある老紳士・執事（古典・重厚）',
        'caption': '深みと渋みのある高齢男性の声。低く落ち着いた響きで、礼儀正しく格調高い口調でゆっくりと話す。',
        'text': '暖炉の火が静かに揺らめく書斎で、老人は丁寧に頭を下げた。「お帰りなさいませ。お嬢様がお待ちでございます、どうぞこちらへ」',
    },
    'warm_mother': {
        'label': '温かく優しい大人の女性（童話・エッセイ・日常）',
        'caption': '温かみのある柔らかな成人女性の声。中音域で丸みがあり、包み込むように優しく穏やかなテンポで語りかける。',
        'text': '夕飯の支度をするいい香りが、台所からふんわりと漂ってくる。「さあ、手を洗っていらっしゃい。温かいスープがちょうどできたところよ」',
    },
    'calm_scholar': {
        'label': '知的で穏やかな中年男性（解説・SF・ノンフィクション）',
        'caption': '穏やかで知的な印象の中年男性の声。中音域で聞き取りやすく、論理的かつ丁寧な語り口で落ち着いて話す。',
        'text': 'かつてこの場所に存在した古い街の記録は、今も図書館の奥深くに眠っている。「歴史の扉をひとつずつ開いていくことにしましょう」',
    },
    'cheerful_friend': {
        'label': '親しみやすい快活な青年（日常会話・コメディ）',
        'caption': '親しみやすく明るい若い男性の声。自然体でくだけた雰囲気があり、軽快なテンポで楽しそうに話す。',
        'text': '駅の改札を抜けると、見慣れた顔がこちらに向かって手を振っていた。「おーい、こっちこっち！久しぶりだな、元気にしてたか？」',
    },
    'stern_commander': {
        'label': '凛とした威厳のある女性（ファンタジー・戦記）',
        'caption': '芯が強く凛とした成人女性の声。やや低めでよく通り、迷いのない毅然とした口調で明瞭に話す。',
        'text': '冷たい風が吹き抜ける城壁の上で、彼女はまっすぐに前を見据えた。「これより先は一歩も退かない。各自、持ち場を死守しなさい」',
    },
}


def parse_seeds(raw: str) -> list[int]:
    if not raw or not raw.strip():
        raise ValueError('--seeds には1つ以上の整数シードを指定してください（例: 101,202,303）')
    seeds: list[int] = []
    for part in raw.split(','):
        token = part.strip()
        if not token:
            continue
        try:
            val = int(token)
        except ValueError as exc:
            raise ValueError(f'不正なシード値です: {token}') from exc
        if not 0 <= val <= 2147483647:
            raise ValueError(f'シード値は 0〜2147483647 の範囲で指定してください: {val}')
        if val not in seeds:
            seeds.append(val)
    if not seeds:
        raise ValueError('--seeds に有効なシードがありません')
    return seeds


def resolve_job_prefix(explicit_prefix: str | None, out_dir: Path | None) -> str:
    """Derive a collision-free job prefix from --job-prefix or --out directory name."""
    if explicit_prefix:
        cleaned = re.sub(r'[^A-Za-z0-9_-]', '_', explicit_prefix.strip())
    elif out_dir is not None:
        cleaned = re.sub(r'[^A-Za-z0-9_-]', '_', out_dir.name.strip())
    else:
        cleaned = 'vkit'
    cleaned = cleaned.strip('_-') or 'vkit'
    return cleaned[:32]


def build_sample_scenario(sample_text: str, caption: str) -> dict:
    return {
        'schema_version': 1,
        'speakers': {
            'narrator': {
                'name': '試聴話者',
                'kind': 'narrator',
                'voice_caption': caption,
            }
        },
        'segments': [
            {
                'id': 'sample01',
                'speaker_id': 'narrator',
                'text': sample_text,
                'emotion': 'neutral',
            }
        ],
    }


def build_sample_settings(caption: str, seed: int, steps: int, model: str) -> dict:
    return {
        'title': f'Voice Candidate (seed {seed})',
        'voiceMode': 'design',
        'reading': 'shared',
        'baseCaption': caption,
        'acting': False,
        'emotion': False,
        'narratorEmotion': False,
        'ttsModel': model,
        'seed': seed,
        'steps': steps,
        'pause': 0.28,
    }


def adopt_candidate(
    from_out: Path,
    seed: int,
    save_to: Path,
    *,
    write_settings: Path | None = None,
    overwrite: bool = False,
) -> int:
    summary_path = from_out / 'candidates.json'
    if not summary_path.is_file():
        raise FileNotFoundError(f'候補一覧ファイルが見つかりません: {summary_path}')
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    matched = next((item for item in summary.get('candidates', []) if item.get('seed') == seed), None)
    if not matched or not matched.get('wav'):
        raise ValueError(f'seed={seed} の生成済みWAVが見つかりません')
    src = Path(matched['wav'])
    if not src.is_absolute():
        src = (from_out / src).resolve()
    if not src.is_file():
        raise FileNotFoundError(f'WAVファイルが存在しません: {src}')
    save_to = save_to.expanduser().resolve()
    meta_path = save_to.with_suffix('.voice_meta.json')
    targets = [save_to, meta_path]
    if write_settings is not None:
        write_settings = write_settings.expanduser().resolve()
        targets.append(write_settings)

    for index, target in enumerate(targets):
        for other in [src, *targets[:index]]:
            if target == other or (target.exists() and other.exists() and target.samefile(other)):
                raise ValueError(f'採用元と各出力には別々のファイルを指定してください: {target}')
        if target.exists() and not overwrite:
            raise FileExistsError(f'保存先が既に存在します（上書きする場合は --overwrite を指定）: {target}')
        if target.exists() and not target.is_file():
            raise ValueError(f'ファイルの保存先を指定してください: {target}')

    record = {
        'adopted_seed': seed,
        'source_wav': str(src),
        'saved_wav': str(save_to),
        'caption': summary.get('caption'),
        'sample_text': summary.get('sample_text'),
        'model': summary.get('model'),
        'steps': summary.get('steps'),
    }

    if write_settings is not None:
        settings_dir = write_settings.parent
    elif save_to.parent.name == 'voices':
        settings_dir = save_to.parent.parent
    else:
        settings_dir = save_to.parent

    try:
        rel_wav = Path(os.path.relpath(save_to, settings_dir)).as_posix()
    except ValueError:
        rel_wav = str(save_to)

    snippet = {
        'title': '作品名',
        'voiceMode': 'clone',
        'reading': 'shared',
        'voices': {'voice_a': rel_wav},
        'baseCaption': summary.get('caption', '落ち着いた明瞭な日本語の朗読。'),
        'acting': True,
        'emotion': True,
        'narratorEmotion': True,
        'ttsModel': summary.get('model', 'Aratako/Irodori-TTS-v4.1-Small'),
        'seed': 314,
        'steps': summary.get('steps', 40),
        'pause': 0.28,
    }
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with save_to.open('wb' if overwrite else 'xb') as output:
            if not overwrite:
                created.append(save_to)
            with src.open('rb') as input_wav:
                shutil.copyfileobj(input_wav, output)
        documents = [(meta_path, record)]
        if write_settings is not None:
            documents.append((write_settings, snippet))
        for target, document in documents:
            with target.open('w' if overwrite else 'x', encoding='utf-8') as output:
                if not overwrite:
                    created.append(target)
                json.dump(document, output, ensure_ascii=False, indent=2)
                output.write('\n')
    except OSError:
        for target in created:
            target.unlink(missing_ok=True)
        raise

    print(f'ADOPTED_WAV {save_to}')
    print(f'VOICE_META  {meta_path}')
    if write_settings is not None:
        print(f'SETTINGS    {write_settings}')
    else:
        suggested_settings = settings_dir / 'settings.json'
        print(f'\n--- {suggested_settings} への保存用設定例（一人朗読の場合） ---')
        print(json.dumps(snippet, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Koebuta v3 参照音声作成キット: 声の説明文からシード違いの試聴WAVを一括生成します'
    )
    parser.add_argument('--list-presets', action='store_true', help='定番ボイスカタログ（12種）を表示して終了')
    parser.add_argument('--preset', choices=sorted(PRESETS), help='定番ボイスカタログのIDを選択')
    parser.add_argument('--caption', help='声の説明文（例: "落ち着いた明瞭な声の成人女性。やや低めで丁寧に話す。"）')
    parser.add_argument('--text', help='試聴セリフ（省略時は50〜70文字の標準試聴セリフを使用）')
    parser.add_argument(
        '--seeds',
        default=','.join(str(s) for s in DEFAULT_SEEDS),
        help='カンマ区切りのシード値リスト（既定: 101,202,303,404,505）',
    )
    parser.add_argument('--steps', type=int, default=40, choices=[20, 40, 60], help='生成ステップ数（既定: 40）')
    parser.add_argument('--model', default='Aratako/Irodori-TTS-v4.1-Small', help='TTSモデル名')
    parser.add_argument('--session', default='voice-kit', help='Colabセッション名（既定: voice-kit）')
    parser.add_argument('--job-prefix', help='Colabジョブ名の接頭辞（省略時は --out のフォルダー名から自動設定）')
    parser.add_argument('--out', type=Path, help='候補WAVを並べて保存する新しい出力フォルダー')
    parser.add_argument('--new', action='store_true', help='最初の候補で新しいGPUランタイムを作成')
    parser.add_argument('--gpu', default='T4', choices=['T4', 'L4', 'G4', 'A100', 'H100'], help='GPU種別（既定: T4）')
    parser.add_argument('--skip-prepare', action='store_true', help='すでにTTS環境を準備済みの既存セッションを使用')
    parser.add_argument('--keep-session', action='store_true', help='全候補の生成後もColabランタイムを停止せず保持する')
    parser.add_argument('--no-usage', action='store_true', help='CU残量の照会を省略する')
    parser.add_argument('--dry-run', action='store_true', help='Colabへ接続せず、全候補の設定と実行計画のみ検証する')
    parser.add_argument('--from-out', type=Path, help='生成済みの候補フォルダー（--adopt と併用）')
    parser.add_argument('--adopt', type=int, metavar='SEED', help='採用するシード値を指定（--from-out, --save-to と併用）')
    parser.add_argument('--save-to', type=Path, help='採用したWAVのコピー先パス（例: works/my_book/voices/narrator.wav）')
    parser.add_argument('--write-settings', type=Path, help='採用したWAVを参照する settings.json の書き出し先パス（任意）')
    parser.add_argument('--overwrite', action='store_true', help='--adopt 時に既存の保存先ファイルを上書きする')
    args = parser.parse_args(argv)

    if args.list_presets:
        for key, info in PRESETS.items():
            print(f'[{key}] {info["label"]}')
            print(f'  Caption : {info["caption"]}')
            print(f'  試聴文  : {info["text"]}\n')
        return 0

    if args.adopt is not None or args.from_out is not None or args.save_to is not None:
        if args.adopt is None or args.from_out is None or args.save_to is None:
            parser.error('候補の採用には --from-out <候補フォルダー> --adopt <SEED> --save-to <保存先.wav> の3つを指定してください')
        return adopt_candidate(
            args.from_out,
            args.adopt,
            args.save_to,
            write_settings=args.write_settings,
            overwrite=args.overwrite,
        )

    if not args.caption and not args.preset:
        parser.error('--caption "<声の説明文>" または --preset <プリセットID> を指定してください（一覧は --list-presets）')
    if args.new and args.skip_prepare:
        parser.error('--new と --skip-prepare は併用できません')

    preset_info = PRESETS.get(args.preset, {}) if args.preset else {}
    caption = (args.caption or preset_info.get('caption', '')).strip()
    sample_text = (args.text or preset_info.get('text') or DEFAULT_SAMPLE_TEXT).strip()
    if not caption:
        parser.error('空でない --caption が必要です')
    if not sample_text:
        parser.error('空でない --text が必要です')

    seeds = parse_seeds(args.seeds)
    job_prefix = resolve_job_prefix(args.job_prefix, args.out)

    if args.dry_run:
        cli_dir = ROOT / 'cli'
        if (cli_dir / 'irodori_cli').is_dir():
            if str(cli_dir) not in sys.path:
                sys.path.insert(0, str(cli_dir))
            from irodori_cli.faithful import build_plan
            sample_scenario = build_sample_scenario(sample_text, caption)
            for seed in seeds:
                sample_settings = build_sample_settings(caption, seed, args.steps, args.model)
                build_plan(sample_scenario, sample_settings)
        elif args.model not in ('Aratako/Irodori-TTS-v4.1-Small', 'Aratako/Irodori-TTS-500M-v2', 'Aratako/Irodori-TTS-500M-v2-VoiceDesign'):
            raise ValueError(f'未対応のTTSモデルです: {args.model}')
        plan_items = []
        for idx, seed in enumerate(seeds, 1):
            is_first = idx == 1
            is_last = idx == len(seeds)
            plan_items.append({
                'candidate_index': idx,
                'seed': seed,
                'output_wav': f'candidate_{idx:02d}_seed{seed}.wav',
                'job': f'{job_prefix}_{idx:02d}_s{seed}',
                'new_runtime': bool(args.new and is_first),
                'skip_prepare': bool(args.skip_prepare or not is_first),
                'stop_after_download': bool(is_last and not args.keep_session),
            })
        payload = {
            'status': 'dry_run_ok',
            'preset': args.preset,
            'caption': caption,
            'sample_text': sample_text,
            'sample_text_length': len(sample_text),
            'model': args.model,
            'steps': args.steps,
            'session': args.session,
            'job_prefix': job_prefix,
            'candidates': plan_items,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.out is None:
        parser.error('GPU生成時は --out <出力フォルダー> が必須です')
    out_dir = args.out.expanduser().resolve()
    if out_dir.exists():
        raise FileExistsError(f'出力先が既に存在します。新しいフォルダーを指定してください: {out_dir}')
    out_dir.mkdir(parents=True, exist_ok=False)
    configs_dir = out_dir / 'configs'
    runs_dir = out_dir / 'runs'
    configs_dir.mkdir()
    runs_dir.mkdir()

    scenario_path = configs_dir / 'sample_scenario.json'
    scenario_doc = build_sample_scenario(sample_text, caption)
    scenario_path.write_text(json.dumps(scenario_doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    summary: dict = {
        'preset': args.preset,
        'caption': caption,
        'sample_text': sample_text,
        'model': args.model,
        'steps': args.steps,
        'session': args.session,
        'job_prefix': job_prefix,
        'candidates': [],
    }
    summary_path = out_dir / 'candidates.json'

    print(f'=== Koebuta v3 参照音声作成キット ===')
    print(f'声の説明文 : {caption}')
    print(f'試聴セリフ : {sample_text} ({len(sample_text)}文字)')
    print(f'生成シード : {seeds} (計{len(seeds)}候補)')
    print(f'ジョブ接頭辞: {job_prefix}')
    print(f'出力先     : {out_dir}\n')

    for idx, seed in enumerate(seeds, 1):
        is_first = idx == 1
        is_last = idx == len(seeds)
        settings_path = configs_dir / f'settings_seed{seed}.json'
        settings_doc = build_sample_settings(caption, seed, args.steps, args.model)
        settings_path.write_text(json.dumps(settings_doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

        job_id = f'{job_prefix}_{idx:02d}_s{seed}'
        run_out = runs_dir / f'seed_{seed}'
        candidate_wav_name = f'candidate_{idx:02d}_seed{seed}.wav'
        candidate_wav_path = out_dir / candidate_wav_name

        cmd = [
            sys.executable,
            str(CLI_GENERATE),
            '--scenario', str(scenario_path),
            '--settings', str(settings_path),
            '--session', args.session,
            '--job', job_id,
            '--out', str(run_out),
        ]
        if is_first:
            if args.new:
                cmd += ['--new', '--gpu', args.gpu]
            elif args.skip_prepare:
                cmd += ['--skip-prepare']
        else:
            cmd += ['--skip-prepare']

        if is_last and not args.keep_session:
            cmd += ['--stop-after-download']
        if args.no_usage:
            cmd += ['--no-usage']

        print(f'--- [{idx}/{len(seeds)}] seed={seed} を生成中 (job={job_id}) ---', flush=True)
        res = subprocess.run(cmd)
        result_wav = run_out / 'result.wav'
        if res.returncode != 0 or not result_wav.is_file():
            summary['candidates'].append({
                'index': idx,
                'seed': seed,
                'status': 'failed',
                'exit_code': res.returncode,
                'wav': None,
            })
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'ERROR: seed={seed} の生成に失敗しました（終了コード {res.returncode}）。ログ: {run_out}', file=sys.stderr)
            return res.returncode or 1

        shutil.copyfile(result_wav, candidate_wav_path)
        summary['candidates'].append({
            'index': idx,
            'seed': seed,
            'status': 'complete',
            'wav': candidate_wav_name,
        })
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'OK: {candidate_wav_path}\n', flush=True)

    print('=== 全候補の生成が完了しました ===')
    for item in summary['candidates']:
        print(f"  [{item['index']}] seed={item['seed']} -> {out_dir / item['wav']}")
    print('\n気に入った声を本番用の参照WAV＋設定JSONとして採用するには:')
    print(f'  python3 voice_kit/irodori_voice_kit.py --from-out {out_dir} --adopt <選んだSEED> '
          f'--save-to works/my_book/voices/narrator.wav --write-settings works/my_book/settings.json')
    print(f'VOICE_KIT_READY {summary_path}', flush=True)
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
