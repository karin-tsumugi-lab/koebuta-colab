import runpy,copy
from pathlib import Path
b=runpy.run_path(str(Path(__file__).with_name('test_koebuta_stability_v1.00.py')));g=b['g']
s=b['reset'](b['project']([b['segment'](0,'あ'*200)]));s['length_max']=80
frame=g['render_table'](0,50)[0];frame.loc[0,'感情（絵文字・名前）']='joy'
# Preview saves and normalizes; even the previous unnormalized browser input must not invalidate approval.
g['draft_guard'](g['preview_length_adjust'])(frame)
stamp=g['project_stamp']()
r=g['editor_ui'](g['apply_length_adjust'])(frame,True,0,50)
assert '適用しました' in r[0],r[0]
assert len(s['project']['segments'])>1
s=b['reset'](b['project']([b['segment'](0,'あ'*200)]));s['length_max']=80
frame=g['render_table'](0,50)[0];frame.loc[0,'感情（絵文字・名前）']='joy'
p=g['preview_length_ui'](frame)
assert '喜び' in p[1].iloc[0]['感情（絵文字・名前）'] and p[-1] is False
assert '適用しました' in g['editor_ui'](g['apply_length_adjust'])(p[1],True,0,50)[0]
s=b['reset'](b['project']([b['segment'](0,'甲。'),b['segment'](1,'乙。')]))
g['preview_length_adjust']();assert '適用しました' in g['apply_length_adjust'](True,0,50)[0]
assert s['project']['segments'][0]['text']=='甲。乙。'
print('PASS: preview/save/approval regression and source-optional merge')
