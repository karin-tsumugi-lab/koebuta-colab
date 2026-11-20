# Koebuta v3 CLI 朗読生成ガイド

作成済みのシナリオJSON（`schema_version: 1`）を Google Colab GPU 上の Irodori-TTS で連続生成し、完成音声をローカルへ回収する公式CLI（`cli/irodori_generate.py`）の案内です。

> **Colabの利用規約を確認してください。**  
> 公式CLIの利用にもColabの規約が適用されます。無料・CU残高なしの管理ランタイムには追加制限があり、CLIは制限を回避する手段ではありません。有料でも一般の禁止事項・利用上限は残ります。認証・GPU生成の前に [Colab利用条件の注意](../docs/COLAB_USAGE.md) と公式資料を確認してください。

---

## 必要なもの

- WSL2 Ubuntu（確認済みは26.04）またはLinux
- Python 3.10以上（ホスト側は標準ライブラリのみで動作し、重いML計算はColab GPU側で実行されます）
- 認証済みの Colab CLI（確認済みは0.7.5）
- シナリオJSON（例：`works/my_book/scenario.json`）と生成設定JSON（例：`works/my_book/settings.json`）
- クローンを使用する場合は、利用権限のある参照音声WAV（ない場合は [参照音声作成キット](../voice_kit/README.md) で作成できます）

Windowsから起動する場合は `python3` を `python` に読み替えてください。以下のコマンド例はすべて**リポジトリのルートフォルダー**から実行する形式で統一しています。

---

## 1. Colab CLIの接続確認

Colab CLIのインストールと認証は、CLI本体の公式手順に従ってください。認証情報・Cookie・トークンを設定JSONやリポジトリへ書き込まないでください。

```bash
colab --help
colab sessions
```

※ Colab CLI 0.7.5 では `--version` オプションが未対応のため、版番号はパッケージ管理ツールの表示等で確認してください。

---

## 2. 生成設定JSON（`settings.json`）を用意する

シナリオJSONと同じ作品フォルダー（例：`works/my_book/`）に、声の割り当てやモデル条件を指定する `works/my_book/settings.json` を作成します。参照音声WAVの相対パスは **`settings.json` があるフォルダー（`works/my_book/`）を基準** に解決されます。

### パターンA：一人朗読（共通の参照WAVでクローン）

`voice_kit` で `--save-to works/my_book/voices/narrator.wav --write-settings works/my_book/settings.json` を実行した場合は、以下の形式で自動作成されます。

```json
{
  "title": "作品名",
  "voiceMode": "clone",
  "reading": "shared",
  "voices": {"voice_a": "voices/narrator.wav"},
  "baseCaption": "落ち着いた明瞭な日本語の朗読。",
  "acting": true,
  "emotion": true,
  "narratorEmotion": true,
  "ttsModel": "Aratako/Irodori-TTS-v4.1-Small",
  "seed": 314,
  "steps": 40,
  "pause": 0.28
}
```

### パターンB：複数人朗読（話者ごとに参照WAVを割り当て）

`reading` を `"cast"` にし、`speakerVoices`（話者ID → プロファイル名）と `voices`（プロファイル名 → WAVパス）を指定します。

```json
{
  "title": "作品名",
  "voiceMode": "clone",
  "reading": "cast",
  "speakerVoices": {
    "narrator": "narrator",
    "aoi": "aoi"
  },
  "voices": {
    "narrator": "voices/narrator.wav",
    "aoi": "voices/aoi.wav"
  },
  "baseCaption": "自然で聞き取りやすい日本語の朗読。",
  "acting": true,
  "emotion": true,
  "narratorEmotion": true,
  "ttsModel": "Aratako/Irodori-TTS-v4.1-Small",
  "seed": 314,
  "steps": 40,
  "pause": 0.28
}
```

### パターンC：参照WAVを使わず声の説明文（VoiceDesign）で生成

`voiceMode` を `"design"` にします。`reading: "shared"` では `baseCaption` が、`reading: "cast"` では各話者の `voice_caption` が使用されます。事前に [参照音声作成キット](../voice_kit/README.md) で気に入ったシードのWAVを1本作ってからクローン（パターンA/B）で本編を生成すると、長編でも声質を揃えやすくなります。

### 主な設定キーと既定値

