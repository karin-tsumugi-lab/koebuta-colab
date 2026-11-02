"""v1.4レビュー再現条件とv1.00自動分割を検証。GPU・公開サーバー不要。"""
import copy,json,runpy,types,asyncio,contextlib,io
from pathlib import Path
from unittest.mock import patch
base=runpy.run_path(str(Path(__file__).with_name('test_koebuta_without_gpu_v1.00.py')))
g=base['g'];ctx=g['_CTX']
def segment(i,text,**kw):return {'id':str(i),'speaker_id':'a','text':text,**kw}
def project(segs,source=None):
    raw={'schema_version':1,'speakers':{'a':{'name':'A','kind':'narrator','voice_caption':'声','acting_description':'演技'}},'segments':segs}
    if source is not None:raw['source']=source
    return g['normalize_scenario'](raw)
def reset(p):
    state=g['new_session']();state['project']=p;state['project']['reading']='cast';ctx.set(state);return state
# R1: page controls alone must not redirect data to another page.
s=reset(project([segment(0,'甲',tts_text='こう'),segment(1,'乙',pause_after_ms=999)]))
df,*_=g['render_table'](0,1);df.loc[0,'発話ID']='renamed'
r=g['save_table_edits'](df,1,1)
assert '反映' in r[0],r[0]
assert s['project']['segments'][0]['id']=='renamed'
assert s['project']['segments'][1]['text']=='乙' and s['project']['segments'][1]['pause_after_ms']==999
# R2/3: stale save rejected; undo restores reference map, sample, and whole project.
s=reset(project([segment(0,'甲。')]))
s['voices']={'a':'voice.wav'};s['sample']={'role_name':'a','path':'sample.wav'}
df,*_=g['render_table'](0,50);old=copy.deepcopy(s['project'])
g['save_role_action']('a','b','B','narrator','','声','演技')
r=g['save_table_edits'](df,0,50)
assert '保存できません' in r[0] and s['project']['segments'][0]['role']=='b'
g['pop_undo']();assert s['project']==old and s['voices']=={'a':'voice.wav'} and s['sample']['role_name']=='a'
# R4: invalid cell keeps all pending values; threshold change must do the same.
s=reset(project([segment(0,'元。')]))
df,*_=g['render_table'](0,50);df.loc[0,'原文']='変更した本文。';df.loc[0,'感情（絵文字・名前）']='typo'
r=g['save_table_edits'](df,0,50)
assert r[2].equals(df) and s['project']['segments'][0]['text']=='元。'
r=g['set_length_limits'](5,100,0,50,df)
assert r[0]['原文'].tolist()==df['原文'].tolist() and r[0]['感情（絵文字・名前）'].tolist()==['typo']
# R5: complete ruby tokens and graphemes are atomic. Readings must concatenate exactly.
for text,fmt,cut in [('東京《とうきょう》へ。','aozora',1),('｜東京《とうきょう》へ。','aozora',2),
                     ('東京(とうきょう)へ。','narou',1),('東京（とうきょう）へ。','narou',4),
                     ('[[rb:東京 > とうきょう]]へ。','pixiv',3),('《《重要》》です。','kakuyomu',3)]:
 s=reset(project([segment(0,text,text_format=fmt)]));before=copy.deepcopy(s['project'])
 r=g['split_single_row'](0,cut,0,50)
 assert '分割できません' in r[0] and s['project']==before,(text,r)
for text in ['か\u3099次','👩\u200d👩\u200d👧\u200d👦次','🇯🇵次','👍🏽次','1️⃣次']:
 import regex
 cluster=regex.match(r'\X',text).group()
 for k in range(1,len(cluster)):assert not g['_ruby_safe_offset'](text,k),(text,k)
# R7/8/9
s=reset(project([segment(0,'文。')]))
for _ in range(3):g['save_role_action']('a','a','A','narrator','',g['sample_caption_prefill']('a'),'演技')
assert s['project']['roles'][0]['caption']=='声'
s=reset(project([segment('sep',None,segment_type='separator'),segment('a','甲。'),segment('b','乙。')],source='甲。乙。'))
assert '結合しました' in g['merge_row_with_next'](1,0,50)[0]
s=reset(project([segment('sep',None,segment_type='separator',pause_after_ms=2000),segment('a','甲。'),segment('b','乙。')]))
assert g['resolve_pauses'](s['project'],280)=={'a':280,'b':280}
# Artificial row45 fixture always ships and exercises differing emotion/ruby-format paths.
segs=[segment(i,f'第{i}文。',emotion='joy' if i==45 else 'neutral',text_format='aozora' if i==45 else 'none') for i in range(47)]
s=reset(project(segs,source=''.join(x['text'] for x in segs)));before=copy.deepcopy(s['project'])
assert '結合しました' in g['merge_row_with_next'](45,0,50)[0]
assert s['project']['segments'][45]['text']=='第45文。第46文。'
g['pop_undo']();assert s['project']==before
# Auto split: punctuation preference, hard fallback, reading/source preservation and metadata roundtrip.
assert g['_split_choice']('あ'*18+'。'+'い'*21,20)[0]==19
assert g['_split_choice']('あ'*18+'、'+'い'*21,20)[0]==19
assert g['_split_choice']('あ'*18+'\n\n'+'い'*21,20)[0]==20
for fmt,text in [('none','あ'*281),('none','あ'*55+'、'+'い'*55+'。'+'う'*100),
                 ('aozora',('東京《とうきょう》へ行く。'*20)),('narou',('東京(とうきょう)へ行く。'*20)),
                 ('pixiv',('[[rb:東京 > とうきょう]]へ行く。'*20))]:
 s=reset(project([segment('long',text,text_format=fmt,emotion='joy',acting_description='静かに',pause_after_ms=1200)]))
 before=copy.deepcopy(s['project']);s['length_min']=12;s['length_max']=80
 g['preview_length_adjust']();r=g['apply_length_adjust'](True,0,50)
 assert '適用しました' in r[0],r[0]
 parts=s['project']['segments'];assert len(parts)>1
 assert ''.join(x['text'] for x in parts)==text
 assert ''.join(g['reading'](x['text'],fmt)[0] for x in parts)==g['reading'](text,fmt)[0]
 assert all(x['emotion']=='joy' and x['acting']=='静かに' for x in parts)
 assert all('pause_after_ms' not in x for x in parts[:-1]) and parts[-1]['pause_after_ms']==1200
 assert all('自動分割' in g['length_status'](x) and '要確認' in g['length_status'](x) for x in parts)
 if fmt=='none' and text=='あ'*281:assert all('自然な区切りなし' in g['length_status'](x) for x in parts)
 exported=g['export_scenario'](s['project']);loaded=g['normalize_scenario'](exported)
 assert all('要確認' in g['length_status'](x) for x in loaded['segments'])
 g['confirm_review'](0,0,50);assert '確認済み' in g['length_status'](parts[0])
 g['pop_undo']();assert '要確認' in g['length_status'](s['project']['segments'][0])
 g['pop_undo']();assert s['project']==before
