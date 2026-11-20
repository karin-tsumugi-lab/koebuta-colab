# Koebuta v3

原稿をシナリオに整え、Irodori-TTSで朗読を作ります。**原稿 → シナリオJSON → HTMLで確認 → CLIで検査・生成 → WAVを試聴**の順に進めます。

## 1. AIでシナリオを作る

チャット型AIに、[V3シナリオ作成プロンプト](docs/V3_SCENARIO_PROMPT.md)、[話者・感情などのJSON仕様](notebook/01_SPEC_SHEET.md)、朗読したい原稿を渡します。AIが確認した朗読範囲・声・演出の方針に答え、できたJSONを `scenario.json` として保存します。任せられる判断は「おまかせ」と伝えられます。

AIエージェントに生成まで任せる場合は、[AIエージェント向け制作手順](docs/AGENT_WORKFLOW.md)の依頼欄を使ってください。

## 2. HTMLでシナリオを確認する

[Scenario Inspector](Koebuta_Scenario_Inspector_v0.1.6.html)を手元のブラウザーで開き、`scenario.json` を読み込みます。話者、原文と読み上げ文、感情・演技、発話の区切りを確認し、編集したらJSONを保存します。🔖は追加ルビです。効果音素材を入れる位置などの作業指示は発話の `notes` に記録できます。[エディタの使い方](docs/EDITOR_GUIDE.md)

## 3. CLIで検査し、朗読を生成する

1. `scenario.json` と同じフォルダーに、[生成設定サンプル](cli/irodori_cli_examples/generate_settings.json)を `settings.json` としてコピーします。サンプルは声の説明から一人分の声を作る設定です。クローンを使う場合は参照WAVを保存し、CLI用設定の `voices` に指定します。[参照WAVの設定例](docs/AGENT_WORKFLOW.md#4-作品フォルダーと生成設定)
2. リポジトリ直下で、下のコマンドを実行します。発話ID、読み上げ文、話者、診断を確かめます。追加ルビの自動候補は `ruby_pending` に表示され、本生成時に判定されます。
3. 内容を確認したら、[CLIのGPU生成手順](cli/README.md#gpu生成)へ進みます。Colabの接続準備と本生成のコマンドはCLI案内にあります。

```bash
python cli/irodori_generate.py --scenario scenario.json --settings settings.json --dry-run
```

環境により `python` を `python3` に読み替えてください。構造や読みだけ試す場合は、同梱の [サンプルシナリオ](cli/irodori_cli_examples/generate_scenario.json)も使えます。

## 4. WAVを試聴する

出力先の `result.wav` は結合音声、`segments.zip` は発話IDで照合できる個別WAVです。誤読や演技を直した発話は、CLIの `--ids` で指定して再生成できます。

[v3シナリオ詳細仕様](docs/V3_SCENARIO_SPEC.md) · [ライセンス](LICENSE) · [第三者の権利表示](THIRD_PARTY_NOTICES.md)

Notebook版と [V3試作ガイド](V3_PROTOTYPE_GUIDE.md)は過去の資料です。
