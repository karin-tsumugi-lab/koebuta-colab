"""Same 15 emotion choices used by the validated notebook and Web UI."""
LABELS = ['ニュートラル。事実説明、淡々とした説明。','喜び・楽しさ。嬉しさ、陽気な興奮。',
          '怒り・苛立ち。不満、反発、抗議。','悲哀・絶望。悲しみ、落胆、絶望。',
          '優しさ・感謝。いたわり、慈愛、感謝。','からかい・悪戯っぽさ。皮肉、からかい。',
          '不安・懇願。不安、おずおずした発言、お願い。','焦り・動揺・緊張。慌てている、切迫している。',
          '驚き・感嘆。意外さ、驚き。','ため息・疲労・諦め。疲れ、呆れ、諦め。',
          '囁き・内緒話。秘密、小声、囁き。','含み笑い・忍び笑い。くすくす笑い、笑いをこらえる。',
          '恐怖・悲鳴。強い恐怖、危険への恐怖。','眠気・気だるさ。眠気や気だるさ。','勢い・気合・強調。強い決意、勢い。']
LEGACY_EMOTION_QUESTION = {'emotion':{'type':'choice', 'instructions':
    '次の日本語の発話を音声で表現する感情として分類します。特に強い感情を付けない場合は0を選び、複数の感情がある場合は最も目立つものを選んでください。',
    'criteria':{str(i):value for i,value in enumerate(LABELS)}}}

# Short enough to retain the complete instruction in Laya's classification head.
CORE_EMOTIONS = dict(zip(
    ['neutral','joy','anger','sad','kind','tease','anxiety','surprise','fear'],
    ['平静・普通の説明','嬉しい・楽しい','怒り・苛立ち','悲しい・落ち込む','優しい・感謝する',
     'からかう・皮肉','不安・お願い','驚く','怖い・悲鳴']))
EMOTION_QUESTION = {'emotion':{'type':'choice',
    'instructions':'発話している人の感情を一つ選びます。明確な感情がなければneutralです。',
    'criteria':CORE_EMOTIONS}}