| キー | 既定値 | 説明 |
|---|---|---|
| `reading` | `"shared"` | `"shared"`（全員共通の声）または `"cast"`（話者別の声） |
| `voiceMode` | `"design"` | `"clone"`（参照WAVを使用）または `"design"`（説明文から生成） |
| `baseCaption` | `"自然で聞き取りやすい日本語の朗読。"` | ベースとなる声質・朗読スタイルの説明文 |
| `acting` | `true` | 話者・発話の `acting_description`（演技指示）をCaptionへ反映する |
| `emotion` | `true` | 発話の `emotion`（感情絵文字タグ）を反映する |
| `narratorEmotion` | `true` | `kind: "narrator"`（地の文・語り手）にも感情タグを反映する |
| `ttsModel` | `"Aratako/Irodori-TTS-v4.1-Small"` | 使用するTTSモデル |
| `seed` | `314` | 乱数シード（0〜2147483647） |
| `steps` | `40` | 生成ステップ数（`20` / `40` / `60`） |
| `pause` | `0.28` | 発話間の基本休止秒数（0〜10秒。個別の `pause_after_ms` がない箇所に適用） |

---

## 3. `--dry-run` で事前検査する（GPU不使用）

Colabに接続する前に、必ずローカルで `--dry-run` を実行して構文・話者・参照WAVの存在・解決後の読みを確認します。`--dry-run` 時は `--session` / `--job` / `--out` を省略できます。

```bash
python3 cli/irodori_generate.py \
  --scenario works/my_book/scenario.json \
  --settings works/my_book/settings.json \
  --dry-run
```

- 成功すると標準出力に生成計画のJSONが出力されます。
- 原文にある作者ルビや、手動確定（`selection: "kana"` / `"surface"`）の追加ルビは解決済みの形で `requests` に表示されます。
- 自動判定待ち（`selection: "auto"`）の追加ルビがある場合は、`ruby_pending` に候補一覧が表示されます。

---

## 4. ルビの解決規則と事前判定（`--ruby-preflight`）

### v3におけるルビの扱い

Koebuta v3のシナリオ（作者ルビや `koebuta_added_ruby` を含む発話）では、ルビの由来に応じて次のとおり解決されます。

1. **原文にある作者ルビ（および `tts_text` に青空文庫形式で補記された必須ルビ）**:  
   `--ruby-mode` の指定にかかわらず、**常に指定された読みへ展開**されます。
2. **追加ルビ（`koebuta_added_ruby`）の手動確定分**:  
   `selection: "kana"` は常に仮名へ展開され、`selection: "surface"` は常に元表記（漢字等）のまま維持されます。スコア判定で覆ることはありません。
3. **追加ルビ（`koebuta_added_ruby`）の自動判定分（`selection: "auto"`）**:  
   発話に `selection: "auto"` が含まれる場合、既定で **`--ruby-mode auto_select`** が選ばれ、Colab GPU上のテキストエンコーダ特徴量の類似度スコア（`cos_cond`）と閾値（複数トークン語 `0.8327`、1トークン語 `0.65`）によって機械判定されます（`cos_cond <= 閾値` の候補を仮名へ展開、それ以外は元表記を維持）。  
   ※ スコア判定は特徴量の類似度に基づく機械的な選択であり、同音異義語や文脈上の誤読をすべて自動判別するものではありません。固有名詞・当て字・確実に読ませたい語は、エディタまたはJSON上で手動確定（`"kana"` または `"surface"`）してください。

### ルビ関連オプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--ruby-mode` | 自動（`auto`候補があれば `auto_select`、なければ `none`） | v3シナリオでは `auto_select` 時に `selection: "auto"` のスコア判定を有効にします（`none` 指定時は `auto` 候補を元表記のまま維持します）。※ `original`（インラインルビの親文字維持）および `partial_kana`（インラインルビの全展開）は、`koebuta_added_ruby` を持たない旧形式テキスト向けのモードです |
| `--ruby-threshold` | `0.8327` | `auto_select` 時の複数トークン語閾値（`cos_cond <= threshold` で仮名化） |
| `--ruby-single-threshold` | `0.65` | `auto_select` 時の1トークン語閾値 |
| `--ruby-device` | `auto` | `auto`（`auto_select` はColab GPU、他はローカル）/ `remote` / `local` |
| `--ruby-preflight` | `False` | 音声生成を行わず、Colab GPUでスコア判定と仮名化対象リスト（`ruby_review.json`）のみ回収 |

### 事前判定（Preflight）→ 確認 → 本生成の流れ（任意）

本生成の前に、`selection: "auto"` の候補のうちどれが仮名化判定になるかを確認・調整したい場合は、`--ruby-preflight` を使います。

1. **事前判定のみ実行（ランタイムは保持）**
   ```bash
   python3 cli/irodori_generate.py \
     --scenario works/my_book/scenario.json \
     --settings works/my_book/settings.json \
     --session work-sess --job pre01 --out works/my_book/preflight \
     --ruby-preflight --new --gpu T4
   ```
   `works/my_book/preflight/ruby_review.json` の `flagged_items` に、仮名化（`kana`）となった語が前後文脈付きで出力されます。必要に応じて `scenario.json` の `selection` を `"kana"` / `"surface"`（または `tts_text`）で調整します。

