# 統合状況

## 現在のmain（2026-11-20）

- [PR #9](https://github.com/karin-tsumugi-lab/koebuta-colab/pull/9) を `aed3c0b` でマージ。マージ直後の `main` と検証済みのPR先頭 `bcce229` にファイル差分がないことをGitHubの比較で確認。
- 公開READMEの見出しは「Koebuta v3」。シナリオ制作プロンプトは `prompts/` にあり、任意のHTML Inspector確認を経てCLIで検査・生成する。参照音声作成キットを追加し、旧Notebook本体・専用テスト・ツール・CIは廃止した。
- 検証結果は [PRのCPU CI](https://github.com/karin-tsumugi-lab/koebuta-colab/actions/runs/44746212419) 成功。旧Notebook削除後のローカル検証はCLI 73件、voice_kit 7件、Inspectorの絵文字挿入テストが成功し、CLI配布マニフェストのSHA-256が62件一致した。
- `d3be8df` の実生成で参照音声候補2件と、採用WAVを使ったCLIの個別・結合WAVの生成と回収を確認。マージ後のGPU再試験は未実施。V2の『山月記』の手元のシナリオは、外字注記直後のルビでV3の `--dry-run` が構文エラーになる。旧作の移行可否は作品ごとに検査する。
- [PR #10](https://github.com/karin-tsumugi-lab/koebuta-colab/pull/10) を `e0e9bd8` でマージ。公開CLIガイドからColab CLIの公式導入手順とローカルGPUへの移植案内にたどれることを確認した。[CPU CI](https://github.com/karin-tsumugi-lab/koebuta-colab/actions/runs/44747592423) は成功。ローカルGPUでの連続生成の実機検証は未実施。

## 2026-11-16のmain（履歴）

- [PR #7](https://github.com/karin-tsumugi-lab/koebuta-colab/pull/7) を bbb253e6、続いて [PR #8](https://github.com/karin-tsumugi-lab/koebuta-colab/pull/8) を d761dc9c でmainへマージ済み。履歴を保持し、強制的な置き換えは行っていない。
- シナリオ化プロンプトv0.3、Notebook v2の原文照合警告化、CLI 2.0.0-devの忠実生成・親／片の対象指定を反映。CLI配布版1.0.1の記録とJSON交換形式v1は区別する。
- mainのマージ直後のtreeは、レビュー・CI成功済みの先頭4d063d6fのtree 838f08e2と完全一致した。アプリのコードはMuseの実生成対象4a94b5bから変更していない。以下の実装時点・統合前の記録は履歴として保持する。
- 最終文書点検は20文書・ローカルリンク113件・JSON例・34感情IDの一致で成功。追加コミット4d063d6fのCLI/Notebook/Inspector CIも成功。
- MuseのT4で全体4単位と一片1単位の生成・回収・検査・停止が成功したとの報告、利用者から試聴して問題なしとの報告を受領。長編・長時間resident・独立した透かしデコードは確認範囲外。詳細は [検証記録](CLI_FAITHFUL_VALIDATION.md) を参照。
- 試験引き継ぎ用ブランチcodex/muse-cli-gpu-test-20261116はmainへ混ぜない。CLIの版は2.0.0-devのまま。Release ZIPの新規発行は別作業。

以下の『main未統合』『実GPU未実施』は各節の作業時点を示す。現在の状態と検証範囲は上記と検証記録の追記を参照。

## 2026-11-16 CLI実生成・試聴確認

- Museが実装4a94b5b／試験用ZIP bb53337をLinux＋T4で試験し、全体4単位（27.74秒）と一片指定1単位（5.36秒）の生成・回収・機械検査・停止が成功したと報告。利用者の試聴でも問題なしとの報告を受領。
- Colab CLI 0.7.5の --version 未対応を案内へ反映。モデルrevisionは既存の回収job.jsonのprovenanceに保存されるため、その場所を明記した。残っていた旧CLIの対象指定・区切り案内も新経路と区別した。アプリのコード変更なし。
- 実行コマンド・要件別の観測・報告の範囲と未確認事項は [実装検証記録](CLI_FAITHFUL_VALIDATION.md) の追記を参照。mainへの統合は未実施。以下の実GPU未実施という記述は初回記録の時点を指す。

## 2026-11-16 CLI忠実生成の実装

- 作業ブランチ `codex/cli-faithful-v02`。基点 `9166f81`（シナリオ化プロンプトPR #7の先頭）。mainやPR #7への直接変更は行わない。
- `irodori_generate.py` と専用遠隔経路で自動分割を廃止。明示TTS片・親/片の対象指定・明示休止・新しい演出既定値・計画照合・選択範囲の完了記録に対応。
- 旧入口とNotebook/HTML/Fast本体は維持。新旧README、移行案内、独立した [仕様v0.2](CLI_FAITHFUL_SPEC.md) と [検証記録](CLI_FAITHFUL_VALIDATION.md)、CPU CIを追加。
- CLI49件、Notebook等30件、HTML絵文字検査が成功。新経路は模擬推論で検査し、実GPU・Colab輸送・試聴は未実施。mainへの統合は未実施。
- 以下の「CLI変更なし」等は各作業時点の範囲・履歴を示す。

## 2026-11-16 外部レビュー反映

- Muse・Geminiのレビューを公開実装と照合し、原文不変の見出し結合、区切りとCLI固有条件、感情の生成設定、改変許可の外縁を明確化。照合警告の重複を整理した。
- 変更は文書のみ。アプリ・JSON構造は変更しない。[採否と検証記録](SCENARIO_PROMPT_EXTERNAL_REVIEW.md)、[固定レビューケース](SCENARIO_PROMPT_REVIEW_CASES.md)を参照。mainへの統合は未実施。

## 2026-11-16 Notebook v2 原文照合の警告化

- 追加依頼により、正式Notebook v2のみ原文不一致を非停止の警告へ変更。元の `source` と照合を残し、読み込み結果と生成計画確認に表示する。
- 話者・発話ID、空本文、不正なTTS片、設定・参照パスなどの停止条件は維持。JSON構造、旧v1・旧プロトタイプ、HTML・CLIは変更しない。
- 生成元・正式Notebook・UI・回帰試験・案内を更新。詳細は [修正・レビュー記録](NOTEBOOK_V2_SOURCE_WARNING_REVIEW.md) を参照。
- 以下のv0.3初回記録の「文書だけ」は追加依頼前の範囲。現在のPRはこのv2修正も含む。mainへの統合は未実施。

## 2026-11-16 シナリオ化プロンプトv0.3（初回記録）

- 作業ブランチ：`codex/scenario-prompt-v03`。基点は確認時の公開main `28c135c6774c5f659cf6856b12b718cdc0050046`。
- 通常のGit fetchは名前解決に失敗したため、GitHub経由で最新コミットとREADMEを取得。既存親コミットと照合してtree・commit双方のSHAが公開mainと完全一致するGitオブジェクトを復元し、専用worktreeを作成した。mainや他作業の変更は編集していない。
- 01・02・03A/B/C、README・エージェント手順・エディタ案内等の文書だけを改訂。交換形式v1の構造、アプリコード、Notebook本体、HTML本体、過去の検証記録は変更しない。
- 全体理解→場面演出→発話分割、一人／複数人朗読共通化、20〜80文字推奨、許可済み見出し改変、既定Bと読み方針Cの別許可を反映。
- コマンド結果、要件ごとの確認根拠、原文照合の実挙動と未実施事項は [v0.3検証・レビュー記録](SCENARIO_PROMPT_V03_VALIDATION.md) を参照。
- この作業の完了は文書改訂とローカル検証を指す。音声による演出品質の改善は未検証。mainへの統合は別途レビュー対象。

## 2026-11-13 絵文字対応の統合前記録（履歴）

以下は当時の記録。絵文字対応は現在の基点mainに含まれるため、末尾の「未統合」は当時の状態を指す。過去の検証結果は今回再実行した範囲と区別する。

- 作業ブランチは `codex/notebook-v2`。基点は `4824e9f`。公開mainの `0f0437d` と基点のファイル差分はない。
- 主な変更はCLI・Fastの絵文字台帳、Inspectorの選択・位置挿入、Notebook生成元、仕様書・AI向け依頼文、READMEと検証記録。
- コマンド結果と要件への適合根拠は [検証記録](EMOJI_RELEASE_VALIDATION.md) に分けて記載した。
- 生成要求の一致、回帰試験、利用者からのCLI実聴・Notebook生成確認に基づき、今回の絵文字対応の統合を推奨する。
- 利用者からHTML版エディタの確認で問題なさそうとの報告を受領。操作条件の詳細ログは未収集。Fast実GPU推論、Drive再起動復元の再試験は未実施。モデルの効果音再現性は利用者の試聴調整対象とする。
- エージェント向け手順を `docs/AGENT_WORKFLOW.md` に統合。CLIのAGENTSとシナリオ作成用03Bは統一手順への案内に置き換え、READMEからリンクした。
- 統一手順のJSON設定例をそのまま読み込み、一時的な検査用WAVと同梱シナリオによるCLI dry-runが終了コード0、生成要求2件で成功。README・統一手順・移行案内のローカルリンクに欠落なし。文書の手順で新規GPU生成を行う全工程試験は未実施。
- この記録の時点では今回の変更は公開mainへ未統合。
