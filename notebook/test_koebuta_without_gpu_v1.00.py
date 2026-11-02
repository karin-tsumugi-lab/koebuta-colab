"""Koebuta v1.00 の非GPU回帰テスト。Gradio画面は構築するが公開しない。"""
import json,copy,io,nbformat,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np
import gradio as gr

NB = Path(__file__).resolve().parent / 'Koebuta_Colabv1.00.ipynb'
n = nbformat.read(NB,as_version=4)
g = {'MODEL_ID':'Aratako/Irodori-TTS-v4.1-Small', 'MODEL_REVISION':'test','CODEC_ID':'test','CODEC_REVISION':'test', 'IRODORI_DIR':Path('/not-installed')}
for idx in (4,6): exec(compile(n.cells[idx].source,f'cell{idx}','exec'),g)
with patch.object(gr.Blocks,'launch',lambda *args,**kwargs:None), patch('builtins.print'):
    exec(compile(n.cells[8].source,'cell8','exec'),g)
assert len(g['demo'].fns) > 20
source='第一行。\n\n第二行。'
sc={'schema_version':1,'source':source,'speakers':{
  'A':{'name':'同名','kind':'narrator','age':'adult','custom':{'future':1}},
  'B':{'name':'同名','kind':'character','pitch':'high'}},'segments':[
  {'id':'a#1','speaker_id':'A','text':'第一行。','emotion':'neutral','blank_lines_after':2,'extra':3},
  {'id':'a_1','speaker_id':'B','text':'第二行。','emotion':'joy','pause_after_ms':0}]}
p=g['normalize_scenario'](sc)
assert len(g['validate_project'](p))==0
output=g['export_scenario'](p)
assert output['speakers']['A']['custom']=={'future':1}
assert output['speakers']['A']['age']=='adult'
assert output['segments'][0]['extra']==3
assert g['resolve_pauses'](p,280)=={'a#1':1200,'a_1':0}
assert g['cache_path']('a#1','same') != g['cache_path']('a_1','same')
assert g['cache_path']('a#1','one') != g['cache_path']('a#1','two')

# 重複表示名でも変更しない
ctx=g['_CTX']; state=g['new_session'](); state2=g['new_session']()
token=ctx.set(state)
try:
    loaded=g['load_scenario_action'](None,json.dumps(sc,ensure_ascii=False),'cast')
    df,_,_=g['render_table'](0,50)
    status,*_=g['save_table_edits'](df,0,50)
    assert '反映' in status
    assert [r['role'] for r in state['project']['segments']] == ['A','B']
    role_updated=g['save_role_action']('B','B2','同名','character','','','')
    assert '保存' in role_updated[0]
    assert state['project']['segments'][1]['role']=='B2'
    assert state['project']['roles'][1]['id']=='B2'
    saved=Path(g['save_scenario_json']())
    assert saved.exists()
    rt=g['normalize_scenario'](json.loads(saved.read_text()))
    assert rt['segments'][1]['role']=='B2'
    assert rt['source']==source
finally:ctx.reset(token)
assert state2['project'] is None

# 原稿全文がある場合、発話間の原文改行も保持する
ctx=g['_CTX']
st=g['new_session']();tk=ctx.set(st)
try:
    same_speaker={'schema_version':1,'source':'一。\n\n二。',
         'speakers':{'n':{'name':'地の文','kind':'narrator'}},
         'segments':[{'id':'a','speaker_id':'n','text':'一。'},
                     {'id':'b','speaker_id':'n','text':'二。'}]}
    st['project']=g['normalize_scenario'](same_speaker)
    msg,*_=g['merge_row_with_next'](0,0,50)
    assert '結合しました' in msg, msg
    assert st['project']['segments'][0]['text']=='一。\n\n二。'
    assert not g['validate_project'](st['project'])
finally:ctx.reset(tk)

# 欠落・異常値を編集用に救済し、生成前に止める
raw={'schema_version':1,'speakers':{'n':{'kind':'narrator','name':'地の文'}},'segments':[
 {'id':'t1','speaker_id':'none','text':'おはよう','emotion':'unknown','pause_after_ms':-1},
 {'id':'t1','speaker_id':'n','emotion':'joy'},
 {'id':'sep','segment_type':'separator','text':'***'}]}
