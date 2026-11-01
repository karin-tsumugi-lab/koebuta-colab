import runpy,copy
from pathlib import Path
b=runpy.run_path(str(Path(__file__).with_name('test_force_length.py')));g=b['g'];reset=b['reset'];project=b['project'];segment=b['segment']
s=reset(project([segment(0,'あ'*79+'。'+'い'*90)]));s['length_max']=100;s['force_length']=True
g['preview_length_adjust']();g['apply_length_adjust'](True,0,50)
assert [len(x['text']) for x in s['project']['segments']]==[80,90]
s=reset(project([segment(0,'甲。',emotion='joy'),segment(1,'乙。',emotion='sad')]))
s['force_length']=True;preview=g['preview_length_adjust']()
assert '強制結合' in preview and '話者または感情が異なる' not in preview
s=reset(project([segment(0,'東京《とうきょう》',text_format='aozora')]))
df=g['render_table'](0,50)[0];r=g['set_length_limits'](8,80,0,50,df)
assert '短文 5字' in r[0].iloc[0]['長さの確認']
s=reset(project([segment(0,'あ'*200)]));s['force_length']=True;s['length_max']=100
old=copy.deepcopy(s['project']);g['preview_length_adjust']();g['apply_length_adjust'](True,0,50);g['split_single_row'](0,50,0,50)
assert all('強制処理' in g['review_status'](x) for x in s['project']['segments'])
g['pop_undo']();g['pop_undo']();assert s['project']==old
s=reset(project([segment(0,'甲。')]))
df=g['render_table'](0,50)[0];df.loc[0,'原文']='あ'*200
r=g['set_length_limits'](12,80,0,50,df)
assert '長文 200字' in r[0].iloc[0]['長さの確認'] and '短文 0件／長文 1件' in r[-1]
print('PASS: all five review findings, force/natural boundary, preview consistency, ruby count, provenance, Undo')
s=reset(project([segment(0,'甲。'),segment(1,'乙。')]))
s['project']['segments'][1].setdefault('_extras',{})['koebuta_edit']={'actions':['split'],'forced':True,'needs_review':True}
g['merge_row_with_next'](0,0,50)
assert '強制処理' in g['review_status'](s['project']['segments'][0])
print('PASS: merging retains forced provenance from second row')
