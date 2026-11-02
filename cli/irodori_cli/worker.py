"""Transient analysis stages and an optionally resident, serialized TTS runtime."""
from __future__ import annotations

import argparse
import copy
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .core import (atomic_json, digest, file_hash,
                   normalize_project, read_json, is_narrator)
from .jobs import generate, job_lock


def memory():
    result = subprocess.run(['nvidia-smi','--query-gpu=memory.used,memory.total','--format=csv,noheader,nounits'], text=True, capture_output=True, check=True)
    used, total = map(int, result.stdout.strip().split(','))
    return {'used_mib':used, 'total_mib':total}


def qwen(args):
    from .qwen_stage import run
    return run(args)


def emotions(args):
    os.environ['USE_TF'] = '0'
    # Reuse the tested emotion taxonomy, not its hard-coded test characters.
    from .taxonomy import EMOTION_QUESTION, CORE_EMOTIONS
    project = normalize_project(read_json(args.project))
    if not project['analyzed']:
        raise ValueError('先に話者を分析してください')
    job = Path(args.job)
    with job_lock(job):
        cache_path = job/'emotion_results.json'
        results = read_json(cache_path) if cache_path.exists() else {}
        roles = {r['id']:r for r in project['roles']}
        agent = None
        errors = []
        selected = set(args.ids.split(',')) if getattr(args, 'ids', None) else {s['id'] for s in project['segments']}
        if not selected <= {s['id'] for s in project['segments']}:
            raise ValueError('分類対象の発話IDが存在しません')
        from .text_conversion import convert_project
        speaking={r['id'] for r in convert_project(project) if r['segment_type']=='speech'}
        candidates=[row for row in project['segments'] if row['id'] in speaking and row['id'] in selected and (not row['reviewed'] or args.include_reviewed)]
        for index,row in enumerate(candidates,1):
            print(f'PROGRESS 感情判定: {index}/{len(candidates)}件目を処理中',flush=True)
            if row['id'] not in selected:
                continue
            if row['reviewed'] and not args.include_reviewed:
                continue
            if (job/'.pause').exists() or (job/'.stop').exists():
                print('CLASSIFICATION_INTERRUPTED', flush=True)
                return
            role = roles[row['role']]
            if is_narrator(role) and not project['narratorEmotion']:
                row['emotion'] = 'neutral'
                atomic_json(args.project, project)
                continue
            key = digest({'text':row['text'],'question':EMOTION_QUESTION,'classifier_contract':2})
            if key not in results:
                try:
                    if agent is None:
                        import laya
                        from .environments import MODEL_REVISIONS
                        agent = laya.load('convaiinnovations/laya-multilingual',revision=MODEL_REVISIONS['convaiinnovations/laya-multilingual'])
                        atomic_json(job/'laya_memory_while_loaded.json', memory())
                    question = copy.deepcopy(EMOTION_QUESTION)
                    answer = agent.predict({'text':row['text']}, question)['answers']['emotion']
                    label = str(answer['choice'])
                    if label not in CORE_EMOTIONS:
                        raise ValueError(f'未対応のLayaラベル: {label}')
                    results[key] = {'emotion':label, 'confidence':str(answer.get('confidence')), 'segment_id':row['id']}
                    atomic_json(cache_path, results)
                except Exception as exc:
                    row['reviewed'] = False
                    atomic_json(args.project, project)
                    errors.append({'id':row['id'],'error':str(exc)})
                    continue
            if results[key]['emotion'] not in CORE_EMOTIONS:
                raise ValueError('感情キャッシュのラベルが現在の分類仕様と一致しません')
            row['emotion'] = results[key]['emotion']
            row['reviewed'] = False
            project['stage'] = 2
            atomic_json(args.project, project)
            print('EMOTION_READY', row['id'], row['emotion'], flush=True)
        atomic_json(job/'emotion_errors.json', errors)
        if errors:
            raise RuntimeError('感情分類に失敗した発話があります。成功分は保存済みで、失敗をニュートラル成功扱いにはしません')


