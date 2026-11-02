# Koebuta — AIでIrodori-TTS用の演技指導を自動化するツール群

Koebutaは、**AIを使ってIrodori-TTS用の演技指導を自動化する**ためのツール群です。原稿から話者・感情・読み・発話ごとの演技指示をシナリオJSONへ整理し、Irodori-TTSによる音声生成につなげます。

AIの判断は生成前に確認し、生成後は誤読・話者・声の一貫性・演技を試聴してください。演技指示どおりの表現が必ず得られるわけではありません。

## 使い分け

| 構成 | 使う場面 | この一式での状態 |
| --- | --- | --- |
| [HTMLエディタ](Koebuta_Scenario_Inspector_v0.1.6.html) | シナリオ・読み・感情・演技を手元で編集 | v0.1.6を収録。[利用案内](docs/EDITOR_GUIDE.md) |
| [Notebook版](notebook/README.md) | 声の試作、試聴、画面からの音声生成 | 公開mainのv1.00を収録。HTML互換PRは未収録 |
| [CLI版](cli/README.md) | 準備済みシナリオから連続生成・回収 | v1.0.1を収録。生成設定は別JSON |
| [Fast版](fast/README.md) | AIの短い返答を単一話者で音声化する実装例 | コード・LLM用依頼文・テストを収録。実GPU推論は未検証 |

このフォルダーは公開に向けて整理したローカルの一式です。公開中の [koebuta-colab](https://github.com/karin-tsumugi-lab/koebuta-colab) のmainはNotebook中心の構成で、この一式と同一ではありません。

## 始め方

1. [シナリオ化の依頼文](notebook/02_CHAT_PROMPT.md) と [JSON仕様](notebook/01_SPEC_SHEET.md) を使い、LLMに原稿の話者・演技を整理させます。長編、ファイル操作エージェント、難読語には同フォルダーの `03A`、`03B`、`03C` の追加指示を組み合わせます。
2. [HTMLエディタ](Koebuta_Scenario_Inspector_v0.1.6.html) で内容を確認・修正し、JSONを保存します。参照WAVを追加した場合は作品フォルダー保存またはZIP出力を使います。
3. [Notebook](notebook/Koebuta_Colabv1.00.ipynb) をColabで開いて声を試すか、[CLI手順](cli/README.md) に従って生成します。CLIのコマンドは `cli/` 内で実行します。
4. 完成WAV、発話別WAV、JSONを手元に保存し、試聴します。

**受け渡しには注意が必要です。** HTMLの `koebuta_settings`・参照WAVパス・TTS分割情報は、同梱Notebook mainとCLI v1.0.1で自動的に同じ意味で使われるものではありません。CLIには別設定JSONが必要で、HTMLのTTS分割境界も引き継ぎません。[互換性の表](docs/EDITOR_GUIDE.md) を先に確認してください。

## 既知の不整合：発話の長さ

シナリオ化プロンプトが生成する発話単位（意味の塊）と、Irodori-TTSが安定して合成できる長さには開きがあります。極端に短い発話（10字未満程度）は合成が不安定になり、極端に長い発話はそのままでは生成できない場合があります。文字数は目安です。

現行版では受け取り側で対処しています。長文は生成側で分割（安全に分割できない場合は拒否）、短文は警告と手動結合、題名・著者名はシナリオ側で必要に応じてまとめます。Fast版には生成時の短文自動結合もあります。

将来のIrodori-TTSの更新で改善されうる前提で、この役割分担を据え置いています。実用上は、利用者がシナリオ化プロンプトを調整することで対処できます。原文を水増しせず、異なる話者を混ぜない範囲で発話を整え、試聴してください。

## Notebook内エディタについて

Notebook内の編集機能は補助的に扱ってください。画面にエラーがなくても、表の編集・分割・結合が意図どおり反映・保存されたと過信せず、保存したJSONを再度開いて本文・読み・話者・感情・演技・間を確認してください。重要な編集には独立HTMLエディタを推奨します。元ファイルの複製を残してください。

Notebook版は声の試作・試聴・生成に利用できますが、同梱版の実GPU・ブラウザー受入確認は公開資料で未完了です。CLIでのGPU実績をNotebookの検証済み実績として扱わないでください。

## フォルダー

```text
koebuta/
├── README.md
├── Koebuta_Scenario_Inspector_v0.1.6.html
├── cli/          # v1.0.1のコード、サンプル、手順、AGENTS.md
├── notebook/     # 公開mainのNotebook、既存仕様・依頼文、テスト
├── fast/         # 単一話者の読み上げ例、依頼文、サンプル、テスト
├── docs/         # エディタ案内、棚卸し、出典、過去レビュー
├── LICENSE
├── LICENSES/
└── THIRD_PARTY_NOTICES.md
```

AIエージェントへCLI導入を依頼する場合は [cli/AGENTS.md](cli/AGENTS.md) と [cli/README.md](cli/README.md) を渡してください。WSL/Ubuntuは操作端末、推論先はColabのGPUです。Notebookの [ローカルGPU移植案](notebook/LOCAL_DEVELOPMENT_HANDOFF.md) とは導入経路が異なります。

## 利用条件と公開前の確認

**Colab CLIにもColabの利用規約が適用されます。** 無料・CU残高なしの管理ランタイムには、SSH等の遠隔操作や外部WebUI中心の利用への追加制限があります。CLIを制限回避の手段として使わず、利用形態とアカウント条件を確認してください。有料でも一般の禁止事項やリソース制限は残ります。[Colab利用条件の注意](docs/COLAB_USAGE.md) と、その中の公式規約・FAQを先に確認してください。

Koebuta独自部分は [Koebuta Responsible Use License 1.0](LICENSE) です。Irodori-TTSコード・モデル等には各提供元の条件が適用されます。[第三者の権利表示](THIRD_PARTY_NOTICES.md) と [CLIの権利表示](cli/THIRD_PARTY_NOTICES.md) も確認してください。原稿・参照音声を扱う権利と同意は利用者自身で確認してください。

Colabへ原稿・参照WAVを転送し、GPU利用枠を使用します。Notebookの共有URLと認証情報を公開しないでください。認証情報や作品データをGitへ登録しないでください。

収録元・検証範囲は [収録記録](docs/PROVENANCE.md)、残る確認事項は [公開前チェック](docs/PUBLICATION_CHECKLIST.md) を参照してください。
