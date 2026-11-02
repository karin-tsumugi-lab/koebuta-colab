# 収録元と検証範囲

## シナリオ運用文書の整理

発話長の注意は総合README、作品フォルダーとsettings作成の規約は `cli/AGENTS.md` に集約しました。一時追加した `SCENARIO_WORKSPACE.md` と `SCENARIO_EXTENSIONS.md` は統合して削除しました。`voices/<話者ID>.wav` は推奨する配置規約であり、HTMLが強制する命名ではありません。settingsの運用既定値はCLI実装の既定値とは区別します。

### HTML v0.1.6が保存する任意拡張

基本のschema v1を変更するものではありません。生成側の対応は [互換表](EDITOR_GUIDE.md)、調査時点の詳細は [既存互換性資料](references/NOTEBOOK_HTML_COMPATIBILITY_v0.1.6.md) を参照してください。

| 項目 | 意味 |
| --- | --- |
| root `koebuta_settings` | 朗読方式、感情・演技の使用、seed・steps、共通・空行休止、ルビ形式、共通WAVパス |
| speaker `reference_wav` | 作品内の相対WAVパス。WAV本体をJSONへ埋め込むものではない |
| segment `koebuta_tts_parts` | 2片以上の非空文字列。連結が発話全体の `tts_text` と完全一致。原文を分割しない |
| segment `blank_line_pause_ms` | 空行時の個別休止（0以上の整数ms） |
| segment `koebuta_edit` | 編集履歴・要確認印。actions、needs_review、forced、fallback等 |
| segment `koebuta_merge_backup` | 強制結合前の項目の保存。生成本文として再読込しない |

HTML設定の既定はreading_mode=cast、use_emotion=true、use_acting=false、narrator_emotion=false、seed=314、steps=40、default_pause_ms=280、default_blank_line_pause_ms=1200、default_text_format=none、shared_reference_wav=nullです。短文・長文の判定閾値はUI状態で、JSONへ保存されません。拡張項目の保持と生成への反映は別であり、未知属性を変換時に黙って破棄しない方針です。

初回整理日：2026-11-02（日本時間）。統合構成は公開済みです。2026-11-03、旧ルート直下のNotebook関連16ファイルを削除し、`notebook/` を正本へ統一しました。削除した旧版はGit履歴から復元できます。ライセンス・権利表示と元配布物の記録は役割が異なるため保持しています。

既存のNotebook互換PR #1は旧ルートのファイルを対象としていたため、採用時には `notebook/` 以下へ変更を移して検証する必要があります。今回PRのマージや推論コードの変更はしていません。

| 対象 | 収録元 | 今回の変更 |
| --- | --- | --- |
| `cli/` のコード・サンプル・同梱依存定義 | 利用者提供 `irodori-colab-cli-1.0.1.zip`（52エントリー） | コードを変更せず展開。READMEを整理し、原READMEは `DISTRIBUTED_README.md` へ保存。AGENTSとトラブル対策を追加 |
| `notebook/` | `karin-tsumugi-lab/koebuta-colab` のコミット `0aeaccab0746da237d9120ba92bed3fede0e45c5` | Notebook・既存テストは変更なし。README、FAQ、ローカル移植案の入口へ注意・リンクを追加 |
| 単一HTML | 利用者提供 `Koebuta_Scenario_Inspector_v0.1.6.html` | 内容を収録。テキストの改行はLFへ正規化。機能変更なし |
| `docs/references/` | 利用者提供のNotebook互換性資料とHTMLレビュー | 過去資料として保存。記載の推奨事項を今回の実装依頼と解釈しない |
| Fast版 | 利用者提供 `koebuta_fast_speak_concept.zip`（4ファイル） | コード・テスト・依頼文を収録。元READMEを `fast/DISTRIBUTED_README.md` に保存し、入口READMEとサンプルを追加 |

元CLI ZIPのSHA-256：`CFCD505FD83591A900D4BBAEE38301BC1D233D5485CE4ABB0C0AEC18AC203841`。

CLI原配布物のマニフェスト `cli/DISTRIBUTED_BUILD.json` のパスは元ZIP内の名前です。`README.md` は現在の `cli/DISTRIBUTED_README.md` に対応し、それ以外は `cli/` 以下の同名ファイルに対応します。原READMEは末尾改行も含めて元ZIPと同一のバイト列で保存します。整理後のREADMEなどを含む現在の構成は `cli/BUILD.json` で検証します。

元HTMLのSHA-256（改行正規化前）：`CEC4650DF3430C29D7DEAF68C15129991123AF7570E1721E184E2B7889308A72`。

元Fast版ZIPのSHA-256：`C921E30F0F3676FDDE39A4140808C0B708CCAD493A37746AE2CF6610398B547C`。コード・テスト・依頼文は末尾改行以外の内容を変更していません。

NotebookのHTML互換対応 [PR #1](https://github.com/karin-tsumugi-lab/koebuta-colab/pull/1) は照会時点でopen・draft・未マージです。headは `7658c8ac21c9d1bb5a468bc1ccfb7fcd18183ceb`。この一式には含めません。

## 過去の検証と今回の確認

CLI配布記録にはWindows回帰92件、WSL関連30件、配布ZIP単体のdry-run成功があります。仕上げ前の生成経路ではT4による28発話を3条件で生成・回収・検証済みという記録があります。v1.0.1最終版の新規GPU再生成は未実施です。

HTMLレビューにはコア27件、追加10件、Chromium試験の過去報告があります。実OSのディレクトリ選択、`file://` 起動、電源断の試験は未実施とされています。今回そのテスト群の再実行は行っていません。

Notebook公開版は非GPU試験と、実GPU・ブラウザー・音質の確認を区別しています。Notebook互換PRについて、チャットのCPU9件成功報告とPR本文の未実行記載には時点差があり、公開前にCI結果と照合する必要があります。

今回の整理後の検査結果は [VALIDATION.md](VALIDATION.md) を参照してください。
