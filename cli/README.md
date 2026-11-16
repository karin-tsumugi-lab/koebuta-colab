# Koebuta CLI 2.0.0-dev（忠実生成）

準備済みのシナリオJSONを Irodori-TTS で連続生成し、完成音声をローカルへ回収するCLIです。WebUIを使いません。

> **Colabの利用規約を確認してください。** 公式CLIの利用にもColabの規約が適用されます。無料・CU残高なしの管理ランタイムには遠隔操作や外部WebUI中心の利用等の追加制限があり、CLIは制限を回避するための手段ではありません。有料でも一般の禁止事項・利用上限は残ります。認証・GPU生成の前に [Colab利用条件の注意](../docs/COLAB_USAGE.md) と公式資料を確認してください。

## 動作確認の範囲

開発版の `irodori_generate.py` は、作成済みの発話・明示TTS片をそのまま生成する入口です。CLI 1.0.1の自動分割はこの入口では使いません。交換形式は引き続き `schema_version: 1` です。CLIの版とJSON形式の版を混同しないでください。

新経路はCPUの模擬推論と既存回帰試験で確認しています。2026-11-16にMuseのLinux環境で新経路の実Colab・T4生成を試し、全体4単位（27.74秒）と一片指定1単位（5.36秒）の生成・回収・機械検査・停止が成功しました。利用者の試聴でも問題なしとの報告を受領しています。長編性能や長時間セッションでのresident継続性は今回の確認範囲外です。検査結果と未確認範囲は [実装検証記録](../docs/CLI_FAITHFUL_VALIDATION.md)、確定した判断は [仕様v0.2](../docs/CLI_FAITHFUL_SPEC.md) を参照してください。

## 必要なもの

- WSL2 Ubuntu（確認済みは26.04）またはLinux
- Python 3.10以上。ホスト側は標準ライブラリのみで動作します
- 認証済みの Colab CLI（確認済みは0.7.5）
- 本文付きのシナリオJSONと生成設定JSON
- GPU生成を行う場合のGoogle Colab利用権限。モデル利用承認・認証条件はIrodori-TTSに従います

Windowsから起動する場合は、WindowsのPythonからでもWSL側のColab CLIを検出できます。WSL内から起動する場合は、入力パスをWSL形式で指定してください。

## Colab CLIの認証と接続

Colab CLIのインストール方法と認証画面は、CLI本体の公式手順に従ってください。認証情報、Cookie、トークンを設定JSON、シナリオJSON、ログ、リポジトリへ書き込まないでください。

次でCLIが呼び出せることを先に確認します。

```bash
colab --help
colab sessions
```

Colab CLI 0.7.5では `--version` が未対応との実機報告があります。版番号は導入に使用したパッケージ管理ツールの表示やCLIの更新通知で確認し、`--version` のusageエラーを接続・生成の失敗と混同しないでください。

このプロジェクト側では、Colab CLIの認証を自動化・代行しません。新規GPU作成、原稿・参照音声のGoogle Colabへの転送、GPU利用枠の消費は、実行前に利用者が理解して承認してください。

## 最初の確認（GPUを使わない）

この配布一式の `cli/` フォルダーへ移動して、まずdry-runを実行します。Colabへ接続せず、出力フォルダーも作りません。

```bash
python3 irodori_generate.py --scenario irodori_cli_examples/generate_scenario.json --settings irodori_cli_examples/generate_settings.json --session narration-v1 --job chapter01 --out outputs/chapter01-cli --dry-run
```

WindowsのPythonから実行する場合は `python3` を `python` に読み替えます。成功時は標準出力にJSONだけが出力されます。

## GPU生成

以下は新しいT4ランタイムを作成し、準備・生成・回収・検証後に停止する例です。

```bash
python3 irodori_generate.py --scenario irodori_cli_examples/generate_scenario.json --settings irodori_cli_examples/generate_settings.json --session narration-v1 --job chapter01 --out outputs/chapter01-cli --new --gpu T4 --stop-after-download
```

