# Koebuta CLI v1.0.1

準備済みのシナリオJSONを Irodori-TTS で連続生成し、完成音声をローカルへ回収するCLIです。WebUIを使いません。

seedを変えて声を選ぶ場合は、[声の候補比較と採用（AIエージェント向け）](docs/AI_VOICE_CANDIDATES.md) を参照してください。

> **Colabの利用規約を確認してください。** 公式CLIの利用にもColabの規約が適用されます。無料・CU残高なしの管理ランタイムには遠隔操作や外部WebUI中心の利用等の追加制限があり、CLIは制限を回避するための手段ではありません。有料でも一般の禁止事項・利用上限は残ります。認証・GPU生成の前に [Colab利用条件の注意](../docs/COLAB_USAGE.md) と公式資料を確認してください。

## 動作確認の範囲

WSL2上の Ubuntu 26.04、Colab CLI 0.7.5、Python 3.10以上で確認しました。配布ZIPを展開した状態でCLI関連30テストとサンプルのdry-runが成功しています。T4で28発話の生成・回収・検証は、生成ロジックの最終仕上げ前に確認済みです。

最終表示・CU記録・停止確認の追加後、同じ最終版で新規GPUの音声生成は実行していません。長編、切断からの完全自動復旧、別ランタイムへのジョブ復元はv1の動作保証外です。

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
colab --version
colab sessions
```

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

入力は本文付き `schema_version: 1`、`speakers`、`segments` を持つシナリオJSONと、別の設定JSONです。CLI v1は配役整理、読み補正、感情判定、設定の統合を行いません。指定済みの `tts_text`、感情、演技指示、発話後の間を生成に取り込みます。

Scenario Inspector v0.1.6の `koebuta_settings`、話者の `reference_wav`、`koebuta_tts_parts` は、この入口で設定・WAV指定・分割境界として利用しません。別設定JSONで声と生成条件を指定してください。HTMLでTTS分割した片の境界はCLIへ引き継がれません。`tts_text` 全体にCLI独自の分割検査が適用されるため、HTMLで分割済みでも長い読み上げ文が拒否される場合があります。dry-runで生成要求を確認してから実行してください。

設定では `voiceMode`、`reading`、`baseCaption`、`seed`、`steps`、`pause`、`ttsModel`、`acting`、`emotion`、`narratorEmotion`、`textOptions`、`speakerVoices`、`voices` を使えます。未知のキーは拒否します。参照WAVの相対パスは設定JSONのあるフォルダーから解決されます。

未確認の感情・演技設定を自動で品質承認するものではありません。無人生成の入口では、渡されたシナリオをそのまま対象にするため内部的に未確認許可を明示します。実行前に、人がシナリオの話者、読み、感情、演技、参照音声の権利を確認してください。

## 成果物の回収と確認

成功時に `AUDIO_READY` と完成WAVのパスが出ます。`--out` 内には少なくとも次を残します。

| ファイル | 内容 |
| --- | --- |
| `result.wav` | 原稿順に結合した完成音声 |
| `segments.zip` | 採用された発話別WAV |
| `generated_project.json` | 回収したプロジェクト・発話情報 |
| `pipeline.json` | 完了状態、検証結果、保存先、停止結果 |
| `plan.json` | 入力から検査した生成要求 |
| `telemetry.json` | CU照会、GPU詳細、経過時間。取得不可も記録 |
| `events.jsonl` / `*.log` | 進捗と工程ログ |

終了コード0は、生成・回収・機械検証・保存の成功を示します。音質や演技品質の合格ではありません。必ず完成WAVと発話別WAVを試聴し、誤読、話者、声の一貫性、感情、つなぎ目、音量、雑音を確認してください。

## トラブル時

- **接続が切れた／Ctrl+Cを押した**: 遠隔生成が続いている可能性があります。同じ生成をすぐ再送せず、`pipeline.json`、実行受付情報、`recovery_command.json` を確認してください。Ctrl+Cの終了コード130はローカル監視の中断であり、遠隔停止を保証しません。
- **Colab CLIのtimeout**: 確認したCLIでは `colab exec --timeout` が処理を厳密に停止しない観測があります。タイムアウトだけを失敗判定にせず、受付記録と遠隔状態を照合してください。
- **失敗したが成果物がある**: 出力フォルダーとセッションは保持されます。入口が表示・保存した回収コマンドを使い、再生成せずに回収を試みてください。回収だけで `result.wav` の書き出しを自動再開するわけではありません。
- **停止だけ失敗した**: 回収済みの完成音声は有効な場合があります。`pipeline.json` の `session_stopped` と `shutdown_error`、さらにColabの状態を確認してください。
- **既存セッションの再利用に失敗した**: 実機で初期接続エラーを観測しています。v1は自動再試行しません。ログと回収案内を確認し、状態照合後に判断してください。

参照音声、原稿、認証情報を添えて障害報告を公開しないでください。

## 詳細資料

配布ZIPに同梱された [v1.0.1の詳細仕様・出力・終了コード](DISTRIBUTED_README.md) と [AIエージェント用手順](AGENTS.md)、[トラブル対策](TROUBLESHOOTING.md) を参照してください。原配布物のコードは変更していません。

`DISTRIBUTED_*` と第三者表示は元配布物の記録も兼ねています。第三者表示にある旧名Yomibuta・α版や調査用fixtureへの言及は配布当時の記述で、fixture本体はこの構成に含みません。現在の操作手順はこのREADMEを参照してください。
