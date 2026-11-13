# Notebook v2の正式版切り替え

利用者の指示に基づき、Notebookの正式な利用入口を Koebuta_Notebook_v2.ipynb に統一する。総合README、Notebook README、Inspectorからの受け渡し案内をv2へ更新する。操作の正本は notebook/NOTEBOOK_V2_GUIDE.md。

v1.00は通常の起動案内から退け、旧Notebookの先頭にv2へのリンクを表示する。旧ファイルは履歴の再現、CPU互換試験、v2ビルド元として残す。既存のv2ビルダーはv1の先頭コードセルを利用するため、削除すると再ビルドができなくなる。

v1向け絵文字拡張PR #5は採用を終了する。そこで確認された修正事項と聴取に基づく絵文字仕様は、今後のv2対応で参照する。

## 検証記録

変更は利用案内と旧版表示。以下を確認した。

- `python tools/build_notebook_v2.py` は成功。生成する全コードセルの構文を検査し、正式Notebookの生成結果に差分が生じないことを確認した。
- `.venv-v2/Scripts/python.exe -X utf8 -m unittest test_notebook_v2 test_notebook_v2_ui test_inspector_p0 -q` は23件成功。Gradio 6.5.1、Python 3.14.3。GradioのイベントループにResourceWarningが出るが試験は終了コード0。
- 制限付き実行ではWindows内部ソケットの作成でUI構築が停止したため、通常の実行環境で再実行して成功した。標準Python側にはGradioがなく、UIを含まない21件は成功した。
- 総合README、Notebook README、Inspector案内のローカルMarkdownリンクは全件存在する。正式Colabリンクはmainの `notebook/Koebuta_Notebook_v2.ipynb` を指す。
- v1 Notebookの先頭に旧版表示とv2リンクがある。旧v1の操作・履歴資料にも冒頭に移行案内がある。
- `git diff --check` を実行し、余分な末尾空行を修正した。

今回の切り替えでは、v2での新たなGPU生成・実ブラウザー操作・Driveのランタイム再起動試験は未実施。