def synthesize(args, runtimes=None):
    os.environ['USE_TF'] = '0'
    repo = Path('/content/Irodori-TTS')
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    import importlib.metadata
    from huggingface_hub import hf_hub_download
    from .core import sampling_plan
    project = normalize_project(read_json(args.project))
    model = project['ttsModel']
    from .environments import MODEL_REVISIONS,IRODORI_COMMIT
    from .tts_dependencies import WATERMARK_REVISION,TOKENIZER_REVISIONS
    checkpoint = hf_hub_download(model, 'model.safetensors',revision=MODEL_REVISIONS[model])
    codec_repo='Aratako/Semantic-DACVAE-Japanese-32dim'
    codec=hf_hub_download(codec_repo,'weights.pth',revision=MODEL_REVISIONS[codec_repo])
    commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip()
    if commit!=IRODORI_COMMIT:raise RuntimeError('Irodoriのコードが検証済みの版と一致しません')
    engine = {'model':model,'checkpoint_sha256':file_hash(checkpoint),'irodori_commit':commit,
              'model_revision':MODEL_REVISIONS[model],'codec_revision':MODEL_REVISIONS[codec_repo],
              'watermark_expected_payload':'IRDTS',
              'watermark_model_revision':WATERMARK_REVISION,
              'tokenizer_revisions':TOKENIZER_REVISIONS,
              'watermark_loader_sha256':file_hash(Path(__file__).parent/'tts_dependencies.py'),
              'torch':importlib.metadata.version('torch'), 'worker_sha256':file_hash(__file__)}
    from .segmentation import prepare_with_mapping,expand_ids
    original=project
    project,mapping=prepare_with_mapping(project)
    if any(len(parts)>1 for parts in mapping.values()):atomic_json(Path(args.job)/'snapshots'/f'{time.time_ns()}_before_tts_split.json',{'project':original,'mapping':mapping})
    if args.ids:args.ids=','.join(expand_ids(args.ids.split(','),mapping))
    atomic_json(args.project,project)
    voices = dict(item.split('=',1) for item in args.voice)
    plan = sampling_plan(project, voices)
    for row in plan:
        row['fingerprint'] = digest({'request':row['fingerprint'], 'engine':engine})
    if args.ids and not any(r['id'] in args.ids.split(',') for r in plan):raise ValueError('指定範囲に読み上げる本文がありません')
    runtimes = runtimes if runtimes is not None else {}
    runtime_key = digest(engine)
    runtime = runtimes.get(runtime_key)
    if runtimes and runtime is None:
        raise RuntimeError('ロード済みIrodoriとモデルの構成が変わっています。解放後に再実行してください')
    if runtime is not None:
        print('PROGRESS ロード済みのIrodoriを再利用します', flush=True)
    def infer(request, destination):
        nonlocal runtime
        import numpy as np
        import soundfile as sf
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey, SamplingRequest
        missing = set(request)-set(inspect.signature(SamplingRequest).parameters)
        if missing:
            raise RuntimeError(f'SamplingRequestの仕様が異なります: {sorted(missing)}')
        if runtime is None:
            print('PROGRESS IrodoriをGPUへロードしています', flush=True)
            from .tts_dependencies import pinned_watermark_backend,pinned_text_tokenizers,require_watermark
            with pinned_watermark_backend(),pinned_text_tokenizers():
                runtime = InferenceRuntime.from_key(RuntimeKey(checkpoint=checkpoint, codec_repo=codec, model_device='cuda',
                    codec_device='cuda', model_precision='fp32', codec_precision='fp32'))
            require_watermark(runtime)
            runtimes[runtime_key] = runtime
            atomic_json(Path(args.job)/'irodori_memory_while_loaded.json', memory())
        result = runtime.synthesize(SamplingRequest(**request))
        from .tts_dependencies import require_watermark
        require_watermark(runtime,result)
        audio = result.audios[0].detach().cpu().float().view(-1).numpy()
        if not audio.size or not np.isfinite(audio).all():
            raise RuntimeError('空または非有限値の音声が生成されました')
        sf.write(str(destination), audio, int(result.sample_rate), subtype='PCM_16')
    manifest = generate(args.job, plan, project['pause'], infer,
        selected=[r['id'] for r in plan if r['id'] in args.ids.split(',')] if args.ids else None, regenerate=args.regenerate, provenance=engine)
    if manifest['status'] == 'failed':
        raise RuntimeError('音声生成に失敗した発話があります。job.jsonを確認してください')
    print('JOB_STATUS', manifest['status'], flush=True)


def main(argv=None, runtimes=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['gemma-scenario','qwen-scenario','gemma-readings','qwen-readings','qwen','emotions','synthesize','gemma','gemma-emotions'])
    parser.add_argument('--project', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--context', type=int, default=8192)
    parser.add_argument('--max-tokens', type=int, default=0)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--replace-analysis', action='store_true')
    parser.add_argument('--include-reviewed', action='store_true')
    parser.add_argument('--voice', action='append', default=[])
    parser.add_argument('--ids')
    parser.add_argument('--regenerate', action='store_true')
    parser.add_argument('--analyzer', choices=['gemma','qwen'], default='gemma')
    parser.add_argument('--scenario-emotion', choices=['on','off'], default='on')
    parser.add_argument('--structure', choices=['auto','prose','script'], default='auto')
    args = parser.parse_args(argv)
    profile=read_json(args.project).get('executionProfile')
    if profile:
        from .execution_profiles import normalize_profile,validate_gpu
        from .gemma_runtime import gpu_state
        gpu=gpu_state();validate_gpu(normalize_profile(profile)['gpu'],gpu['name'],gpu['total_mib'])

    Path(args.job).mkdir(parents=True, exist_ok=True)
    before = memory()
    atomic_json(Path(args.job)/f'{args.stage}_memory_before.json', before)
    code=None
    if args.stage.endswith('-scenario'):
        from .scenario_pipeline import run
        with job_lock(args.job):code=run(args)
    elif args.stage.endswith('-readings'):
        from .reading_stage import run
        with job_lock(args.job):run(args,analyzer='gemma' if args.stage.startswith('gemma') else 'qwen')
    elif args.stage.startswith('gemma'):
        from .gemma_stage import run
        with job_lock(args.job):run(args,'emotions' if args.stage=='gemma-emotions' else 'analyze')
    elif args.stage == 'qwen':
        with job_lock(args.job):
            qwen(args)
    elif args.stage == 'synthesize':
        synthesize(args, runtimes)
    else:
        globals()[args.stage](args)
    atomic_json(Path(args.job)/f'{args.stage}_memory_after_work.json', memory())
    return code


if __name__ == '__main__':
    raise SystemExit(main())
