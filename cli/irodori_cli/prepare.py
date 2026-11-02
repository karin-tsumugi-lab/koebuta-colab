"""Prepare only the requested stage, using immutable dependency contracts."""
import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path
from .core import atomic_json, file_hash
from . import environments as env


def run(command,cwd=None):
    subprocess.run([str(v) for v in command],cwd=cwd,check=True)


def snapshot(python):
    return env.snapshot(python)


def bootstrap():
    target=env.root()/'yomibuta_tools';binary=target/'bin/uv'
    if binary.is_file():
        version=subprocess.check_output([str(binary),'--version'],text=True).split()[1]
        if version!=env.UV_VERSION:raise RuntimeError('準備ツールの版が異なります。新しいランタイムを使用してください')
        return binary
    target.mkdir(exist_ok=True)
    run([sys.executable,'-m','pip','install','--no-deps','--target',target,f'uv=={env.UV_VERSION}'])
    if not binary.is_file():raise RuntimeError('準備ツールを確認できません')
    return binary


def tts_repository():
    repo=env.root()/'Irodori-TTS'
    if not repo.exists():
        repo.mkdir();run(['git','init',repo])
        run(['git','remote','add','origin','https://github.com/Aratako/Irodori-TTS.git'],repo)
        run(['git','fetch','--depth','1','origin',env.IRODORI_COMMIT],repo)
        run(['git','checkout','--detach','FETCH_HEAD'],repo)
    if not (repo/'.git').is_dir():raise RuntimeError('既存のIrodoriフォルダーを上書きしません。別のランタイムを使用してください')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    dirty=subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
    if sha!=env.IRODORI_COMMIT or dirty:
        raise RuntimeError('既存のIrodoriに変更または版の違いがあります。上書きせず停止しました。新しいランタイムを使用してください')
    for name,checksum in env.IRODORI_FILES.items():
        if file_hash(repo/name)!=checksum:raise RuntimeError('Irodoriの依存定義が検証済みの版と一致しません')
    return repo


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',choices=[*env.ENGINES,'all'])
    parser.add_argument('--qwen',action='store_true');parser.add_argument('--gemma',action='store_true')
    args=parser.parse_args(argv)
    engines=[args.engine] if args.engine and args.engine!='all' else ['tts','laya']
    if args.engine=='all' or args.qwen or args.gemma:engines+=['gemma']
    engines=list(dict.fromkeys(env.canonical(e) for e in engines))
    marker=env.marker_path();previous=json.loads(marker.read_text()) if marker.exists() else {}
    state={'id':previous.get('id') or uuid.uuid4().hex,'schema':2,'capabilities':dict(previous.get('capabilities',{}))}
    uv=None
    for engine in engines:
        if env.ready(engine,state,verify=True):
            print(f'PROGRESS {engine}: 検証済みの準備を再利用します',flush=True);continue
        # Never modify libraries beneath a live inference process.
        from .resident import unload
        unload()
        state['capabilities'].pop(engine,None)
        state['prepared']=any(env.ready(e,state) for e in ('llm','laya','tts'));atomic_json(marker,state)
        print(f'PROGRESS {engine}: この工程のライブラリだけを準備中。モデル本体は読み込みません',flush=True)
        if uv is None:uv=bootstrap()
        if engine=='tts':
            repo=tts_repository()
            run([uv,'sync','--locked','--no-dev','--extra','cu128','--python',env.PYTHON_VERSION],repo)
            for name,checksum in env.IRODORI_FILES.items():
                if file_hash(repo/name)!=checksum:raise RuntimeError('環境構築が依存定義を変更しました')
        else:
            python=env.python_path(engine)
            if not python.is_file():run([uv,'venv','--python',env.PYTHON_VERSION,python.parent.parent])
            lock=Path(__file__).parent/'requirements'/f'{engine}.lock'
            run([uv,'pip','sync','--python',python,'--require-hashes','--only-binary',':all:',
                 '--index-strategy','unsafe-best-match',lock])
        versions=snapshot(env.python_path(engine))
        if versions['python']!=env.PYTHON_VERSION:raise RuntimeError('Pythonの版が指定と一致しません')
        state['capabilities'][engine]={'signature':env.signature(engine),**versions}
        state['prepared']=True;atomic_json(marker,state)
    state['prepared']=any(env.ready(e,state) for e in ('llm','laya','tts'));atomic_json(marker,state)
    print(json.dumps({'prepared_engines':engines,'capabilities':list(state['capabilities'])}),flush=True)


if __name__=='__main__':main()
