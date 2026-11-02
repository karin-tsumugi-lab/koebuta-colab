# 整理後の確認（2026-11-02）

Windows / Python 3.14で、整理後の `cli/` 内だけを作業フォルダーとして以下を実行しました。

```text
python -B -m unittest test_irodori_generate test_cli_terminal -v
```

30件すべて成功。接続・GPU生成はモックを使用するCPU試験であり、実際のColab認証やGPU利用を行っていません。

```text
python -B irodori_generate.py --scenario irodori_cli_examples/generate_scenario.json --settings irodori_cli_examples/generate_settings.json --session narration-v1 --job chapter01 --out outputs/chapter01-cli --dry-run
```

終了コード0、標準出力に2発話の生成要求JSONを確認しました。指定した出力フォルダーは作成されていません。

NotebookのJSON構造と4つのコードセルのPython構文を確認しました。Notebookの回帰テスト、ブラウザー操作、モデル読み込み、実GPU生成は今回実行していません。

ローカルMarkdownリンクと配布ファイルの構成を点検しました。`docs/references/` は過去資料のためリンク点検対象外です。原CLI配布物のコード・サンプルと展開後のSHA-256を比較し、文書以外の一致を確認しました。

CLIの `BUILD.json` は整理後の文書を含むチェックサムへ更新し、元ZIPのマニフェストは `DISTRIBUTED_BUILD.json` に保存しました。HTMLは元ファイルと改行以外の一致を確認しました。

今回のコミットはこの整理一式のみを対象とし、作業フォルダーに既存の開発差分は含めません。GitHubへのプッシュは実施しません。

## Fast版の追加確認

利用者から受領した `koebuta_fast_speak_concept.zip` を静的に確認して収録しました。`fast/` 内で次を実行しました。

```text
python -B -m unittest discover -s tests -v
python -B speak_pipeline.py --input reply_example.txt --emit-json
python -B speak_pipeline.py --input reply_example.txt --plan-only
```

テスト18件中17件成功、1件スキップ。スキップは `numpy` / `soundfile` を必要とするモック音声結合の試験で、今回のPython環境には必要なライブラリがありません。過去READMEの18件成功と今回の結果を区別しています。サンプルは2発話のJSON変換と2件の生成単位を確認しました。実GPU推論・モデル取得・音質や速度の検証は行っていません。

## Colab利用条件の追記

2026-11-02、公式Colab CLIのLegal & Privacy、Colab追加利用規約、公式FAQを読み、総合README、CLIのREADME・AGENTS・トラブル対策、NotebookのREADMEへ注意を追記しました。原配布物のREADMEは履歴として保持しています。処理コードは変更していません。追記後にローカル文書リンクとCLIチェックサムを再確認しました。

## 原配布READMEの保存修正

公開確認用ZIPで、`cli/DISTRIBUTED_README.md` の末尾に原文より改行が1つ多く付いていました。修正して元ZIPのREADMEとバイト単位で一致させました。`DISTRIBUTED_BUILD.json` の全51項目を、READMEのみ保存名を対応させて検証しました。現在の `BUILD.json` の全55項目と、修正版ZIP全96ファイルのバイト一致も確認しました。旧ZIPは保持し、修正版ZIPを別名で作成しました。
