# Koebuta Colab 1.00

> Colabの無料枠・CU残高なしでの外部WebUI利用には追加制限があります。[Colab利用条件の注意](../docs/COLAB_USAGE.md) を確認してください。有料プランでも一般の禁止事項やリソース制限は残ります。

Irodori-TTSを利用し、シナリオJSONから話者ごとの朗読音声を作成するColabノートブックです。このフォルダーは公開mainのNotebook版を収録しています。全体の使い分けは [総合README](../README.md)、完成済みのCLI v1.0.1は [CLI利用案内](../cli/README.md) を参照してください。

## 起動

1. `Koebuta_Colabv1.00.ipynb` をGoogle Colabで開き、GPUランタイムを選択します。
2. 冒頭の利用条件を確認し、セルを上から順に実行します。
3. 表示されたGradio URLへ、そのセルに表示された認証情報でログインします。
4. シナリオJSONを読み込み、声を設定して試聴・生成します。

外部Web UIを主に使う構成のため、Colab無料管理対象ランタイムでの利用は勧めません。詳細はノートブックと使い方を確認してください。共有URL・パスワードは公開しないでください。

## 資料

| ファイル | 用途 |
|---|---|
| [USER_GUIDE_FAQ.md](USER_GUIDE_FAQ.md) | 操作方法、ルビ、分割・結合、保存時の注意 |
| [01_SPEC_SHEET.md](01_SPEC_SHEET.md) | シナリオJSONの仕様 |
| [02_CHAT_PROMPT.md](02_CHAT_PROMPT.md) | LLMへ原稿のシナリオ化を依頼する文章 |
| [03A_LONG_FORM_ADDON.md](03A_LONG_FORM_ADDON.md) | 長編向け追加指示 |
| [03B_AGENT_ADDON.md](03B_AGENT_ADDON.md) | ファイル操作エージェント向け追加指示 |
| [03C_READING_ADDON.md](03C_READING_ADDON.md) | 難読語・曖昧な括弧の読み調整 |
| [README_Koebuta_v1.00.md](README_Koebuta_v1.00.md) | 変更履歴、検証範囲と制限 |
| [LOCAL_DEVELOPMENT_HANDOFF.md](LOCAL_DEVELOPMENT_HANDOFF.md) | ローカル移植・今後の開発の引き継ぎ |

## 非GPUテスト

専用のPython仮想環境で実行してください。検証環境はPython 3.12です。

```bash
python -m pip install -r requirements-dev.txt
python test_merge_reading.py
```

この入口から既存の回帰テストも実行します。音声モデル・GPU・公開サーバーはモックで置き換えます。任意の実作品fixtureは同梱せず、該当試験はSKIPとなります。Colab実GPU、ブラウザー実操作、朗読品質の確認は別途必要です。

## 管理するファイル

原稿・シナリオJSON・参照音声・生成音声・モデル・認証情報・キャッシュは登録しません。`.gitignore` は誤登録を減らす設定であり、登録前に `git diff --cached` で内容を確認してください。配布ZIPは必要に応じてGitHubのリリースへ添付します。

## 上流と利用条件

[Irodori-TTS](https://github.com/Aratako/Irodori-TTS) および関連モデルを利用します。上流コード・モデルのライセンスと利用条件、原稿・参照音声の権利を個別に確認してください。Koebuta独自部分は [Koebuta Responsible Use License 1.0](LICENSE) で提供します。商用利用・改変・再配布を許可しますが、無断の声の複製・なりすまし、詐欺、脅迫・嫌がらせ等の禁止用途があります。再配布時はライセンスと権利表示を保持してください。用途制限付きのソース公開であり、MITやOSI承認のオープンソースライセンスではありません。詳細はLICENSE本文が正です。

第三者のコード・モデルには各提供元の条件が適用されます。[第三者の権利表示](THIRD_PARTY_NOTICES.md)も確認してください。

## 編集と保存の確認

内蔵エディタは補助的に扱ってください。重要な編集は [単一HTMLエディタ](../Koebuta_Scenario_Inspector_v0.1.6.html) を使い、[生成側との互換性](../docs/EDITOR_GUIDE.md) を確認してください。Notebookで編集した場合も、JSONを保存して再読込し、本文・読み・話者・感情・演技・間を確認してください。HTMLの拡張設定に対応するPR #1は、本収録版に含まれていません。

