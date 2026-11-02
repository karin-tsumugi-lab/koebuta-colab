# シナリオJSONからColab CLIで生成する

CLI v1.0.1。既存のYomibuta/irodori_cliのTTS実装とColab転送・回収処理を使い、WebUIなしで「生成準備済みのシナリオ → 連続生成 → ローカル回収」を一つの入口で実行する。

入力は本文付き `schema_version: 1` / `speakers` / `segments` のシナリオJSONと、独立した生成設定JSON。配役整理・読み補正・感情判定のLLM工程は実行しない。指定済みの感情・演技・tts_text・発話後の間を取り込む。設定の統合は行っていない。

## WSL Ubuntuから使う

配布ZIPを展開したフォルダー、またはプロジェクトのフォルダーで実行する。ホストはPython 3.10以上の標準ライブラリのみで動作し、WSLに認証済みColab CLIが必要。今回の実機検証はColab CLI 0.7.5、Ubuntu-26.04 / WSL2で実施した。

```bash
python3 irodori_generate.py --version
python3 irodori_generate.py --help
```

まずローカルで検査する。このコマンドはColabに接続せず、出力フォルダーも作らない。

```bash
python3 irodori_generate.py \
  --scenario irodori_cli_examples/generate_scenario.json \
  --settings irodori_cli_examples/generate_settings.json \
  --session narration-v1 --job chapter01 --out outputs/chapter01-cli \
  --dry-run
```

新しいT4ランタイムを作成し、TTS環境だけを準備して生成する。原稿と明示した参照音声をGoogle Colabへ転送し、GPUの利用枠を消費する。モデルの利用承認・認証条件は既存TTS実装に従う。

```bash
python3 irodori_generate.py \
  --scenario irodori_cli_examples/generate_scenario.json \
  --settings irodori_cli_examples/generate_settings.json \
  --session narration-v1 --job chapter01 --out outputs/chapter01-cli \
  --new --gpu T4 --stop-after-download
```

Windowsから使う場合は `python3` を `python` にする。既存ドライバーがWSL版Colab CLIを検出する。WSLから直接起動する場合、入力パスはWSL形式を使う。

- `--new` なし: 指定名の既存セッションを使う。新しいランタイムを勝手に作成しない。
- `--skip-prepare`: 同じ版のTTS準備済みセッションを使う場合だけ指定。`--new` との併用不可。
- `--stop-after-download`: 全生成・回収・音声検証・WAV/ZIP書き出しの成功後に指定セッションを停止。省略時は保持する。
- `--timeout`: 既存ドライバーへ渡す工程ごとの待機上限。既定7200秒。タイムアウトの追加設計・改修は今回行っていない。
- `--out`: 毎回新しいフォルダーを指定。既存の出力は上書きしない。
- `--no-usage`: CU残量照会を省略。GPU・進行状況・結果の表示は維持する。

この入口は無人生成用であり、内部で `synthesize --allow-unreviewed` を明示指定する。確認済みフラグを偽って付けず、渡されたシナリオをそのまま生成対象とする。既存の対話的CLIのreview動作は変更しない。

## 生成設定

サンプルは `irodori_cli_examples/generate_settings.json`。既存の設定項目をそのまま使い、未知のキーは誤指定として拒否する。

`title`, `reading`, `voiceMode`, `baseCaption`, `seed`, `steps`, `pause`, `ttsModel`, `acting`, `emotion`, `narratorEmotion`, `textOptions`, `speakerVoices`, `voices` が指定可能。既定値・値の範囲は既存プロジェクト検証と共通。`acting: true` なら演技指定を使用し、`emotion: true` なら感情タグを使用する。語り手に感情を付ける場合は `narratorEmotion: true`。

共通の参照音声によるクローン:

```json
{
  "voiceMode": "clone",
  "reading": "shared",
  "acting": true,
  "emotion": true,
  "voices": {"voice_a": "reference.wav"}
}
```

人物別の参照音声:

```json
{
  "voiceMode": "clone",
  "reading": "cast",
  "speakerVoices": {"assistant": "voice_a", "guest": "voice_b"},
  "voices": {"voice_a": "references/assistant.wav", "voice_b": "references/guest.wav"}
}
```

`speakerVoices` のキーはシナリオの話者IDと一致させる。`voices` の相対パスは**設定ファイルのあるフォルダー**から解決する。CLIの `--voice voice_a=/path/to/reference.wav` は同じIDの設定を上書きし、その相対パスは**実行時のフォルダー**から解決する。使われない音声指定は転送せず、入力検査でエラーにする。

`voiceMode: design` と `reading: shared` は `baseCaption` から共通の声を作る。人物別のVoiceDesignには `reading: cast`, `speakerVoices: {"話者ID": "design"}` とシナリオ側各話者の `voice_caption` を指定する。シナリオ内の任意パスを転送対象として解釈しない。

参照あり・なしの混在例:

```json
{
  "reading": "cast",
  "voiceMode": "design",
  "speakerVoices": {"narrator": "narrator_ref", "guest": "design"},
  "voices": {"narrator_ref": "voices/narrator.wav"},
  "acting": true,
  "emotion": true
}
```

この例では語り手がクローン、guestはシナリオのvoice_captionから生成する。クローン指定でWAVがない場合は生成前に停止し、自動でVoiceDesignへ変更しない。参照なしで声質説明も空の場合も停止する。シナリオ内の `reference_wav` や `koebuta_settings` を自動的に生成設定へ取り込む機能はv1に含めない。

## 端末の表示

開始時にセッション・ジョブ・モデル・ステップ・seed・朗読形式・発話数・クローンと参照なしの件数・終了後の停止方針を表示する。GPUは新規作成の指定と、準備後に照会できた実際のGPU・ランタイム識別子を分ける。

