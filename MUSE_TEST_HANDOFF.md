# Muse向け：Koebuta CLI 忠実生成の実機試験

このZIPはPR #8の実装コミット `4a94b5b0b4730924fb4e6425cae14374284287e9` を基準に、試験入力・期待計画・引き継ぎ手順だけを追加した固定版です。mainの配布版ではありません。アプリのソースコードは基準コミットと同一です。

まずこのファイルを読み、既存のMuse側Koebuta改変を上書きせず、展開した別フォルダーで試験してください。テスト中はソース・テスト・入力・設定を変更しません。不備は再現条件と修正案を報告してください。既存コードへの合流やGitHubへの結果公開は依頼範囲外です。

## 目的と現状

- 作成済み発話を自動分割しないこと、明示TTS片が維持されること、片だけの再生成、休止、回収・停止を実Colabで確認する。
- CPUではCLI49件、Notebook等30件、HTMLのNode検査とGitHub CIが成功済み。実GPU生成・新経路のresident実機起動・音声試聴は未実施。
- 華凜側ではWSL起動が `Wsl/E_ACCESSDENIED` または `Wsl/Service/CreateInstance/E_ACCESSDENIED` で拒否された。Colab接続前の問題で、GPUは未使用。Muse環境でこのWindows問題を再現・修復する必要はない。
- 試験は短い全体1回（4生成要求）と `garden#2` の選択生成1回（1生成要求）、合計5生成要求まで。自動再試行や比較実験を広げない。追加GPU・長時間利用が必要なら結果を報告して止める。

## 同梱物

- `cli/`：新しいCLI、遠隔worker、輸送・環境準備・透かし検査・テスト・第三者表示。
- `docs/CLI_FAITHFUL_SPEC.md`：実装基準v0.2。
- `docs/CLI_FAITHFUL_VALIDATION.md`：実施済み検査と未実施範囲。
- `handoff/muse_cli_gpu/scenario.json` / `settings.json`：短い試験入力（この試験用の創作、VoiceDesign、参照WAV不要）。
- `handoff/muse_cli_gpu/expected_full_plan.json` / `expected_piece_plan.json`：華凜側で成功したdry-run。セッション名などの起動引数は見本で、実行用設定ではない。
- `handoff/muse_cli_gpu/verify_results.py`：回収した音声・対象範囲・休止・親WAVの機械検査。
- `handoff/muse_cli_gpu/REPORT_TEMPLATE.md`：返却レポートのひな型。

## 1. 環境を確認する（GPU不要）

このREADMEのあるZIP展開ルートを作業ディレクトリにする。LinuxではWSL不要。Python 3.10以上、Node、公式Colab CLIを使う。ホスト側Pythonは標準ライブラリだけで動く。モデル依存は遠隔の準備工程が導入する。

```bash
python3 --version
node --version
colab --version
colab sessions
python3 cli/irodori_generate.py --version
(cd cli && python3 -m unittest test_faithful test_irodori_generate test_cli_terminal -v)
python3 -m unittest test_inspector_p0 test_notebook_v2 test_v2_emoji test_v2_source_validation -v
node test_inspector_emoji.cjs
```

Colab CLIがPATHになければ、既存インストールの場所を確認する。認証されていなければ利用者にログインを引き継ぎ、トークン・Cookieを要求・表示・ZIPへ保存しない。ログイン・利用条件への同意を代行しない。認証・接続・GPUが使えなければ『未実施』として具体的な原因を返す。

GPU・費用・原稿転送は今回の小規模試験の範囲。公開の試験用創作とVoiceDesignのみを使い、個人の原稿・参照WAVは転送しない。Colabのアカウント上限を回避しない。`docs/COLAB_USAGE.md`、LICENSE、THIRD_PARTY_NOTICES.mdも確認する。

## 2. dry-run

新規の識別名を作る。以下の変数を設定した同じシェルで続ける。

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SESSION="muse-faithful-$STAMP"
RUN="outputs/muse_cli_gpu_$STAMP"
FIXTURE="handoff/muse_cli_gpu"
mkdir -p outputs
mkdir "$RUN"
python3 cli/irodori_generate.py --scenario "$FIXTURE/scenario.json" --settings "$FIXTURE/settings.json" --session "$SESSION" --job "$SESSION-full" --out "$RUN/full" --dry-run > "$RUN/full_plan.json"
python3 cli/irodori_generate.py --scenario "$FIXTURE/scenario.json" --settings "$FIXTURE/settings.json" --session "$SESSION" --job "$SESSION-piece" --out "$RUN/piece" --ids 'garden#2' --dry-run > "$RUN/piece_plan.json"
```

mkdirが既存フォルダーで失敗したら新しいSTAMPを作り直す。dry-runが失敗した状態でGPU生成へ進まない。シェルが失敗後も続行する環境では各コマンドの終了コードを確認する。

期待する全体要求は `heading, garden#1, garden#2, girl` の4件。改行付き見出しheadingは一つのまま。片間の休止は0。pause_after_msは順に500/0/700/200、冒頭100ms・末尾200ms。既定のacting/emotion/narratorEmotionはすべてtrue。

