# Koebuta v2 — AIでIrodori-TTS用の演技指導を自動化するツール群

正式なNotebook版は **v2** です。[v2をColabで開く](https://colab.research.google.com/github/karin-tsumugi-lab/koebuta-colab/blob/main/notebook/Koebuta_Notebook_v2.ipynb) ／ [v2操作ガイド](notebook/NOTEBOOK_V2_GUIDE.md)。

Notebook v1.00は旧版として通常の利用案内から外し、今後の開発はv2へ集約します。旧ファイルは再現・移行とビルド用の履歴資料として保持しています。CLIとFastは、それぞれの利用案内から選べます。

Koebutaは、**AIを使ってIrodori-TTS用の演技指導を自動化する**ためのツール群です。原稿から話者・感情・読み・発話ごとの演技指示をシナリオJSONへ整理し、Irodori-TTSによる音声生成につなげます。

AIの判断は生成前に確認し、生成後は誤読・話者・声の一貫性・演技を試聴してください。演技指示どおりの表現が必ず得られるわけではありません。

このリポジトリは、Notebook版の単体公開に、CLI版・Fast版・HTMLエディタと関連文書を加えた統合構成です。

Google Colabの有料プランなどで、コンピューティングユニット（CU）を割り当てられているユーザーを前提としています。ただし、ローカル環境を構築して使うための関連文書も同梱しています。

## まずはここから
Irodoriで読ませたい原稿をLLM(チャット型AIのこと)にシナリオJSON化してもらいます。やり方は後述。
多くの場合はNotebook版が入口です。Google Colabで [Notebook v2](notebook/Koebuta_Notebook_v2.ipynb) を開き、GPUランタイムを選んでセルを上から実行し、表示された画面から作品ZIPまたはシナリオJSONを読み込んで使います。詳しい手順は [Notebook版の案内](notebook/README.md) と [v2操作ガイド](notebook/NOTEBOOK_V2_GUIDE.md) を参照してください。

## 実行環境の選び方

音声生成に使うGPUの場所で、入口が分かれます。

| 使うGPU | 入口 | 補足 |
| --- | --- | --- |
| Colab（画面から操作） | [Notebook版](notebook/README.md) | 標準の使い方です |
| Colab（手元のPCから命令） | [CLI版](cli/README.md) | 操作端末はWSL/Ubuntu、推論はColabのGPUです |
| 手元のPCのGPU | [ローカルGPU移植案](notebook/LOCAL_DEVELOPMENT_HANDOFF.md) | Notebookをローカル環境で動かすための移植手順です。未検証の作業案であり、動作保証はありません |

Fast版は手元のGPUで動かす単一話者向けの実装例です。HTMLエディタは音声生成を行わないため、実行環境を問いません。

## 使い分け

| 構成 | 使う場面 | 状態 |
| --- | --- | --- |
| [HTMLエディタ](Koebuta_Scenario_Inspector_v0.1.6.html) | シナリオ・読み・感情・演技を手元で編集 | v0.1.6を収録。[利用案内](docs/EDITOR_GUIDE.md) |
| [Notebook v2](notebook/README.md) | 声の設定、生成候補の比較・採用、完成音声の出力 | 正式版。シナリオ編集はHTMLエディタで行います |
| [CLI版](cli/README.md) | 準備済みシナリオから連続生成・回収 | v1.0.1を収録。生成設定は別JSON |
| [Fast版](fast/README.md) | AIの短い返答を単一話者で音声化する実装例 | コード・LLM用依頼文・テストを収録。実GPU推論は未検証 |

## 始め方

1. [シナリオ化の依頼文](notebook/02_CHAT_PROMPT.md) と [JSON仕様](notebook/01_SPEC_SHEET.md) を使い、LLMに原稿の話者・演技を整理させます。長編、ファイル操作エージェント、難読語には同フォルダーの `03A`、`03B`、`03C` の追加指示を組み合わせます。LLMはGeminiやChatGPT、Grok、Claude、Museなど、どんなLLMサービスでも利用可能なように作られています。ただし、LLMモデルごとに文書解釈結果には個性があります。
2. [HTMLエディタ](Koebuta_Scenario_Inspector_v0.1.6.html) で内容を確認・修正し、JSONを保存します。参照WAVを追加した場合は作品フォルダー保存またはZIP出力を使います。
3. [Notebook v2](notebook/Koebuta_Notebook_v2.ipynb) をColabで開いて声を試すか、[CLI手順](cli/README.md) に従って生成します。CLIのコマンドは `cli/` 内で実行します。
4. 完成WAV、発話別WAV、JSONを手元に保存し、試聴します。

Notebook v2はHTMLの `koebuta_settings`・参照WAVパス・TTS分割情報を読み込みます。CLIには別設定JSONが必要で、HTMLのTTS分割境界も引き継ぎません。[互換性の表](docs/EDITOR_GUIDE.md) を確認してください。

## 既知の不整合：発話の長さ

シナリオ化プロンプトが生成する発話単位（意味の塊）と、Irodori-TTSが安定して合成できる長さには開きがあります。極端に短い発話（10字未満程度）は合成が不安定になり、極端に長い発話はそのままでは生成できない場合があります。文字数は目安です。

現行版では受け取り側で対処しています。長文は生成側で分割（安全に分割できない場合は拒否）、短文は警告と手動結合、題名・著者名はシナリオ側で必要に応じてまとめます。Fast版には生成時の短文自動結合もあります。

将来のIrodori-TTSの更新で改善されうる前提で、この役割分担を据え置いています。実用上は、利用者がシナリオ化プロンプトを調整することで対処できます。原文を水増しせず、異なる話者を混ぜない範囲で発話を整え、試聴してください。

## Notebook v2とシナリオ編集

Notebook v2は生成専用です。本文・読み・話者・感情・演技・分割位置はHTMLエディタで修正して読み込み直してください。生成候補の比較・採用、再結合、作業状態の保存・復元はv2の画面から行えます。

Notebook版は声の試作・試聴・生成に利用できますが、同梱版の実GPU・ブラウザー受入確認は公開資料で未完了です。CLIでのGPU実績をNotebookの検証済み実績として扱わないでください。

## このリポジトリの構成

```text
koebuta-colab/
├── README.md
├── Koebuta_Scenario_Inspector_v0.1.6.html   # HTMLエディタ
├── cli/          # CLI版 v1.0.1のコード、サンプル、手順、AGENTS.md
├── notebook/     # 正式Notebook v2、仕様・依頼文、テスト、旧版資料
├── fast/         # Fast版。単一話者の読み上げ例、依頼文、サンプル、テスト
├── docs/         # エディタ案内、収録記録、検証範囲、過去レビュー
├── LICENSE
├── LICENSES/
└── THIRD_PARTY_NOTICES.md
```

Notebook版の本体・仕様書・依頼文・テストは `notebook/` に統一しています。旧ルート直下へのブックマークやColabリンクは、`notebook/` 以下のパスへ更新してください。

AIエージェントへCLI導入を依頼する場合は [cli/AGENTS.md](cli/AGENTS.md) と [cli/README.md](cli/README.md) を渡してください。WSL/Ubuntuは操作端末、推論先はColabのGPUです。Notebookの [ローカルGPU移植案](notebook/LOCAL_DEVELOPMENT_HANDOFF.md) とは導入経路が異なります。

## 利用条件と確認事項

**Colab CLIにもColabの利用規約が適用されます。** 無料・CU残高なしの管理ランタイムには、SSH等の遠隔操作や外部WebUI中心の利用への追加制限があります。CLIを制限回避の手段として使わず、利用形態とアカウント条件を確認してください。有料でも一般の禁止事項やリソース制限は残ります。[Colab利用条件の注意](docs/COLAB_USAGE.md) と、その中の公式規約・FAQを先に確認してください。

Koebuta独自部分は [Koebuta Responsible Use License 1.0](LICENSE) です。Irodori-TTSコード・モデル等には各提供元の条件が適用されます。[第三者の権利表示](THIRD_PARTY_NOTICES.md) と [CLIの権利表示](cli/THIRD_PARTY_NOTICES.md) も確認してください。原稿・参照音声を扱う権利と同意は利用者自身で確認してください。

Colabへ原稿・参照WAVを転送し、GPU利用枠を使用します。Notebookの共有URLと認証情報を公開しないでください。認証情報や作品データをGitへ登録しないでください。

収録元・検証範囲は [収録記録](docs/PROVENANCE.md)、残る確認事項は [確認一覧](docs/PUBLICATION_CHECKLIST.md) を参照してください。