進捗は経過時間付きで表示し、詳細な転送ログやトレースは工程別ログへ保存する。モデル準備中等に更新がない場合、状態確認の応答が続いていれば約30秒間隔で待機継続を表示する。

生成の残り時間は初回モデル読み込みを除外して、以後の進捗間隔から計算する目安。最初は「初回計測中」と表示し、計算できるまで推測値を出さない。モデル取得・結合・回収にかかる残り時間は含まない。

CU残量・CU/時間は開始時、環境準備後、終了時にColab CLIで照会する。**アカウント全体の値**なので、ほかのランタイムの利用や残量補充が含まれる。開始・終了の残量差分をこのジョブ単独の実消費とは表示しない。取得に失敗した場合は「取得不可」とし、0として扱わず、生成を続ける。GPUを新規作成する前の消費率0は、新規GPUの消費率見積もりではない。

`telemetry.json` の保存に失敗した場合も、警告を一度表示して生成結果の判定を維持する。生成成功時の終了コード0と `AUDIO_READY`、生成失敗時の元のエラー、監視中断時の130を補助記録の保存失敗で置き換えない。保存エラーの内容は、保存できる場合の `pipeline.json` 内の `telemetry.save_error` にも残す。

通常の進捗・案内は標準エラー、最終の `AUDIO_READY` は標準出力に出す。`--dry-run` は標準出力のJSONだけを返し、Colab照会もファイル作成も行わない。

## 出力と再実行

成功時に `AUDIO_READY` と完成WAVのパスを表示する。

| 出力 | 内容 |
| --- | --- |
| `result.wav` | 原稿順に結合した完成音声 |
| `segments.zip` | 採用した発話別WAV |
| `generated_project.json` | 回収したプロジェクト・発話情報 |
| `pipeline.json` | 完了/失敗、検証結果、保存先、停止結果 |
| `plan.json` | 入力から検査した発話ごとの生成要求 |
| `telemetry.json` | CUの取得結果、GPU詳細、経過時間。取得不可も記録 |
| `events.jsonl` | 経過時間付きの端末表示・進捗イベント |
| `project.json` | 入力から作成した生成用スナップショット |
| `prepare.log`, `synthesize.log` | 工程の標準出力とエラー |
| `prepare/`, `synthesize/` | 実行受付ID、回収ZIP、遠隔ログ等の既存ドライバー出力 |
| `stop.log` | 停止コマンドの出力（停止を指定した場合） |

入力シナリオと設定は変更しない。長い発話の分割は既存の本文保持ルールを使う。短い発話の自動結合やプロンプト書き換えはこの入口には追加していない。

失敗時は生成済み・回収済みデータとセッションを保持する。途中生成を完成音声として公開しない。実行受付情報を保存できていれば、`recovery_command.json` と端末に、再生成せず回収するための具体的なコマンドを残す。このコマンドは既存の `irodori_colab_cli.py recover` を使用し、回収先は今回の出力内のrecovery/となる。回収後の音声はその `latest.json` が指すrecovered/job/内を確認する。回収だけでは入口のresult.wav書き出しは自動再開しない。同じ生成を自動再送しない。

Ctrl+Cはローカル監視の中断であり、遠隔の生成停止を保証しない。`pipeline.json` にinterruptedと記録し、回収済みデータを保持する。復旧する場合はまず実行受付情報と遠隔状態を確認する。

停止だけに失敗した場合、回収した完成音声は有効。`pipeline.json` に `status: complete`, `session_stopped: false`, `shutdown_error` を残し、手動で状態を確認する。停止コマンドの成功だけでは停止済みとせず、後続の状態照会も確認する。実行したランタイムの識別情報を取得できなかった場合、停止前の照会に失敗した場合、または識別子が同名の別環境に入れ替わっていた場合は、自動停止せず保持する。

| 終了コード | 意味 |
| --- | --- |
| 0 | 音声の生成・回収・検証・保存に成功。GPU停止結果は別途表示・pipeline.jsonを確認 |
| 1 | 入力検査・工程・回収・検証のいずれかが失敗。ログと回収案内を確認 |
| 2 | コマンド引数の構文エラー |
| 130 | Ctrl+Cによる中断。遠隔処理は継続している可能性あり |

## 検証範囲

生成経路は桃太郎の全28発話で、全員共通クローン・全話者WAVなし・語り手のみクローンの混在の3条件をT4で実生成・回収・検証済み。生成物はユーザーによる試聴確認済み。CPUテストでは入力検査・破損/未完了音声拒否・表示・CU取得失敗・回収案内・中断・停止順序も確認する。

既存ランタイムの再利用時に、CLIの初期接続エラーを実機で観測した。状態照合後、新規ランタイムでは混在生成が成功した。v1はこれを自動再試行せず、ログ・回収案内を残す。タイムアウト設計の見直し、切断からの完全自動復旧、設定の統合、短文の自動結合は後続課題。別のノートブックや外部Koebutaリポジトリとの互換性を確認済みとは扱わない。

表示・CU・停止確認の最終変更後にGPU生成を追加実行してはいない。生成ロジックは今回の仕上げで変更していない。

2026-11-02のv1.0.1確認: Windowsの回帰テスト92件、WSLのCLI関連テスト30件が成功。v1.0.0では既存Colab CLIからCU残量・消費率・稼働枠を読み取る実接続も確認した。配布ZIPは展開したファイルだけでCLI関連テストとサンプルのdry-runを検査する。v1.0.1では新規GPUの作成や音声再生成を行っていない。