partial=g['normalize_scenario'](raw)
assert partial['source'] is None
assert partial['segments'][0]['emotion']=='neutral'
assert 'pause_after_ms' not in partial['segments'][0]
assert partial['segments'][1]['_pending_id'] is True
assert len(g['validate_project'](partial)) >= 3
try:g['require_ready'](partial)
except ValueError: pass
else:raise AssertionError('生成前の保留チェックが失敗')

# 原文結合では句読点・空白を勝手に補わない
small={'schema_version':1,'speakers':{'n':{'name':'地の文','kind':'narrator'}},'segments':[
 {'id':'a','speaker_id':'n','text':'一'}, {'id':'b','speaker_id':'n','text':'二'}]}
st=g['new_session']();tk=ctx.set(st)
try:
    st['project']=g['normalize_scenario'](small)
    msg,*_=g['merge_row_with_next'](0,0,50)
    assert '結合しました' in msg
    assert st['project']['segments'][0]['text']=='一二'
finally:ctx.reset(tk)

# 合成の一連の処理を偽の音声で検査（実際のGPUや外部モデルは使用しない）
voice_dir=Path('/content/koebuta_work/test_voice')
voice_dir.mkdir(parents=True,exist_ok=True)
voice=voice_dir/'fake.wav'
import uuid
voice.write_bytes(b'fake reference audio for key:' + uuid.uuid4().bytes)
raw2={'schema_version':1,'speakers':{'n':{'name':'地の文','kind':'narrator'}},'segments':[
 {'id':'hello','speaker_id':'n','text':'おはようございます。','emotion':'neutral'},
 {'id':'world','speaker_id':'n','text':'今日もよろしくお願いします。','emotion':'neutral'}]}
st=g['new_session']();tk=ctx.set(st)
try:
    st['project']=g['normalize_scenario'](raw2)
    st['project']['reading']='cast'
    st['voices']={'n':str(voice)}
    plan=g['build_plan'](st['project'],st['voices'],use_acting=False,use_emotion=False,
        narrator_emotion=False,seed=314,steps=40,global_pause_ms=280)
    assert len(plan)==2
    calls=[]
    def pretend_synthesize(unit,runtime):
        calls.append(unit['unit_id']);return np.ones(1600,dtype='float32')*0.01,16000
    g['load_runtime']=lambda *args,**kwargs: object()
    g['synthesize']=pretend_synthesize
    def progress(*args,**kwargs):pass
    result=list(g['run_master_generation'](False,False,False,314,40,0.28,progress=progress))[-1]
    assert '完了' in result[0], result
    assert len(calls)==2
    assert Path(result[1]).exists()
    assert len(st['last_files']) == 2
    zipfile=Path(g['download_segments_zip']())
    import zipfile as zf
    with zf.ZipFile(zipfile) as z:
        assert 'manifest.json' in z.namelist()
        manifest=json.loads(z.read('manifest.json'))
        assert {r['segment_id'] for r in manifest} == {'hello','world'}
    result2=list(g['run_master_generation'](False,False,False,314,40,0.28,progress=progress))[-1]
    assert 'キャッシュ利用: 2件' in result2[0]
    assert len(calls)==2, '全編再生成でキャッシュが使われません'
finally:ctx.reset(tk)

print('PASS: UI構築、JSON往復、同名話者、属性、異常値、セッション分離、結合、間、音声キャッシュ、ZIP')

# v1.00: Gradioのジェネレータが異なるContextで再開してもエラーにならない。
import contextvars
session=g['new_session']()
session['project']=g['normalize_scenario'](raw2)
session['project']['reading']='cast'
session['voices']={'n':str(voice)}
generator=g['session_generate'](session,False,False,False,314,40,0.28,progress=progress)
yields=[]
while True:
    # Gradioの進捗通知ごとに実行コンテキストが変わる状況を再現
    try:
        value=contextvars.Context().run(next,generator)
    except StopIteration:
        break
    yields.append(value)
assert len(yields)>=2
assert '完了' in yields[-1][0],yields
assert Path(yields[-1][1]).exists()
assert yields[-1][3] is session
assert len(session['last_files'])==2
assert ctx.get() is None, 'ContextVarがイベント後に漏れています'

