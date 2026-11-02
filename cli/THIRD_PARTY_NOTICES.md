# 使用する外部ソフトウェア・モデル

Yomibutaは外部ツールを組み合わせるα版です。この一覧はYomibuta自体の公開ライセンスを定めるものではありません。モデル重み・ユーザーの参照音声はこのリポジトリに含めません。

| 対象 | ライセンス・利用条件 | 公式資料 |
|---|---|---|
| Irodori-TTS コード | MIT。保存した依存定義はcommit 59be938c99d48b5653ca5aa3fdd0cddaa56940e5由来 | https://github.com/Aratako/Irodori-TTS |
| Irodori-TTS-v4.1-Small | MIT表記。本人の同意、なりすまし・欺瞞防止等、モデルカードの利用条件も確認してください | https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small |
| Qwen3-8B-GGUF（Q4_K_M） | Apache-2.0 | https://huggingface.co/Qwen/Qwen3-8B-GGUF |
| Laya ライブラリ | Apache-2.0 / Convai Innovations | https://github.com/NandhaKishorM/laya |
| convaiinnovations/laya-multilingual | Apache-2.0 | https://huggingface.co/convaiinnovations/laya-multilingual |
| DACVAE ライブラリ | Apache-2.0 | https://github.com/facebookresearch/dacvae |
| Aratako/Semantic-DACVAE-Japanese-32dim | MIT。確認済みIrodori版の既定codec | https://huggingface.co/Aratako/Semantic-DACVAE-Japanese-32dim |
| llama-cpp-python | MIT | https://github.com/abetlen/llama-cpp-python |
| Gradio（過去のNotebook UI試作） | Apache-2.0 | https://github.com/gradio-app/gradio |
| Colab CLI | 別途導入する外部ツール。配布元のライセンスとColabのサービス条件を確認してください | https://github.com/googlecolab/google-colab-cli |

Gemini APIは外部サービスです。APIの利用条件・料金が適用され、選択した場合は原稿がGoogleへ送信されます。

## 同梱物

- Irodoriの依存定義とlockファイル: dependency_snapshot/irodori/。対応するMIT本文は third_party/Irodori-TTS-MIT.txt。元の著作権表示を保持しています。
- LayaのApache本文: third_party/Laya-Apache-2.0.txt。取得元・取得日・SHA256は third_party/provenance.json。以前の調査用ソースコピーはローカルに残し、今後のGit登録対象から外しました。
- 長文fixture: irodori_cli_artifacts/longtext_gemini/README.md に由来と用途を記載しています。外部ツールやモデルのライセンスを原稿・音声へ一律に適用するものではありません。

実行時に取得される版が変わる可能性があります。配布・公開範囲を広げる際は、その版のLICENSE、NOTICE、モデルカードを改めて確認してください。