- `--new` を付けない場合、指定名の既存セッションだけを利用します。新しいランタイムは作りません。
- `--skip-prepare` は、同じ版のTTS環境を準備済みのセッションだけに使います。`--new` とは併用できません。
- `--stop-after-download` は、生成・回収・音声検証・保存がすべて成功してから停止します。省略時はセッションを保持します。
- `--no-usage` はCU照会だけを省略します。CUはアカウント全体の値であり、このジョブ単独の実消費とは表示しません。
- `--out` は実行ごとに新しいフォルダーを指定してください。既存出力は上書きしません。

実際に割り当てられたGPUと新規作成時の指定は別々に表示されます。GPU指定だけで実GPUが確定したとは判断しません。

## シナリオと設定

入力は本文付き `schema_version: 1`、`speakers`、`segments` を持つシナリオJSONと、別の生成設定JSONです。配役整理、読み補正、感情判定、本文修復、自動分割・結合は行いません。改行を含む見出しも、一発話なら一つの生成要求のままです。80文字超や短文は通知し、勝手に補正しません。

`tts_text` が非空ならそれを使い、未指定・空なら `text` の明示ルビだけを指定形式で展開します。位置指定絵文字は保持し、発話全体の感情タグと演技Captionは生成時に適用します。`source` は任意で、未提供時に作りません。提供時の順序付き部分照合は最初の不一致を警告し、許可済み改変か本文の不備かは利用者が判断します。入力ファイルは上書きしません。

`koebuta_tts_parts` がある場合は、2個以上の非空文字列、非空の `tts_text`、片の連結と `tts_text` の完全一致が必要です。結合文字・絵文字の途中の切断は拒否します。各片へ親の話者・感情・演技・声・生成条件を継承し、片の間に休止を追加しません。HTMLの `koebuta_settings` と話者の `reference_wav` は自動採用しません。別設定JSONと必要な `--voice` を使ってください。

区切り（`segment_type: "separator"`）は読み上げません。`text` と `speaker_id` は省略でき、指定する話者は登録済みである必要があります。`emotion` は区切りも `neutral` を指定してください。

設定には `title`、`voiceMode`、`reading`、`baseCaption`、`seed`、`steps`、`pause`、`ttsModel`、`acting`、`emotion`、`narratorEmotion`、`textOptions`、`speakerVoices`、`voices` を使えます。未知のキーは拒否します。参照WAVの相対パスは設定JSONのあるフォルダーから解決し、選択範囲で必要な参照音声だけを検査・転送します。

**移行時の変更：** 未指定の `acting`・`emotion`・`narratorEmotion` はすべて `true` です。明示した `false` は尊重し、演出を抑制する場合に警告します。既存設定を使う場合は値を確認してください。自動空行休止（`textOptions.blankMode: group/count`）、記号からの区切り生成（`symbolSeparators: true`）、追加の読み変換（`readingMode: selective/all`）は拒否します。必要な休止・読みをシナリオへ明示してください。

### 休止

`pause_after_ms` は0〜10000の整数です。発話の指定値（0を含む）を優先し、未指定なら直後の区切りに明示された値の最大値、それもなければ発話間だけ共通 `pause`（秒、既定0.28、0〜10）を使います。休止を合算しません。冒頭・末尾に共通値を足さず、明示された端の休止は保持します。生の改行や `blank_lines_after` から休止を推定しません。

### 対象を指定した再生成

同じシナリオへ `--ids a,b#2` のように指定します。親IDはその全片、`親ID#番号` は1始まりの明示片を指定します。入力順で生成し、重複は一度だけ、存在しないID・区切りID・空指定は生成前に拒否します。下位CLIの旧 `--regenerate` と混用しません。

```bash
python3 irodori_generate.py --scenario scenario.json --settings settings.json --session narration-v1 --job retry01 --out outputs/retry01 --ids a,b#2 --dry-run
```

