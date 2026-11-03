# Koebuta CLI: AIエージェント向け運用指示

この文書は、利用者に代わってKoebuta CLIを導入・実行するAIエージェント向けです。機能を推測で追加せず、入力や認証情報を勝手に変更せず、確認できた状態だけを報告してください。

## 対象と前提

- CLI v1.1.0は、準備済みのシナリオJSONからIrodori-TTS音声を生成・回収する入口です。配役整理、読み補正、感情判定は行いません。参照未設定時の準備と確認は [自動参照の仕様](../docs/CLI_AUTO_REFERENCE.md) に従います。この版のGPU生成・試聴は未確認です。
- 確認済み環境はWSL2 Ubuntu 26.04、Python 3.10以上、Colab CLI 0.7.5です。別環境は未確認として扱います。
- `irodori_generate.py` はホスト側の標準Pythonで動作します。TTS依存関係はColab側の準備工程で扱います。

## 作業前の安全確認

[Colab利用条件の注意](../docs/COLAB_USAGE.md) とリンク先の公式規約・FAQを確認する。公式CLIが自動化を想定していても、Colabの規約・無料枠の追加制限・禁止用途がなくなるとは判断しない。有料契約の有無だけでなく、CU残高と利用形態を確認する。認証情報そのものの提示は求めない。制限回避のためのアカウント切替や偽の活動による切断回避を提案・実行しない。Koebutaの注意書きをGoogleによる利用許可の代わりにしない。

1. シナリオ本文・参照音声をGoogle Colabへ転送すること、GPU利用枠を消費すること、新規セッション作成の可否を利用者に明示して確認する。承認前にGPU生成を開始しない。
2. Colab CLIのログイン、ブラウザー認証、利用規約同意、Hugging Face等のモデル利用承認、課金またはGPU枠の判断は利用者に任せる。トークン、Cookie、APIキーを要求・表示・保存・ログ出力しない。
3. 原稿、シナリオ、設定、参照WAV、既存の出力・セッションを削除、移動、上書きしない。`--out` は新規フォルダーを指定する。
4. 参照音声と原稿の利用権・同意は利用者の責任である。エージェントは権利確認を省略しない。

## 導入と事前検査

1. Pythonと `colab --version` を確認する。認証の有無は `colab sessions` 等、認証情報を表示しない方法で確認する。
2. 配布物またはリポジトリのルートから `python3 irodori_generate.py --version` と `--help` を実行する。
3. サンプルのdry-runを実行する。dry-runはColabに接続せず、出力フォルダーを作らない。

```bash
python3 irodori_generate.py --scenario irodori_cli_examples/generate_scenario.json --settings irodori_cli_examples/generate_settings.json --session narration-v1 --job chapter01 --out outputs/chapter01-cli --dry-run
```

Windowsから実行する場合は `python3` を `python` に読み替える。WSL内で実行する場合、パスはWSL形式にする。

## 生成前の入力検査

1. `schema_version: 1`、`speakers`、`segments` を持つ本文付きシナリオか確認する。
2. 話者IDと `speakerVoices`、参照音声IDと `voices`、VoiceDesign用 `voice_caption`、`voiceMode` と `reading` の組合せを確認する。
3. 設定の未知キーを見逃さない。CLIの拒否を回避するためにキーを削る・既定値を推測する変更はしない。
4. 感情・演技・読み・話者の内容はAIの品質保証ではない。無人入口が生成を通すことと、人の確認済みであることを混同しない。

## 作品フォルダーとsettingsの作成

```text
作品フォルダ/
├── scenario.json        # 正本。reference_wavは作品内の相対パス
├── voices/
│   ├── narrator.wav     # ファイル名 = 話者ID
│   └── aoi.wav
└── settings.json        # CLI用。以下の規則で作成
```

話者ごとの `reference_wav` は `voices/<話者ID>.wav` とし、提供されたWAVだけを配置する。指定済みファイルの欠落・破損・競合・作品外参照は報告し、別の声で代用しない。WAV自体を提供されていない話者は、存在しないパスを記入せず未指定のままにする。未指定なら自動参照または参照なしの計画をdry-runで確認する。既存ファイルは上書きしない。