# Automatic merge marker persists when length warning is gone.
s=reset(project([segment(0,'あいうえ。'),segment(1,'かきくけ。')],source='あいうえ。かきくけ。'))
s['length_min']=8;s['length_max']=80;g['preview_length_adjust']();g['apply_length_adjust'](True,0,50)
assert len(s['project']['segments'])==1 and '自動結合・要確認' in g['length_status'](s['project']['segments'][0])
assert '短文' not in g['length_status'](s['project']['segments'][0])
# Approval is invalid after changing thresholds until preview is regenerated.
g['preview_length_adjust']();s['length_max']=90
assert '再確認' in g['apply_length_adjust'](True,0,50)[0]
# R6 generation cannot register or display results after switching works.
s=reset(project([segment('old','旧作品。')]))
voice=base['voice'];s['voices']={'a':str(voice)}
it=g['run_master_generation'](False,False,False,314,40,0.28,progress=lambda *a,**kw:None)
next(it)
g['load_scenario_action'](None,json.dumps({'schema_version':1,'speakers':{'a':{'name':'A','kind':'narrator'}},'segments':[segment('new','新作品。')]}),'cast')
r=list(it)[-1]
assert r[1] is None and r[2] is None and s['last_files']==[] and s['project']['segments'][0]['id']=='new'
# UI wrapper output arity and transaction state. Save validation failure must not redraw.
s=reset(project([segment(0,'元。')]))
df,*_=g['render_table'](0,50);df.loc[0,'原文']='変更。'
r=g['editor_ui'](g['save_role_action'])(df,'a','b','B','narrator','','声','演技')
assert len(r)==24 and r[2].iloc[0]['話者ID']=='b' and r[2].iloc[0]['原文']=='変更。'
r=g['editor_ui'](g['undo_action'])(r[2],0,50)
assert r[2].iloc[0]['話者ID']=='a' and r[8]=='声'
# Gradio preprocessing/postprocessing: actual event callbacks via process_api, no network/server.
ctx.set(None)
from gradio.state_holder import SessionState
import gradio as gr
async def check_api():
 demo=g['demo'];state=SessionState(demo)
 def find(name):return next(k for k,v in demo.fns.items() if v.fn and v.fn.__name__==name)
 def table_data(df):return {'headers':list(df.columns),'data':df.fillna('').values.tolist(),'metadata':None}
 raw={'schema_version':1,'speakers':{'a':{'name':'A','kind':'narrator'}},'segments':[segment(0,'前半です。後半です。')]}
 load=find('session_editor_load_scenario_action')
 out=await demo.process_api(load,[None,{'headers':g['EDIT_COLUMNS'],'data':[]},None,json.dumps(raw),'cast'],state=state)
 assert len(out['data'])==25
 session=state[g['session_store']._id];token=ctx.set(session)
 try:df=g['render_table'](0,50)[0]
 finally:ctx.reset(token)
 split=find('session_editor_split_single_row')
 out=await demo.process_api(split,[None,table_data(df),0,None,0,50],state=state)
 assert len(out['data'])==25 and len(session['project']['segments'])==2
 assert all('要確認' in g['review_status'](x) for x in session['project']['segments'])
 undo=find('session_editor_undo_action')
 token=ctx.set(session)
 try:df=g['render_table'](0,50)[0]
 finally:ctx.reset(token)
 await demo.process_api(undo,[None,table_data(df),0,50],state=state)
 assert len(session['project']['segments'])==1
 # all state-changing events and generation share the explicit queue identifier.
 assert all(fn.concurrency_id=='koebuta_studio' for fn in demo.fns.values())
asyncio.run(check_api())
print('PASS: R1–R9、人工45行fixture、自然分割/フォールバック、ルビ・絵文字保全、要確認とJSON往復、Undo、Gradio API配線')

