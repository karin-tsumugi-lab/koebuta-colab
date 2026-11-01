import copy
import runpy
from pathlib import Path

b=runpy.run_path(str(Path(__file__).with_name('test_review_fixes.py')))
g=b['g']; reset=b['reset']; project=b['project']; segment=b['segment']
for first_format in ('none','aozora'):
    s=reset(project([segment(0,'東',text_format=first_format),segment(1,'京《きょう》',text_format='aozora')]))
    old=copy.deepcopy(s['project'])
    result=g['merge_row_with_next'](0,0,50)
    assert len(s['project']['segments'])==1,result[0]
    merged=s['project']['segments'][0]
    assert merged['text']=='東京《きょう》'
    assert merged['tts_text']=='東きょう'
    g['pop_undo']()
    assert s['project']==old
s=reset(project([segment(0,'東京《とうきょう》',text_format='aozora'),segment(1,'へ。',text_format='aozora')]))
g['merge_row_with_next'](0,0,50)
x=s['project']['segments'][0]
assert g['reading'](x['text'],x['text_format'])[0]=='とうきょうへ。'
assert not x.get('tts_text')
print('PASS: manual merge preserves ruby readings across boundaries, unchanged readings, Undo')
