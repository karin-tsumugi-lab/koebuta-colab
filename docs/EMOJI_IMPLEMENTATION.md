# 絵文字拡張の実装記録

ブランチは codex/emoji-expansion。新設IDは cli/irodori_cli/emoji_tags.py の ADDITIONAL を参照する。tools/sync_emoji_catalog.py でFast、Inspector、ノートブックへ埋め込む。

## 動作の確認

- 新ID worried は😟へ変換され、旧ID tired は😮‍💨の先頭付与を維持する。
- 45種のタグを台帳に収録。LLM向け指示文は31種の発話追加と10種の位置指定を案内し、自動選択から外す4種の理由を掲載。
- 原文と読みの間にイベントが追加された長文を分割しても、読みを連結すると元の入力に一致する。対応付けできない本文変更は既存の手動分割案内を返す。
- InspectorではTTS text欄を選択後、効果音一覧からカーソルへ挿入できる。手動の除外タグを保存し理由を警告する。
- FastとInspectorの短文判定の目安は15文字。絵文字を短文判定の長さから除く。

## コマンド・試験結果

- python -m unittest test_emoji_expansion test_inspector_p0 -q は13件成功。
- python -m unittest discover -s fast/tests -q は18件実行、1件skip、残り成功。
- python -m unittest discover -s cli -q は30件成功。
- ノートブック内のPythonセルは互換試験でコンパイル検査済み。新カタログの全IDを通常CLI・Fast・ノートブックで照合済み。

GPUによる新しい生成とInspectorの実ブラウザー操作は未実施。今回の対象は独立したkoebuta-v2-repoで、外側の開発用WebUIとは別の配布構成である。
