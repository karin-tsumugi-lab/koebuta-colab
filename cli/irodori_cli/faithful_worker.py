"""Explicit transport contract for authored scenarios; no legacy normalization."""
from __future__ import annotations

import argparse
import copy
import inspect
import os
from pathlib import Path
import subprocess
import sys

from .core import atomic_json, digest, file_hash
from .faithful import CONTRACT, build_plan, load_json, plan_signature, project_document
from .jobs import assembly, generate


def execute(document, voices, job, infer, engine=None):
    """CPU-testable remote path. Never writes the input or splits its utterances."""
    document = project_document(document)
    if document.get('contract') != CONTRACT:
        raise ValueError('忠実生成の実行契約が必要です')
    if (Path(job) / 'job.json').exists():
        raise ValueError('新しいジョブIDを指定してください。既存の生成結果は変更しません')
    planned = build_plan(document['scenario'], document['settings'], voices=voices,
                         selected=document.get('selection'))
    signature = plan_signature(planned)
    if signature != document.get('expected_plan'):
        raise ValueError('ホストと遠隔の生成計画が一致しません。生成を開始しません')
    rows = copy.deepcopy(planned['requests'])
    for row in rows:
        row['fingerprint'] = digest(dict(authored=row['fingerprint'], engine=engine or {}))
    manifest = generate(job, rows, planned['settings']['pause'], infer,
                        provenance=engine, execution=planned['execution'])
    manifest['authored_plan_signature'] = signature
    manifest['parent_audio'] = {}
    if manifest['status'] == 'complete':
        try:
            for sid in planned['execution']['complete_segment_ids']:
                parent_rows = [r for r in rows if r['segment_id'] == sid]
                if parent_rows[0]['part_count'] > 1:
                    # A parent WAV has no inter-part or after-parent silence.
                    parent_rows = [{**r, 'pause_after_ms': 0} for r in parent_rows]
                    record = assembly(job, parent_rows, 0, copy.deepcopy(manifest))
                    manifest['parent_audio'][sid] = record
        except Exception as exc:
            manifest['status'] = 'failed'
            manifest['errors'].append({'id': 'parent_assembly', 'error': str(exc)})
    atomic_json(Path(job) / 'job.json', manifest)
    return manifest


def runtime_infer(model, runtimes):
    """Pinned runtime and watermark checks are identical to the legacy worker."""
    os.environ['USE_TF'] = '0'
    repo = Path('/content/Irodori-TTS')
    sys.path.insert(0, str(repo))
    import importlib.metadata
    from huggingface_hub import hf_hub_download
    from .environments import MODEL_REVISIONS, IRODORI_COMMIT
    from .tts_dependencies import WATERMARK_REVISION, TOKENIZER_REVISIONS
    checkpoint = hf_hub_download(model, 'model.safetensors', revision=MODEL_REVISIONS[model])
    codec_repo = 'Aratako/Semantic-DACVAE-Japanese-32dim'
    codec = hf_hub_download(codec_repo, 'weights.pth', revision=MODEL_REVISIONS[codec_repo])
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    if commit != IRODORI_COMMIT:
        raise RuntimeError('Irodoriのコードが検証済みの版と一致しません')
    engine = dict(model=model, checkpoint_sha256=file_hash(checkpoint), irodori_commit=commit,
                  model_revision=MODEL_REVISIONS[model], codec_revision=MODEL_REVISIONS[codec_repo],
                  watermark_expected_payload='IRDTS', watermark_model_revision=WATERMARK_REVISION,
                  tokenizer_revisions=TOKENIZER_REVISIONS,
                  watermark_loader_sha256=file_hash(Path(__file__).parent / 'tts_dependencies.py'),
                  torch=importlib.metadata.version('torch'), worker_sha256=file_hash(__file__), contract=CONTRACT)
    key = digest(engine)
    runtime = runtimes.get(key)
    if runtimes and runtime is None:
        raise RuntimeError('ロード済みモデルの実行契約が異なります。解放後に再実行してください')

    def infer(request, destination):
        nonlocal runtime
        import numpy as np
        import soundfile as sf
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey, SamplingRequest
        missing = set(request) - set(inspect.signature(SamplingRequest).parameters)
        if missing:
            raise RuntimeError(f'SamplingRequestの仕様が異なります: {sorted(missing)}')
        from .tts_dependencies import pinned_watermark_backend, pinned_text_tokenizers, require_watermark
        if runtime is None:
            print('PROGRESS IrodoriをGPUへロードしています', flush=True)
            with pinned_watermark_backend(), pinned_text_tokenizers():
                runtime = InferenceRuntime.from_key(RuntimeKey(checkpoint=checkpoint, codec_repo=codec,
                    model_device='cuda', codec_device='cuda', model_precision='fp32', codec_precision='fp32'))
            require_watermark(runtime)
            runtimes[key] = runtime
        result = runtime.synthesize(SamplingRequest(**request))
        require_watermark(runtime, result)
        audio = result.audios[0].detach().cpu().float().view(-1).numpy()
        if not audio.size or not np.isfinite(audio).all():
            raise RuntimeError('空または非有限値の音声が生成されました')
        sf.write(str(destination), audio, int(result.sample_rate), subtype='PCM_16')
    return infer, engine


def main(argv=None, runtimes=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--voice', action='append', default=[])
    parser.add_argument('--allow-unreviewed', action='store_true')
    parser.add_argument('--runtime', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    document = project_document(load_json(args.project))
    if document.get('contract') != CONTRACT:
        raise ValueError('忠実生成の実行契約が必要です')
    if (Path(args.job) / 'job.json').exists():
        raise ValueError('新しいジョブIDを指定してください')
    voices = dict(item.split('=', 1) for item in args.voice)
    # Validate the complete plan before acquiring the model or loading CUDA.
    plan = build_plan(document['scenario'], document['settings'], voices=voices,
                      selected=document.get('selection'))
    if plan_signature(plan) != document.get('expected_plan'):
        raise ValueError('ホストと遠隔の生成計画が一致しません')
    if runtimes is None and not args.runtime:
        # The Colab launcher has no ML dependencies. Use the prepared TTS venv,
        # and the existing serialized resident lifecycle rather than base Python.
        from .environments import executable
        from . import resident
        Path(args.job).mkdir(parents=True, exist_ok=True)
        arguments = ['--project', args.project, '--job', args.job]
        for voice in args.voice:
            arguments += ['--voice', voice]
        if resident.enabled():
            resident.run(executable('tts'), ['faithful', *arguments], args.job, args.project)
            return 0
        return subprocess.run([executable('tts'), '-u', '-m',
                               'irodori_cli.faithful_worker', '--runtime', *arguments]).returncode
    infer, engine = runtime_infer(plan['settings']['ttsModel'], runtimes if runtimes is not None else {})
    manifest = execute(document, voices, args.job, infer, engine)
    if manifest['status'] != 'complete':
        raise RuntimeError('選択範囲の生成が完了していません。job.jsonを確認してください')
    print('JOB_STATUS', manifest['status'], manifest['execution']['scope'], flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
