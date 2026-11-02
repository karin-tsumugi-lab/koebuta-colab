"""Use the tested SilentCipher weights inside the pinned upstream runtime."""
from contextlib import contextmanager
from pathlib import Path
from .core import file_hash

WATERMARK_REPO='sony/silentcipher'
WATERMARK_REVISION='a1c4d021905e0dc5b24be5f68db5fc4dba410ee1'
TOKENIZER_REVISIONS={
    'sbintuitions/modernbert-ja-310m':'77675fc96a7e445e982e2ba90246b816efc74ec6',
    'google/t5gemma-2-1b-1b':'dd0a2683227859151b1730ca3a63087df5b5f39b',
}
WATERMARK_FILES={
    'enc_c.ckpt':'ff64f80d2391fdfc888e4103c499be4a2c958e59626587a1eab6db93204814c7',
    'dec_c.ckpt':'c23b57635172b2fbd3a8531d15ba76b5885a10d0fe902ccb823c521c56041b33',
    'dec_m_0.ckpt':'829540c058270d29788f05294894d45bf436e44add0e1099422242ebb94b7088',
    'hparams.yaml':'27735fd4db0c00c29fef7af872ad1e5efe854e48d530a86c75beac2b87f09ce3',
}


def require_watermark(runtime,result=None):
    if not runtime.watermarker.ready:
        raise RuntimeError('電子透かしを準備できませんでした。透かしなしの音声を保存せず停止します')
    if result is not None and not any(name=='silentcipher_watermark' for name,_ in result.stage_timings):
        raise RuntimeError('電子透かしの付与を確認できません。音声を保存せず停止します')


@contextmanager
def pinned_text_tokenizers():
    from irodori_tts.tokenizer import PretrainedTextTokenizer
    cls=PretrainedTextTokenizer
    descriptor=cls.__dict__['from_pretrained'];original=cls.from_pretrained
    def pinned(_cls,repo_id,**kwargs):
        if not kwargs.get('local_files_only'):
            revision=TOKENIZER_REVISIONS.get(repo_id)
            if revision is None:raise RuntimeError('未検証の音声用トークナイザーです。版を固定してから使用してください')
            kwargs['revision']=revision
        return original(repo_id,**kwargs)
    cls.from_pretrained=classmethod(pinned)
    try:yield
    finally:cls.from_pretrained=descriptor


@contextmanager
def pinned_watermark_backend():
    import silentcipher
    from huggingface_hub import hf_hub_download
    folder=None
    for name,checksum in WATERMARK_FILES.items():
        path=Path(hf_hub_download(WATERMARK_REPO,'44_1_khz/73999_iteration/'+name,revision=WATERMARK_REVISION))
        if file_hash(path)!=checksum:raise RuntimeError('電子透かし用のモデルが検証済みの内容と一致しません')
        folder=path.parent
    original=silentcipher.get_model
    # Upstream's fixed API exposes device/model_type, but not a weight revision.
    # This worker owns one runtime; restore the public loader immediately after construction.
    def pinned(*args,**kwargs):
        kwargs['ckpt_path']=str(folder);kwargs['config_path']=str(folder/'hparams.yaml')
        return original(*args,**kwargs)
    silentcipher.get_model=pinned
    try:yield
    finally:silentcipher.get_model=original
