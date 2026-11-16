"""Read-only verification of the two real GPU runs; never generates audio."""
import argparse
import json
from pathlib import Path
import sys
import wave

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'cli'))
from irodori_generate import verify_authored_recovery
from irodori_colab_cli import verify_recovery
from irodori_cli.core import read_json
from irodori_cli.jobs import inside, wav_info

def require(condition, message):
    if not condition:
        raise ValueError(message)

def inspect_run(folder, ids, scope):
    folder = Path(folder).resolve()
    summary = read_json(folder / 'pipeline.json')
    require(summary['status'] == 'complete', f'{scope}: pipeline not complete')
    require(summary['execution']['scope'] == scope, f'{scope}: scope differs')
    recovered = Path(summary['recovered']).resolve()
    require(recovered.is_relative_to(folder / 'synthesize'), 'recovery outside run folder')
    require(verify_recovery(recovered).get('audio_checked'), 'audio not checked')
    document = read_json(folder / 'project.json')
    plan = read_json(folder / 'plan.json')
    require([r['id'] for r in plan['requests']] == ids, 'unexpected unit order/count')
    require(document['scenario'] == read_json(Path(__file__).with_name('scenario.json')),
            'scenario changed; this test requires the fixed fixture')
    require(document['settings'] == read_json(Path(__file__).with_name('settings.json')),
            'settings changed; this test requires the fixed fixture')
    require('source' not in document['scenario'], 'source was fabricated')
    require(all(plan['settings'][key] is True for key in
                ('acting', 'emotion', 'narratorEmotion')), 'default directives disabled')
    manifest = verify_authored_recovery(recovered, document, plan['requests'])
    combined = manifest['combined']
    require(wav_info(folder / 'result.wav')['frames'] == combined['frames'],
            'exported WAV frame count differs')
    from irodori_cli.core import file_hash
    require(file_hash(folder / 'result.wav') == combined['sha256'], 'exported WAV hash differs')
    used = [next(t for t in manifest['takes'] if t['file'] == name)
            for name in combined['take_files']]
    rate = combined['sample_rate']
    require(all(t['sample_rate'] == rate for t in used), 'different rates')
    expected = sum(t['frames'] for t in used)
    execution = plan['execution']
    expected += int(rate * execution['leading_pause_ms'] / 1000)
    expected += int(rate * execution['trailing_pause_ms'] / 1000)
    expected += sum(int(rate * row['pause_after_ms'] / 1000)
                    for row in plan['requests'][:-1])
    require(expected == combined['frames'], 'explicit pause/assembly frames differ')
    engine = manifest.get('provenance', {})
    require(engine.get('contract') == 'koebuta-faithful-v1', 'legacy worker used')
    require(engine.get('watermark_expected_payload') == 'IRDTS', 'missing watermark provenance')
    return dict(folder=folder, summary=summary, document=document, plan=plan,
                manifest=manifest, used=used, rate=rate)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', required=True)
    parser.add_argument('--piece', required=True)
    args = parser.parse_args()
    full = inspect_run(args.full, ['heading', 'garden#1', 'garden#2', 'girl'], 'full')
    piece = inspect_run(args.piece, ['garden#2'], 'selection')
    req = full['plan']['requests']
    require(req[0]['request']['text'] ==
            full['document']['scenario']['segments'][1]['text'],
            'heading was split or rewritten')
    require([r['pause_after_ms'] for r in req] == [500, 0, 700, 200], 'wrong gaps')
    require(full['plan']['execution']['leading_pause_ms'] == 100, 'wrong leading gap')
    require(full['plan']['execution']['trailing_pause_ms'] == 200, 'wrong trailing gap')
    require(set(full['manifest']['parent_audio']) == {'garden'}, 'wrong parent WAV set')
    require(full['manifest']['parent_audio']['garden']['frames'] ==
            sum(t['frames'] for t in full['used'] if t['id'].startswith('garden#')),
            'parent WAV contains a gap or missing piece')
    require(piece['manifest']['parent_audio'] == {}, 'single piece marked parent complete')
    require(piece['plan']['execution']['complete_segment_ids'] == [], 'wrong parent completion')
    require(piece['manifest']['combined']['frames'] == piece['used'][0]['frames'],
            'single-piece WAV has added boundary silence')
    require(piece['summary']['session_stopped'] is True, 'runtime stop not confirmed')
    output = dict(status='passed', checks='structure, source preservation, unit order, PCM frames, hashes, pause, parent completion, worker provenance, stop',
                  full_seconds=full['manifest']['combined']['seconds'],
                  piece_seconds=piece['manifest']['combined']['seconds'],
                  speech_quality='not evaluated by this script; listen separately',
                  watermark='worker provenance checked; no independent watermark decoding')
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
