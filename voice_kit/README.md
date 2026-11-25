# Yomibuta（Drama-3）参照音声作成キット

Drama-3-Japanese で安定したクローン朗読を行うための**参照音声 WAV（44.1 kHz）**と、文字起こし（`transcript`）を自動転記した **`settings.json`** を作成するキットです。

## 1. プリセット一覧の確認
```bash
python3 voice_kit/yomibuta_voice_kit.py --list-presets
```

## 2. シード違いの候補 WAV を一括試作（Colab T4）
1 回のセッション上でバイナリとモデルを使い回して 5 パターンを連続生成します。
```bash
python3 voice_kit/yomibuta_voice_kit.py \
  --preset female_narrator \
  --seeds 101,202,303,404,505 \
  --out works/my_book/voice_try01 \
  --new --gpu T4
```

## 3. 気に入った声を本番用（`transcript` 自動設定済み）として採用
```bash
python3 voice_kit/yomibuta_voice_kit.py \
  --from-out works/my_book/voice_try01 \
  --adopt 303 \
  --save-to works/my_book/voices/narrator.wav \
  --write-settings works/my_book/settings.json
```
試聴セリフ（`--text`）が `settings.json` の `voices.narrator[0].transcript` へ自動転記されるため、そのまま `cli/yomibuta_generate.py` でクローン朗読を開始できます。