dry-runを確認後、実行時には `--dry-run` を外します。毎回新しいジョブIDと出力先を使います。結果は選択範囲のWAVです。既存全編への自動差し替えや候補採用は行いません。飛ばした発話の長さ・休止を補間せず、選択した左側単位の休止を使います。親の全片が揃った場合だけ親発話WAVを追加し、一片だけを親全体の完成扱いにしません。

未確認の感情・演技設定を自動で品質承認するものではありません。無人生成の入口では、渡されたシナリオをそのまま対象にするため内部的に未確認許可を明示します。実行前に、人がシナリオの話者、読み、感情、演技、参照音声の権利を確認してください。

## 成果物の回収と確認

成功時に `AUDIO_READY` と完成WAVのパスが出ます。`--out` 内には少なくとも次を残します。

| ファイル | 内容 |
| --- | --- |
| `result.wav` | 入力順に結合した全体／選択範囲の音声 |
| `segments.zip` | 生成単位のWAVと、全片が揃った親の `utterances/ID.wav` |
| `generated_project.json` | 元シナリオ・設定と実行契約を含む回収記録（シナリオ単体ではない） |
| `pipeline.json` | 完了状態、検証結果、保存先、停止結果 |
| `plan.json` | 生成要求・親ID／片番号・範囲・実効設定・診断 |
| `telemetry.json` | CU照会、GPU詳細、経過時間。取得不可も記録 |
| `events.jsonl` / `*.log` | 進捗と工程ログ |

終了コード0は、生成・回収・機械検証・保存の成功を示します。音質や演技品質の合格ではありません。必ず完成WAVと発話別WAVを試聴し、誤読、話者、声の一貫性、感情、つなぎ目、音量、雑音を確認してください。

モデル等の固定revisionは、`pipeline.json` の `recovered` が示す回収先の `job/job.json` にある `provenance.model_revision`、`codec_revision`、`watermark_model_revision`、`tokenizer_revisions` へ記録されます。`telemetry.json` はCU・GPU・時間の記録で、モデルrevisionの保存先ではありません。試験報告ではこの回収記録から転記してください。

## トラブル時

- **接続が切れた／Ctrl+Cを押した**: 遠隔生成が続いている可能性があります。同じ生成をすぐ再送せず、`pipeline.json`、実行受付情報、`recovery_command.json` を確認してください。Ctrl+Cの終了コード130はローカル監視の中断であり、遠隔停止を保証しません。
- **Colab CLIのtimeout**: 確認したCLIでは `colab exec --timeout` が処理を厳密に停止しない観測があります。タイムアウトだけを失敗判定にせず、受付記録と遠隔状態を照合してください。
- **失敗したが成果物がある**: 出力フォルダーとセッションは保持されます。入口が表示・保存した回収コマンドを使い、再生成せずに回収を試みてください。回収だけで `result.wav` の書き出しを自動再開するわけではありません。
- **停止だけ失敗した**: 回収済みの完成音声は有効な場合があります。`pipeline.json` の `session_stopped` と `shutdown_error`、さらにColabの状態を確認してください。
- **既存セッションの再利用に失敗した**: 実機で初期接続エラーを観測しています。自動再試行しません。ログと回収案内を確認し、状態照合後に判断してください。

参照音声、原稿、認証情報を添えて障害報告を公開しないでください。

## 詳細資料

配布ZIPに同梱された [v1.0.1の詳細仕様・出力・終了コード](DISTRIBUTED_README.md) と [AIエージェント用手順](AGENTS.md)、[トラブル対策](TROUBLESHOOTING.md) を参照してください。旧 `python -m irodori_cli` の分析・自動分割・キャッシュ経路は維持しています。新入口との挙動の違いに注意してください。

`DISTRIBUTED_*` と第三者表示は元配布物の記録も兼ねています。第三者表示にある旧名Yomibuta・α版や調査用fixtureへの言及は配布当時の記述で、fixture本体はこの構成に含みません。現在の操作手順はこのREADMEを参照してください。
