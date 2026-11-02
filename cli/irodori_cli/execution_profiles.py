"""Existing execution routes and evidence; no model imports or performance guesses."""
PROFILES={
 'T4':{'label':'T4 16GB','gemma':'12B','context_cap':8192},
 'A100':{'label':'A100 40GB','gemma':'26B-A4B','context_cap':65536},
 'G4':{'label':'G4 96GB','gemma':'26B-A4B','context_cap':131072},
}

def normalize_profile(value):
    if not isinstance(value,dict) or type(value.get('version')) is not int or value.get('version')!=1:raise ValueError('実行構成の形式が不正です')
    gpu=value.get('gpu','T4');analyzer=value.get('analyzer','gemma');emotion=value.get('emotionMethod','auto');context=value.get('context',0)
    if gpu not in PROFILES or analyzer not in ('gemma','qwen','gemini','import') or emotion not in ('auto','manual','gemma','laya','gemini'):raise ValueError('未対応の実行構成です')
    if type(context) is not int or context<0 or context and not 512<=context<=PROFILES[gpu]['context_cap']:raise ValueError('コンテキストサイズの設定が対象GPUの範囲外です')
    result={'version':1,'gpu':gpu,'analyzer':analyzer,'emotionMethod':emotion,'context':context}
    if 'emotionChoice' in value:
        if value['emotionChoice'] not in ('gemma','laya','gemini'):raise ValueError('自動感情判定モデルを確認してください')
        result['emotionChoice']=value['emotionChoice']
    if 'geminiModel' in value:
        from .gemini_models import validate_model
        result['geminiModel']=validate_model(value['geminiModel'])
    return result

def normalize_ui(value):
    if not isinstance(value,dict) or value.get('version')!=2 or value.get('page') not in ('environment','scenario','generation') or value.get('scenario') not in ('source','reading','cast','direction'):raise ValueError('画面位置の形式が不正です')
    return {k:value[k] for k in ('version','page','scenario')}

def validate_gpu(profile,name,total):
    if profile not in PROFILES:raise ValueError('未対応のGPU構成です')
    matched={'T4':'T4' in name and 14000<=total<=18000,
             'A100':'A100' in name and 38000<=total<=45000,
             'G4':'RTX PRO 6000' in name and 90000<=total<=102400}
    if not matched[profile]:raise ValueError(f'選択した{PROFILES[profile]["label"]}と実GPU（{name}、{total} MiB）が一致しません。実行環境で構成または接続先を確認してください')

def catalog():
    return {'profiles':[{'id':key,**value,'tts':[{'id':'Aratako/Irodori-TTS-v4.1-Small','label':'v4.1-Small','status':'既定・生成確認済み' if key!='G4' else '既定・短文生成確認済み'},
        {'id':'Aratako/Irodori-TTS-v4-Large','label':'v4-Large','status':{'A100':'生成・試聴確認済み','T4':'短文の文章指定で生成確認（VRAM余裕小）','G4':'短文生成確認済み（試聴待ち）'}[key]}],
        'qwen_verified':True,'gemma_verified':True} for key,value in PROFILES.items()],
        'evidence':'outputs/alpha_gpu_20261026/RESULTS.md; outputs/gemma_emotion_context_20261026/RESULTS.md; docs/GPU_ACCEPTANCE_RESULTS.md'}


def emotion_route(profile):
    p=normalize_profile(profile);method=p['emotionMethod']
    if method=='manual' or method=='auto' and p['analyzer']=='import':return None
    if method=='gemini' or method=='auto' and p['analyzer']=='gemini':return 'gemini'
    return 'gemma' if method=='gemma' or method=='auto' and p['analyzer']=='gemma' else 'qwen'


def validate_dispatch(profile,action,analyzer,engine):
    p=normalize_profile(profile);emotion=emotion_route(p)
    allowed={'tts'}
    if p['analyzer'] in ('gemma','qwen'):allowed.update(('gemma','qwen'))
    if emotion=='gemma':allowed.update(('gemma','qwen'))
    elif emotion=='qwen':allowed.add('laya')
    if action=='prepare' and engine not in allowed:raise ValueError('選択構成に不要なライブラリは準備しません')
    if action in ('scenario','analyze','readings') and (p['analyzer']=='import' or p['analyzer']!=analyzer):raise ValueError('選択した話者整理方法と実行要求が一致しません')
    if action=='emotions' and (not emotion or emotion!=analyzer):raise ValueError('選択した自動感情判定方法と実行要求が一致しません')