# 長文を語の途中で強制分割し、極短い末尾を作っていた回帰を防ぐ。
fixture_path=NB.parent/'sakurano_kino_shitaniwa_koebuta.json'
if fixture_path.exists():
    source_json=json.loads(fixture_path.read_text(encoding='utf-8'))
else:
    # 配布パッケージには利用者の原稿を含めない。テスト用の人工長文で代替。
    source_json={'segments':[{'id':'t010','text':'あいうえお、'*30+'終わり。'}]}
for seg in source_json['segments']:
    txt=seg.get('text','')
    if not txt.strip():continue
    chunks=g['split_text'](txt,80)
    assert ''.join(chunks)==txt,seg['id']
long_text=next(x['text'] for x in source_json['segments'] if x['id']=='t010')
chunks=g['split_text'](long_text,80)
assert len(chunks)>=2
assert len(chunks[-1].strip())>=12, chunks
assert all('ちが'!=c[-2:] for c in chunks[:-1]),chunks

# README文とノート冒頭から重大な利用上の警告を消さない。
intro=n.cells[0].source
for phrase in ['Colab', '無料', 'Web UI', '倫理的', '電子透かし', '短い文章']:
    assert phrase in intro,phrase
print('PASS: v1.00 セッション再開・音声完成・文章分割・規約警告の回帰テスト')

# v1.00: 右カラムに必須設定が常時表示される。感情の絵文字表示とIDラウンドトリップ。
code=n.cells[8].source
assert code.index("with gr.Column(scale=3, min_width=280):\n            # 毎回確認する設定") < code.index("gr.Markdown('### 🎬 4. 朗読音声の生成')")
assert "with gr.Accordion('⚙️ 3. 音声生成の設定'" not in code
assert g['display_emotion']('joy').startswith('😆')
assert g['parse_emotion'](g['display_emotion']('joy'))=='joy'
assert g['parse_emotion']('joy')=='joy'
assert g['length_status']({'text':'こんにちは','emotion':'neutral'})[:1]=='🟥'

# 長い発話は通常入力で1単位になる範囲を確保。
assert g['split_text']('これは試し読みです。'*8,140)==['これは試し読みです。'*8]

# 長さの自動調整：明示的な指示、読み上げ文、改行を壊さない。
long='第一文はここにあります。第二文はその直後です。第三文はもう少し続きます。'
sc3={'schema_version':1,'source':long+'\n'+'甲。乙。'+'\n'+'題名\n著者',
     'speakers':{'n':{'kind':'narrator','name':'地の文'}},
     'segments':[{'id':'long','speaker_id':'n','text':long,'emotion':'neutral'},
                 {'id':'a','speaker_id':'n','text':'甲。','emotion':'neutral'},
                 {'id':'b','speaker_id':'n','text':'乙。','emotion':'neutral'},
                 {'id':'title','speaker_id':'n','text':'題名','emotion':'neutral'},
                 {'id':'author','speaker_id':'n','text':'著者','emotion':'neutral'}]}
p3=g['normalize_scenario'](sc3)
assert not g['validate_project'](p3)
proposed,steps,skips=g['_propose_length_adjust'](p3,5,32)
assert any('分割 long' in q for q in steps),steps
assert any('結合 a + b' in q for q in steps),steps
assert not any('結合 title + author' in q for q in steps),steps
assert proposed['source']==p3['source']
assert not g['validate_project'](proposed)
assert ''.join(s['text'] for s in proposed['segments'][:2])==long
assert g['export_scenario'](proposed)['source']==sc3['source']

# 選択的な除外：既存の読み上げ文は勝手に分割しない。
sc4={'schema_version':1,'speakers':{'n':{'kind':'narrator','name':'地の文'}},
     'segments':[{'id':'ruby','speaker_id':'n','text':long,'emotion':'neutral','tts_text':long.replace('第三','だいさん')} ]}
p4=g['normalize_scenario'](sc4)
assert not g['_propose_length_adjust'](p4,5,32)[1]

