"""Stage-specific, versioned runtime contracts. No imports of ML packages."""
import os
import json
import subprocess
from pathlib import Path
from .core import digest, file_hash, read_json

PYTHON_VERSION='3.10.22'
UV_VERSION='0.13.5'
IRODORI_COMMIT='59be938c99d48b5653ca5aa3fdd0cddaa56940e5'
IRODORI_FILES={'pyproject.toml':'a67e3494530cd9c29817507c67a496bb299a9a81e2edd4df6ffb80cf330dae71',
               'uv.lock':'8175adbb9ad7ae77d1f048344343a63876e57c333b659314bcc054230b5b3e6c'}
MODEL_REVISIONS={
    'Aratako/Irodori-TTS-v4.1-Small':'2b28324dc263ed5e6638b3cf3dd94c82ead07b4b',
    'Aratako/Irodori-TTS-v4-Large':'2e0c55428ce97268a507f1feeb2478f8d9148e8b',
    'Aratako/Semantic-DACVAE-Japanese-32dim':'47376ee24834d7a05a48ebabfe3cde29b3c5e214',
    'Qwen/Qwen3-8B-GGUF':'7c41481f57cb95916b40956ab2f0b139b296d974',
    'convaiinnovations/laya-multilingual':'1720e3e3357cfe1e281542e223f8273b0890ca34',
}
ENGINES=('gemma','qwen','laya','tts')


def root():return Path(os.environ.get('YOMIBUTA_RUNTIME_ROOT','/content'))
def marker_path():return root()/'yomibuta_environment.json'
def canonical(engine):return 'llm' if engine in ('gemma','qwen','llm') else engine
def python_path(engine):
    engine=canonical(engine)
    if engine=='tts':return root()/'Irodori-TTS/.venv/bin/python'
    if engine not in ('llm','laya'):raise ValueError('未対応の準備対象です')
    return root()/f'yomibuta_{engine}_env/bin/python'


def signature(engine):
    engine=canonical(engine)
    if engine not in ('llm','laya','tts'):raise ValueError('未対応の準備対象です')
    source=IRODORI_FILES if engine=='tts' else file_hash(Path(__file__).parent/'requirements'/f'{engine}.lock')
    return digest({'engine':engine,'python':PYTHON_VERSION,'uv':UV_VERSION,'requirements':source,
                   'irodori':IRODORI_COMMIT if engine=='tts' else None,'contract':1})


def snapshot(python):
    code="import sys,json,importlib.metadata as m; print(json.dumps({'python':sys.version.split()[0],'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))"
    return json.loads(subprocess.check_output([str(python),'-c',code],text=True,timeout=30))


def ready(engine,marker=None,verify=False):
    if marker is None:marker=read_json(marker_path()) if marker_path().is_file() else {}
    record=marker.get('capabilities',{}).get(canonical(engine),{})
    valid=record.get('signature')==signature(engine) and python_path(engine).is_file()
    if valid and verify:
        try:
            actual=snapshot(python_path(engine))
            valid=actual['python']==record.get('python')==PYTHON_VERSION and actual['packages']==record.get('packages')
        except (OSError,ValueError,subprocess.SubprocessError):return False
    return valid


def executable(engine):
    override=os.environ.get('YOMIBUTA_'+engine.upper()+'_PYTHON')
    if override:
        if not Path(override).is_file():raise ValueError('指定された実行環境が見つかりません')
        return override
    if not ready(engine,verify=True):raise ValueError(f'{engine}: この工程のライブラリを準備してください（版の未確認・変更を検出しました）')
    return str(python_path(engine))
