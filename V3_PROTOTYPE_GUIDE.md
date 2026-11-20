# Koebuta v3 試作（自動ルビ選択・事前判定版）利用ガイド

> 当時の試作記録です。現行の制作と生成は [Koebuta v3 README](README.md) を参照してください。

## 概要
青空文庫・カクヨム（`|親《よみ》`）・pixiv（`[[rb:親 > よみ]]`）形式のルビ付き `tts_text`（または `text`）を入力とし、Colab GPU 上の `Irodori-TTS-v4.1-Small` テキストエンコーダ特徴量（`cos_cond`）を用いて **「読める漢字はそのまま維持し、誤読リスクの高い語だけを仮名へ展開する」** 試作版 CLI です。

- ホスト側（WSL / Linux）は **標準 Python のみ** で動作し、重い ML 計算はすべて Colab GPU 側で完結します。
- 閾値（`--ruby-threshold`, `--ruby-single-threshold`）は実行時に調整可能です。
- `--dry-run` 実行時は `--session` / `--job` / `--out` を省略できます。
- 交換形式は `schema_version: 1` です。各話者には `kind: "narrator"` または `"character"` が必須です（`settings.json` の `narratorEmotion` は既定で `true` ですが、明示的に `false` を指定した場合は `narrator` の感情タグが抑制されます）。

---

## 追加オプション（`cli/irodori_generate.py`）

| オプション | 既定値 | 説明 |
|---|---|---|
| `--ruby-mode` | `none` | `none`（従来通り）/ `original`（ルビ除去）/ `partial_kana`（全ルビ展開）/ `auto_select`（自動選択） |
| `--ruby-threshold` | `0.8327` | 複数トークン語の閾値（`cos_cond <= threshold` で仮名化） |
| `--ruby-single-threshold` | `0.65` | 1 トークン語の閾値（一般熟語の過剰仮名化を抑制） |
| `--ruby-device` | `auto` | `auto`（`auto_select` は Colab GPU、他はローカル）/ `remote` / `local` |
| `--ruby-preflight` | `False` | 音声生成を行わず、GPU でスコア判定と要確認語リスト（`ruby_review.json`）のみ回収 |

---

## AI エージェント向け推奨フロー（1回限定修正）

1. **事前判定（音声生成なし・ランタイム保持）**
   ```bash
   python3 cli/irodori_generate.py \
     --scenario scenario.json --settings settings.json \
     --session work-sess --job pre01 --out outputs/preflight \
     --ruby-preflight --new --gpu T4
   ```
   - `outputs/preflight/ruby_review.json` に、`kana` 判定となった語のみが前後文脈付きで出力されます。

2. **当該語のみ確認・1 パス修正**
   - `ruby_review.json` の `flagged_items` を確認し、当て字・旧仮名（例：`蒲団《ふとん》` → `布団`）や読みが揺れやすい語を **1 回限り** `tts_text` 上で調整します（`text` 原文・`source` は保持）。

3. **本生成（同一ランタイムを再利用して回収・停止）**
   ```bash
   python3 cli/irodori_generate.py \
     --scenario scenario_revised.json --settings settings.json \
     --session work-sess --job syn01 --out outputs/run01 \
     --skip-prepare --ruby-mode auto_select --stop-after-download
   ```
   - 事前判定でロード済みの GPU モデルをそのまま再利用するため、短時間で生成・回収・停止まで完了します。