片指定はgarden#2の1件、scope=selection、complete_segment_ids=[]、冒頭末尾0ms。要求に親由来の700msが残っていても、単独WAVの末尾へ足さない。見出し18文字の範囲外通知とsource未提供の情報は想定内。sourceを追加して消す必要はない。

## 3. 全体の実生成

専用の新規T4セッションを使い、既存の他作業のセッションを停止・上書きしない。初回はpiece試験へ再利用するため、成功時もセッションを保持する。

```bash
python3 cli/irodori_generate.py --scenario "$FIXTURE/scenario.json" --settings "$FIXTURE/settings.json" --session "$SESSION" --job "$SESSION-full" --out "$RUN/full" --new --gpu T4
```

終了コード0、AUDIO_READY、full/pipeline.jsonのstatus=completeを確認する。実GPUは指定と別に照会・記録する。既存out/jobは使い回さない。全体生成に失敗したらpieceを実行せず、下記の失敗時の手順へ進む。

## 4. 一片だけを再生成する

初回でこの版の環境を準備できた場合だけ --skip-prepare を使う。原シナリオを編集せず、同じセッション・新規ジョブと出力先で実行する。成功したら回収・検証後に停止する。

```bash
python3 cli/irodori_generate.py --scenario "$FIXTURE/scenario.json" --settings "$FIXTURE/settings.json" --session "$SESSION" --job "$SESSION-piece" --out "$RUN/piece" --ids 'garden#2' --skip-prepare --stop-after-download
python3 "$FIXTURE/verify_results.py" --full "$RUN/full" --piece "$RUN/piece" > "$RUN/verification.json"
colab sessions
```

各終了コードを確認する。親gardenの全片が揃う全体生成だけでparent_audio.gardenができる。一片だけの生成では親WAVを作らず、全編完成扱いにしない。既存全編への差し替え・候補採用・自動再結合は今回の対象外。

## 5. 失敗・停止

接続切断・Ctrl+C・待機期限超過でも遠隔は動いている可能性がある。同じ生成を再送せず、pipeline.json、invocation.json、recovery_command.json、工程ログを読む。提示済みのrecoverコマンドで回収を優先する。回収だけでresult.wavまでの書き出しを自動再開するとは限らない。

失敗時は成功時停止が実行されない場合がある。今回作成したSESSIONの識別・実行状態を照合し、必要な回収を済ませてから、そのセッションだけを `colab stop -s "$SESSION"` で停止し、再度一覧で確認する。停止できなければ稼働中の可能性を直ちに報告する。Colab CLIのヘルプと実際の終了コードも確認する。

## 6. 試聴・返却

機械検査と試聴は別。音声を聴ける場合は、見出しの欠落・繰り返し、gardenの片のつなぎ目、girlの演技、誤読、雑音、不自然な無音を確認する。聴けない場合は明示し、音声をあるじさまへ返す。モデルの呼吸・末尾無音を含む聴感の間と、明示的に追加した休止のフレーム数を混同しない。

REPORT_TEMPLATE.mdを埋め、以下を返す：

1. 実行環境、コマンド・終了コード、対象コードの基点SHA、実GPU、工程時間、取得できたCU差（アカウント全体の値）。
2. full/result.wav・full/segments.zip・piece/result.wav・piece/segments.zip。
3. full/pieceのplan.json、project.json、generated_project.json、pipeline.json、telemetry.json、verification.jsonと必要な*.log。
4. recovered/job/job.jsonとplan.json、固定fixture、入力変更の有無、未実施項目、失敗の再現手順、試聴所見。

認証情報を含めない。出力先やログに秘密がないことを確認し、成果物は依頼者へ返す。GitHubへ私有ログや生成データをコミットしない。合否を通すために入力や検査を変更しない。

## 関連資料

- [新入口のREADME](cli/README.md)
- [仕様v0.2](docs/CLI_FAITHFUL_SPEC.md)
- [CPU検証記録](docs/CLI_FAITHFUL_VALIDATION.md)
- [PR #8](https://github.com/karin-tsumugi-lab/koebuta-colab/pull/8)

AGENT_WORKFLOW等に残る旧CLIの自動分割・対象指定なしの説明は旧入口のもの。この試験では2.0.0-devのirodori_generate.pyと本手順を使う。
