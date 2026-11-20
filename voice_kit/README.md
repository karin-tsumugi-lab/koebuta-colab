# Koebuta v3 参照音声作成キット（声づくりガイド）

本編をクローン音声（`voiceMode: "clone"`）で安定して朗読させるための**参照音声WAV**と**生成設定JSON（`settings.json`）**を、AIとの対話とCLIで簡単に作成するキットです。

「声の説明文（Caption）をどう書けばいいかわからない」という方でも、**AIと2〜3往復会話して、生成された5つのサンプル音声から好きな声を選ぶだけ**で理想の参照音声WAVを作れます。

---

## 全体の流れ（3ステップ）

```text
Step 1: AIと対話して「声のイメージ」と「試聴セリフ」を決める（または定番カタログから選ぶ）
  ↓
Step 2: 1コマンドでシード違いのサンプル音声を5パターン生成する（candidate_01_seed101.wav ...）
  ↓
Step 3: 聴き比べて一番好きなWAVを works/my_book/voices/narrator.wav に採用し、settings.json を書き出す
```

---

## Step 1：AIと対話して声のイメージを決める

[対話型・声づくりプロンプト（`VOICE_PROMPT.md`）](VOICE_PROMPT.md) を使います。

- **ChatGPT / Gemini などのチャットAIを使う場合**：`VOICE_PROMPT.md` の依頼文をコピーしてAIに貼り付けてください。
- **Claude Code / Codex などのエージェントを使う場合**：「`voice_kit/VOICE_PROMPT.md` に従って声を作りたい」と伝えてください。

AIが次の手順でリードしてくれます。
1. **原稿から登場人物に合う声を逆提案**するか、あなたの**ざっくりした一言（「落ち着いたお姉さん」「渋い執事」など）**を聞きます。
2. **「年齢感・高さ」「声質・響き」「話し方・距離感」の3点**を選択肢で確認し、Irodori-TTSに最適な「声の説明文（`--caption`）」へ自動翻訳します。
3. クローン元に適した **50〜70文字の試聴セリフ（`--text`）** と、Step 2の実行コマンドを作ってくれます。

### 定番ボイスカタログ（12種）からすぐ始める場合

対話を省略して定番の声から試したい場合は、同梱のプリセット（12種）をそのまま使えます。一覧は以下のコマンドで確認できます。

```bash
python3 voice_kit/irodori_voice_kit.py --list-presets
```

主なプリセット：`female_narrator`（落ち着いた女性ナレーター）、`male_narrator`（深みのある男性ナレーター）、`bright_heroine`（明るく清楚な若い女性）、`gentle_girl`（穏やかで柔らかい少女）、`whisper_sister`（包容力のあるお姉さん）、`cool_youth`（クールで知的な青年）、`energetic_boy`（元気な少年）、`veteran_butler`（渋い老紳士・執事）ほか。

---

## Step 2：シード違いのサンプル音声を一括生成する

同じ声の説明文でも、シード値（`seed`）によって声の個体差が変わります。`irodori_voice_kit.py` を使うと、**1回のコマンドで同一Colabセッションを連続再利用し、5パターンのWAVを1つのフォルダーに並べて出力**します。

### 実行例A：AIと決めた説明文と試聴セリフで作る

```bash
# まず dry-run で設定を確認（GPU不使用）
python3 voice_kit/irodori_voice_kit.py \
  --caption "落ち着いた明瞭な声の成人女性。やや低めで、ゆったりと丁寧に話す。穏やかで耳に近い距離感。" \
  --text "窓の外では静かに雨が降り続いていた。「ねえ、これからどこへ向かうつもりなの？」落ち着いた声が、静かな部屋に柔らかく響く。" \
  --seeds 101,202,303,404,505 \
  --dry-run

# Colab GPUで5パターンを一括生成（完了後にランタイム自動停止）
python3 voice_kit/irodori_voice_kit.py \
  --caption "落ち着いた明瞭な声の成人女性。やや低めで、ゆったりと丁寧に話す。穏やかで耳に近い距離感。" \
  --text "窓の外では静かに雨が降り続いていた。「ねえ、これからどこへ向かうつもりなの？」落ち着いた声が、静かな部屋に柔らかく響く。" \
  --seeds 101,202,303,404,505 \
  --out outputs/voice_try01 \
  --new --gpu T4
```

### 実行例B：定番プリセットから作る

```bash
python3 voice_kit/irodori_voice_kit.py \
  --preset female_narrator \
  --seeds 101,202,303,404,505 \
  --out outputs/voice_try01 \
  --new --gpu T4
```

### 生成されるファイル

`outputs/voice_try01/` 直下に、聴き比べやすい名前で5つのWAVが並びます。

```text
outputs/voice_try01/
├── candidate_01_seed101.wav
├── candidate_02_seed202.wav
├── candidate_03_seed303.wav
├── candidate_04_seed404.wav
├── candidate_05_seed505.wav
└── candidates.json          # 生成条件とシードの記録
```

### 同じセッションのまま別シードや別キャプションを追加試作する場合

1回目の生成に `--keep-session` を付けると、同じセッションで追加試作できます。再試作には `--skip-prepare` と新しい `--out` を指定し、各回で異なる短い英数字の `--job-prefix`（例：`try02`）を付けてください。日本語名や別フォルダーの同じ末尾名からは同じジョブIDが作られることがあります。

```bash
# 1回目：セッションを保持して生成（--keep-session）
python3 voice_kit/irodori_voice_kit.py \
  --preset female_narrator \
  --seeds 101,202,303 \
  --out outputs/voice_try01 \
  --new --gpu T4 --keep-session

# 2回目：説明文を微調整し、新しい --out（と --job-prefix）で同じセッションを再利用（完了後に自動停止）
python3 voice_kit/irodori_voice_kit.py \
  --caption "落ち着いた明瞭な声の成人女性。少し高めで柔らかく、ゆったりと丁寧に話す。" \
  --seeds 101,202,303 \
  --out outputs/voice_try02 \
  --job-prefix try02 \
  --skip-prepare
```

---

## Step 3：気に入った声を本番用（`works/my_book/`）に採用する

5つのWAVを聴き比べて気に入ったシード（例：`303`）が決まったら、`--adopt` コマンドで作品フォルダーの `voices/` へコピーし、同時に本番用の `settings.json` を書き出します。

```bash
python3 voice_kit/irodori_voice_kit.py \
  --from-out outputs/voice_try01 \
  --adopt 303 \
  --save-to works/my_book/voices/narrator.wav \
  --write-settings works/my_book/settings.json
```

- `works/my_book/voices/narrator.wav`（採用した参照音声WAV）
- `works/my_book/voices/narrator.voice_meta.json`（採用したシードと声質説明の控え）
- `works/my_book/settings.json`（`"voices": {"voice_a": "voices/narrator.wav"}` が設定済みの生成設定JSON）

※ 既存の `narrator.wav` や `settings.json` がある場合は上書き防止のためエラーになります。意図して上書きする場合は `--overwrite` を追加してください。

これで声と `settings.json` の準備は完了です！あとは [総合READMEのステップ1（原稿を `works/my_book/scenario.json` にする）](../README.md) へ進み、そのまま本編を生成できます。