`settings.json` はscenarioと同じフォルダーへ作成する。この参照WAV運用では `voiceMode: clone`、モデルは `Aratako/Irodori-TTS-v4.1-Small` とする。scenarioの `koebuta_settings` から次を対応付ける（括弧内は未指定時の運用上の既定値）。

- `reading_mode` → `reading`（cast）。castでは `speakerVoices` を話者ID→同じID、`voices` を同じID→`voices/<話者ID>.wav` とする。
- sharedでは明示された `shared_reference_wav` を `voices.voice_a` へ設定し、`speakerVoices` は省略。WAV指定が全くなければ共通の自動参照を使用できる。一部の話者だけWAVがあり共通WAVがなければ、声を勝手に選ばず止める。
- `use_emotion` → `emotion`（true）、`use_acting` → `acting`（false）、`narrator_emotion` → `narratorEmotion`（false）。
- `seed`（314）、`steps`（40）を転記し、`default_pause_ms`（280）を1000で割って秒単位の `pause` とする。不正値を既定値で隠さない。

これはAIが設定を書くための規約で、自動変換機能ではない。WAVパスはsettingsの位置を基準に解決される。対応状況は [既存の互換表](../docs/EDITOR_GUIDE.md) を参照し、HTMLのTTS片・空行休止等がCLIで同じ結果になると断定しない。作成後はdry-runで確認する。拡張項目と経緯は [PROVENANCE](../docs/PROVENANCE.md) に記録している。

## 実行

利用者の明示承認後にだけ、次の形で実行する。

生成前に1回確認が入る。AIによる承認済みの非対話実行では、先に `--dry-run` の計画を確認したうえで `--yes` を付ける。利用者の承認の代わりに `--yes` を使わない。声候補をシード違いで比較する場合は `voiceMode: design` を明示し、自動参照を作らない。

```bash
python3 irodori_generate.py --scenario <scenario.json> --settings <settings.json> --session <unique-session> --job <unique-job> --out <new-output-dir> --new --gpu T4 --stop-after-download
```

- 既存セッションを使う場合は `--new` を外す。別のセッションへ勝手に接続しない。
- `--skip-prepare` は同一版の準備済みセッションと確認できる場合だけ使う。`--new` と併用しない。
- セッションを維持したい場合は `--stop-after-download` を外す。停止を判断できない場合は保持する。
- CUはアカウント全体の値である。差分をジョブ単独の消費量と断定しない。

## 完了判定と回収

成功は、終了コード0、`AUDIO_READY`、`result.wav`、`segments.zip`、`pipeline.json` の存在と内容を併せて確認する。可能なら検証済みのWAV件数・ハッシュ・フレーム数も確認する。`pipeline.json` の停止状態は終了コードと別に読む。

試聴による誤読、声の一貫性、演技、音量、ノイズの評価は自動合格にしない。利用者に確認を依頼する。

## 失敗・中断時

- Ctrl+Cやホスト側の期限切れで、遠隔実行を失敗扱いにして再送しない。まず受付情報、`pipeline.json`、`recovery_command.json`、遠隔状態を確認する。
- Colab CLIの `--timeout` は、確認済み環境では厳密な実行停止として観測されていない。重複実行を避ける。
- 回収案内があれば、まず再生成なしの回収を実行する。回収だけで入口の完成WAV出力が自動再開するわけではない。
- ランタイム識別子や停止前の状態照会を確認できないとき、自動停止しない。利用者へ状態を報告して判断を求める。
- ログ、入力、参照音声、認証情報を外部へアップロード・共有しない。

## 報告書に含めること

実行コマンド（秘密値を除く）、利用環境、入力ファイル名、実GPU照会結果、セッション・ジョブ名、出力ディレクトリ、終了コード、回収と検証の結果、セッション停止状態、未確認事項を簡潔に報告する。「完了」は機械的成功を示す言葉として使い、聴感品質が確認済みでない場合は明記する。

