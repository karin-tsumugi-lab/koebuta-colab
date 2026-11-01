import runpy,copy
from pathlib import Path
b=runpy.run_path(str(Path(__file__).with_name('test_batch_fix.py')));g=b['g'];reset=b['b']['reset'];project=b['b']['project'];segment=b['b']['segment']
s=reset(project([segment(0,'東京《とうきょう》へ。'*20,text_format='aozora',tts_text='とうきょうへ。'*20)]));s['length_max']=80
old=copy.deepcopy(s['project']);assert not g['_propose_length_adjust'](s['project'],12,80)[1]
s['force_length']=True;g['preview_length_adjust']();r=g['apply_length_adjust'](True,0,50);assert '適用しました' in r[0],r[0]
assert len(s['project']['segments'])>1 and all('強制処理' in g['review_status'](x) for x in s['project']['segments'])
g['pop_undo']();assert s['project']==old
s=reset(project([segment(0,'甲。',emotion='joy',pause_after_ms=999),segment(1,'乙。',emotion='sad',acting_description='叫ぶ',tts_text='おつ。')]))
s['force_length']=True;g['preview_length_adjust']();r=g['apply_length_adjust'](True,0,50);assert '適用しました' in r[0],r[0]
x=s['project']['segments'][0];assert x['text']=='甲。乙。' and x['emotion']=='joy' and x['tts_text']=='甲。おつ。'
print('PASS: force checkbox, ruby/tts override, differing emotions and pauses, Undo')
