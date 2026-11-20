# Koebuta Notebook v2（旧資料）

> Colabの無料枠・CU残高なしでの外部WebUI利用には追加制限があります。[Colab利用条件の注意](../docs/COLAB_USAGE.md) を確認してください。有料プランでも一般の禁止事項やリソース制限は残ります。

Irodori-TTSを利用し、シナリオJSONから話者ごとの朗読音声を作成する旧世代の生成専用ノートブックです。v3の生成には [CLI](../cli/README.md) を使用してください。操作手順は [v2操作ガイド](NOTEBOOK_V2_GUIDE.md)、全体の使い分けは [総合README](../README.md) を参照してください。

## 旧版の起動手順

このフォルダーの [Notebook v2をColabで開く](https://colab.research.google.com/github/karin-tsumugi-lab/koebuta-colab/blob/main/notebook/Koebuta_Notebook_v2.ipynb)。

1. `Koebuta_Notebook_v2.ipynb` をGoogle Colabで開き、GPUランタイムを選択します。
2. 冒頭の利用条件を確認し、セルを上から順に実行します。
3. 表示されたGradio URLへ、そのセルに表示された認証情報でログインします。
4. シナリオJSONを読み込み、声を設定して試聴・生成します。

外部Web UIを主に使う構成のため、Colab無料管理対象ランタイムでの利用は勧めません。詳細はノートブックと使い方を確認してください。共有URL・パスワードは公開しないでください。

シナリオ化は一人朗読・複数人朗読共通の [02 v0.3](02_CHAT_PROMPT.md) を使い、作品全体→場面→発話の順に演出します。一人朗読は一つの話者IDです。発話長20〜80文字は推奨範囲であり、内部生成片とは区別します。見出し類の `text` 改変は明示許可のある範囲だけで、本文・台詞は保持します。JSON交換形式v1とNotebook v2は別の版番号です。

旧Notebook v2は原文不一致を警告として表示し、生成は継続できます。許可済み見出し改変か意図しない本文差分かを確認してください。`source` は元原稿のまま保持します。CLIの新入口も `source` 提供時には原文不一致を警告します。`source` 未提供時は照合未実施です。いずれも原稿全体の確認は別途必要です。詳しくは[エディタ案内](../docs/EDITOR_GUIDE.md)を参照してください。

## 資料

| ファイル | 用途 |
|---|---|
| [NOTEBOOK_V2_GUIDE.md](NOTEBOOK_V2_GUIDE.md) | v2の操作方法、候補の比較・採用、作業保存 |
| [01_SPEC_SHEET.md](01_SPEC_SHEET.md) | シナリオJSONの仕様 |
| [02_CHAT_PROMPT.md](02_CHAT_PROMPT.md) | LLMへ原稿のシナリオ化を依頼する文章 |
| [03A_LONG_FORM_ADDON.md](03A_LONG_FORM_ADDON.md) | 長編向け追加指示 |
| [03B_AGENT_ADDON.md](03B_AGENT_ADDON.md) | ファイル操作エージェント向け追加指示 |
| [03C_READING_ADDON.md](03C_READING_ADDON.md) | 難読語・曖昧な括弧の読み調整 |
| [README_Koebuta_v1.00.md](README_Koebuta_v1.00.md) | 旧v1の履歴資料 |
| [LOCAL_DEVELOPMENT_HANDOFF.md](LOCAL_DEVELOPMENT_HANDOFF.md) | ローカル移植・今後の開発の引き継ぎ |

## 非GPUテスト

専用のPython仮想環境で実行してください。検証環境はPython 3.12です。

コマンドはリポジトリのルートで実行します。

```bash
python -m pip install -r notebook/requirements-dev.txt
python -m unittest -v test_notebook_v2.py test_notebook_v2_ui.py test_inspector_p0.py
```

v2の保存・復元、候補の生成・採用、画面構築とコールバックを確認します。音声モデル・GPU・公開サーバーはモックで置き換えます。旧版の読み変換に関する回帰試験は `notebook/test_merge_reading.py` に保持しています。2026-11-13に利用者からNotebook v2の生成試験完了の報告を受領しました。対象条件と今回の回帰試験は [絵文字対応の検証記録](../docs/EMOJI_RELEASE_VALIDATION.md) を参照してください。

## 管理するファイル

原稿・シナリオJSON・参照音声・生成音声・モデル・認証情報・キャッシュは登録しません。`.gitignore` は誤登録を減らす設定であり、登録前に `git diff --cached` で内容を確認してください。配布ZIPは必要に応じてGitHubのリリースへ添付します。

## 上流と利用条件

[Irodori-TTS](https://github.com/Aratako/Irodori-TTS) および関連モデルを利用します。上流コード・モデルのライセンスと利用条件、原稿・参照音声の権利を個別に確認してください。Koebuta独自部分は [Koebuta Responsible Use License 1.0](LICENSE) で提供します。商用利用・改変・再配布を許可しますが、無断の声の複製・なりすまし、詐欺、脅迫・嫌がらせ等の禁止用途があります。再配布時はライセンスと権利表示を保持してください。用途制限付きのソース公開であり、MITやOSI承認のオープンソースライセンスではありません。詳細はLICENSE本文が正です。

第三者のコード・モデルには各提供元の条件が適用されます。[第三者の権利表示](THIRD_PARTY_NOTICES.md)も確認してください。

## シナリオ編集と旧版の扱い

本文・読み・話者・演技・分割位置は [単一HTMLエディタ](../Koebuta_Scenario_Inspector_v0.1.6.html) で編集し、作品ZIPまたはJSONをv2へ読み込みます。

v1.00は旧版として通常の利用案内から外しています。旧ファイルは履歴の再現とv2ビルド用の元データとして保持します。`Koebuta_Colabv2.prototype.ipynb` は旧開発ファイルです。利用時は正式ファイル `Koebuta_Notebook_v2.ipynb` を選んでください。