2. **同じランタイムを再利用して本生成（`--skip-prepare`）**
   ```bash
   python3 cli/irodori_generate.py \
     --scenario works/my_book/scenario.json \
     --settings works/my_book/settings.json \
     --session work-sess --job run01 --out works/my_book/run01 \
     --skip-prepare --stop-after-download
   ```

---

## 5. 本生成（GPUで音声生成・回収・停止）

新規T4ランタイムを作成し、準備・音声生成・回収・検証後に自動停止する標準コマンドです。

```bash
python3 cli/irodori_generate.py \
  --scenario works/my_book/scenario.json \
  --settings works/my_book/settings.json \
  --session work-sess \
  --job run01 \
  --out works/my_book/run01 \
  --new --gpu T4 \
  --stop-after-download
```

- `--out` には**実行ごとに新しいフォルダー**を指定してください（既存の出力先は上書き保護のため拒否されます）。
- `--new` を付けない場合は、指定名の既存セッションを利用します。
- `--skip-prepare` は同じ版のTTS環境を準備済みのセッションを再利用するときだけ指定します（`--new` とは併用不可）。
- `--stop-after-download` を付けると、生成・回収・音声検証がすべて成功した後にランタイムを自動停止します。続けて別ジョブを走らせる場合は外してください。

---

## 6. 発話単位の再生成（`--ids`）

試聴して一部の発話だけ読みや演技を直したい場合は、元の `scenario.json` を修正したうえで `--ids` に発話ID（カンマ区切り）を指定し、新しい `--job` と `--out` へ部分生成します。

```bash
# まず dry-run で選択対象を確認
python3 cli/irodori_generate.py \
  --scenario works/my_book/scenario.json \
  --settings works/my_book/settings.json \
  --ids t0010,t0020 --dry-run

# 選択した発話だけをGPU生成
python3 cli/irodori_generate.py \
  --scenario works/my_book/scenario.json \
  --settings works/my_book/settings.json \
  --session work-sess --job retry01 --out works/my_book/retry01 \
  --ids t0010,t0020 --new --gpu T4 --stop-after-download
```

※ 部分生成の `result.wav` は選択した発話のみを結合した音声です。全編の完成音声への自動差し替えは行わないため、個別WAV（`segments.zip`）を使って編集ソフト等で差し替えるか、修正が固まってから全編を通しで生成してください。

---

## 7. 出力ファイルと確認項目

生成が成功すると標準出力の末尾に `AUDIO_READY <result.wavのパス>` が表示され、`--out` フォルダーに以下が保存されます。

| ファイル | 内容 |
| --- | --- |
| `result.wav` | 対象範囲を入力順に結合した完成朗読音声 |
| `segments.zip` | 発話IDを先頭に持つ個別WAV（`audio/t0010_...wav` 等）のアーカイブ |
| `generated_project.json` | 実行時のシナリオ・設定・ルビ判定結果を含む回収記録 |
| `pipeline.json` | 完了状態（`status: "complete"`）、WAV検証結果、セッション停止結果（`session_stopped`） |
| `plan.json` | 合成要求・実効設定・診断一覧 |
| `telemetry.json` | アカウント全体のCU残量照会・実効GPU・経過時間 |
| `events.jsonl` / `*.log` | 進行イベントと各工程のログ |

終了コード `0` は機械検証（WAVのSHA256・フレーム数一致）の成功を示します。必ず `result.wav` を試聴し、読み・イントネーション・感情・間を確認してください。

---

## 8. トラブル時の対処

- **接続が切れた／Ctrl+Cで中断した**: ローカル監視が止まってもColab側で生成が続いている場合があります。すぐに同じ生成を再送せず、`pipeline.json` と `recovery_command.json` を確認してください。`recovery_command.json` が生成されていれば、表示された回収コマンドで再生成せずに成果物を回収できます。
- **ランタイム停止だけ失敗した（`SESSION_STOP_FAILED`）**: 音声の回収自体は完了しています。`colab sessions` で稼働状況を確認し、不要なら `colab stop -s <セッション名>` で手動停止してください。
- **旧版互換JSONの書き出し**: 確定済みの読みを `tts_text` へ展開し `koebuta_added_ruby` を除去した旧版互換JSONを書き出す場合は、`python3 cli/irodori_generate.py --scenario works/my_book/scenario.json --settings works/my_book/settings.json --export-compatible works/my_book/legacy_scenario.json` を使用します。

さらに詳しいトラブル対策は [TROUBLESHOOTING.md](TROUBLESHOOTING.md) を参照してください。