# プレビュー中は変更なし。明示的な適用後にUndoできる。
view=g['new_session']();tk=ctx.set(view)
try:
    view['project']=p3
    view['length_min']=5;view['length_max']=32
    previous=copy.deepcopy(view['project'])
    assert '提案できる' in g['preview_length_adjust']()
    assert view['project']==previous
    out=g['apply_length_adjust'](True,0,50)
    assert '適用しました' in out[0],out
    assert view['project']!=previous
    assert '戻しました' in g['pop_undo']()
    assert view['project']==previous
finally:ctx.reset(tk)
print('PASS: v1.00 常時表示、絵文字、警告、事前確認、分割・結合、Undo')

# v1.00: HFトークン入力を求めない。
for c in n.cells:
    assert 'HF_TOKEN' not in c.source, '不要なHFキー案内が残っている'

# ユーザーの実際の台本で、44/45/46番目付近（画面は0始まり）を手動結合できる。
if fixture_path.exists():
    original=json.loads(fixture_path.read_text(encoding='utf-8'))
    for idx in [44,45]:
        st=g['new_session']();tk=ctx.set(st)
        try:
            st['project']=g['normalize_scenario'](original)
            original_source=st['project']['source']
            a=st['project']['segments'][idx]
            b=st['project']['segments'][idx+1]
            result=g['merge_row_with_next'](idx,0,50)
            assert '結合しました' in result[0],(idx,result[0])
            assert st['project']['segments'][idx]['text'].startswith(a['text'])
            assert st['project']['segments'][idx]['text'].endswith(b['text'])
            assert len(st['project']['segments'])==53
            assert st['project']['source']==original_source
            assert g['validate_project'](st['project']) == [],(idx,g['validate_project'](st['project']))
            assert '戻しました' in g['pop_undo']()
            assert len(st['project']['segments'])==54
        finally:ctx.reset(tk)

# 手動分割は感情と演技を両方へ引き継ぎ、間だけ後半に移す。
sc5={'schema_version':1,'source':'なぜだろう。それは謎だ。',
     'speakers':{'n':{'name':'地の文','kind':'narrator'}},
     'segments':[{'id':'first','speaker_id':'n','text':'なぜだろう。それは謎だ。',
                  'emotion':'tension','acting_description':'静かに','pause_after_ms':1200}]}
st=g['new_session']();tk=ctx.set(st)
try:
    st['project']=g['normalize_scenario'](sc5)
    output=g['split_single_row'](0,None,0,50)
    assert '分割しました' in output[0],output
    segs=st['project']['segments']
    assert len(segs)==2
    assert segs[0]['text']+segs[1]['text']==sc5['source']
    assert all(s['emotion']=='tension' and s['acting']=='静かに' for s in segs)
    assert 'pause_after_ms' not in segs[0] and segs[1]['pause_after_ms']==1200
    assert g['validate_project'](st['project'])==[]
    assert '戻しました' in g['pop_undo']()
    assert len(st['project']['segments'])==1
finally:ctx.reset(tk)

# 読み上げ文が原文と異なる場合は安全に拒否。
sc5['segments'][0]['tts_text']='なぜだろう。それはなぞだ。'
st=g['new_session']();tk=ctx.set(st)
try:
    st['project']=g['normalize_scenario'](sc5)
    result=g['split_single_row'](0,None,0,50)
    assert '分割できません' in result[0],result[0]
    assert len(st['project']['segments'])==1
finally:ctx.reset(tk)

# 一括調整を未確認では実行できない。
st=g['new_session']();tk=ctx.set(st)
try:
    st['project']=p3;st['length_min']=5;st['length_max']=32
    old=copy.deepcopy(p3)
    result=g['apply_length_adjust'](False,0,50)
    assert '変更していません' in result[0]
    assert st['project']==old
finally:ctx.reset(tk)

# UI: 分割ボタンは「次の発話と結合」より下、事前確認のある一括適用ボタンがある。
code=n.cells[8].source
assert code.index("merge_btn = gr.Button") < code.index("split_btn = gr.Button")
assert 'length_confirm = gr.Checkbox' in code
assert '警告対象を一括で分割・結合' in code
print('PASS: 手動分割・属性継承・一括確認ゲート')
print(('PASS: 実作品45行付近の結合' if fixture_path.exists() else 'SKIP: 実作品45行付近の結合（fixture未同梱）。人工fixtureは別途必須検証。'))

