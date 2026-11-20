# 03B ファイル操作可能なエージェント向け追加指示（Koebuta v3）

ファイル操作・コマンド実行が可能なAIエージェントへ渡す場合の補足です。具体的な実行・検証・回収手順は [AIエージェント向け制作手順](../docs/AGENT_WORKFLOW.md) に従います。

- シナリオ作成時は [02_CHAT_PROMPT.md](02_CHAT_PROMPT.md) の順序（全体理解 → 1往復確認 → 全体・場面演出 → 発話分割 → JSON出力）と、[01_SPEC_SHEET.md](01_SPEC_SHEET.md) のデータ仕様を適用します。
- 出力トークンとファイルサイズ節約のため、追加ルビがない発話の `koebuta_added_ruby` や変更のない `tts_text` は省略可能です。`source` を含める場合は改変前の元原稿を保持し、見出し改変の許可・変更前後・発話IDは `NOTES.md` に記録します。
- シナリオ作成後は必ず `python3 cli/irodori_generate.py --scenario scenario.json --settings settings.json --dry-run` で構文・ルビ位置・解決後の読みを検証します。依頼範囲が「シナリオ作成まで」の場合はここで報告して完了し、勝手にGPU生成を開始しないでください。
