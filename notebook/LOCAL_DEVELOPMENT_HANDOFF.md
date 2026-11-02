# Koebuta v1.00 — ローカル移行手順とAI開発エージェント向け作業指示

> この文書は手元のGPUで推論するための移植案です。WSLを端末としてColabのGPUへ生成を依頼する完成済みCLIの導入は [CLI利用案内](../cli/README.md) を参照してください。ローカルGPU・CUDAはColab CLIホストの必須条件ではありません。

この文書は **ローカル実行のための設計・移植手順** です。v1.00ノートブックはColab前提の実装を含むため、ローカルでの動作は未保証です。実際のGPU・依存関係の検証を行ってから利用してください。

## 1. ローカル化の基本方針

- まず **LinuxまたはWindows 11 + WSL2 Ubuntu + NVIDIA GPU** での動作を第一候補とします。Windowsネイティブ・CPU専用・AMD GPU・macOSは今回のノートブックでは未検証で、追加の設計判断が必要です。
- Google Colabの利用制限は、ローカルでの実行にはそのまま適用されませんが、Irodoriモデルの利用条件・著作権・声の許諾は引き続き守ってください。
- コードとシナリオJSONを分離します。`source` と `text` を勝手に書き換えず、既存データを上書きしないようにします。
- ローカル版ではGradioの `share=True` を既定で使用しません。ローカルホストだけにバインドし、インターネットへ公開しないことを原則にします。
- ユーザーデータ、音声素材、キャッシュ、モデルをソースリポジトリにコミットしないよう、`.gitignore` を先に整備します。

## 2. 実行前の確認

必要条件は固定的な数字ではなく **上流Irodori-TTSの対応環境と選んだモデル** に左右されます。以下を確認します。

1. 使用許諾：原稿、参照音声、モデルの規約を確認。
2. GPU：WSL2のUbuntu内で `nvidia-smi` を実行し、GPUを確認。CUDA利用可能なPyTorchが導入可能か調べる。
3. Python：上流の `requirements.txt` と選んだバージョンで依存パッケージを導入できるか確認。ColabのPython 3.13向けパッチはローカルで無条件に適用しない。
4. ストレージ：モデル・コーデック・一時WAV・長編の生成音声を保管できる余裕があるか確認。
5. ポート：Gradioが使用するローカルTCPポートをほかのサービスが利用していないか確認。

## 3. 基本的な準備コマンド（WSL2 Ubuntu例）

以下は準備例です。**実行後に対応するIrodoriのコミットとGPU環境を検証する必要があります。** 実際にローカル版が完成していることを意味しません。

```bash
# まずWSL2 Ubuntu側でGPUが見えるか確認
nvidia-smi

# 新規作業ディレクトリを用意（既存のファイルは上書きしない）
mkdir -p ~/dev/koebuta-local
cd ~/dev/koebuta-local

# プロジェクト用Python仮想環境（python3 / python3-venv が必要）
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# Irodori-TTSの公開ソース取得。コミットIDは後で記録・固定する
git clone https://github.com/Aratako/Irodori-TTS.git upstream/Irodori-TTS
git -C upstream/Irodori-TTS rev-parse HEAD

# 依存関係は上流の説明を確認したうえで導入する
python -m pip install -r upstream/Irodori-TTS/requirements.txt
python -m pip install --no-deps -e upstream/Irodori-TTS
python -m pip install 'gradio==6.5.1' pandas numpy soundfile nbformat regex

# PyTorch/CUDAが有効か確認。CUDA版PyTorchの導入方法は環境により異なる
python -c 'import torch; print(torch.__version__, torch.cuda.is_available())'
```

この準備だけで、現行のColabノートブックをそのまま実行できるわけではありません。**次の移植作業が必要**です。

## 4. Colab専用部分を分離する

| 現行箇所 | ローカルでの改修内容 |
|---|---|
| セル2の `IRODORI_DIR = Path('/content/Irodori-TTS')` | `KOEBUTA_IRODORI_DIR` などの環境変数・設定ファイルから取得 |
| セル2の `/content/koebuta_requirements_runtime.txt` | ローカルの一時領域かプロジェクト内の作業ディレクトリを使用 |
| セル4の `WORK = Path('/content/koebuta_work')` | 環境に依存しないユーザーデータディレクトリへ移す。モデルと同じリポジトリに置かない |
| セル2の都度 `git fetch` / `checkout --detach` | セットアップと起動を分離し、通常起動時には上流を更新しない |
| セル2の `nvidia-smi` 強制実行 | GPUを確認する段階でエラーを分かりやすくする。CPU起動はサポートする場合のみ別実装 |
| セル6の `model_device='cuda'` など | 実際のPyTorch/CUDAデバイスとメモリ要件を検証して設定可能にする |
| セル8の `demo.launch(share=True, auth=...)` | **既定は `share=False, server_name='127.0.0.1'`** に変更。意図的なLAN公開にも認証を必須にする |
| Notebookの複数セル構成 | `core`（JSON・台本）、`tts`（推論）、`ui`（画面）、`config`（環境設定）、`tests` へ分けることを推奨 |

モデル取得は公開Hugging Faceリポジトリの通常のダウンロード処理を使用します。オフライン運用にする場合は、**モデル・音声コーデック・依存パッケージを事前取得**し、`hf_hub_download()` の代わりにローカルファイルを指定します。APIの引数は利用するIrodoriコミットに合わせて確認してください。

## 5. ローカル化しても維持する仕様

- `01_SPEC_SHEET.md` の `schema_version: 1` を基本形式にする。未知のキーは読み込み可能なら保持し、編集後の書き出しでも破棄しない。
- 話者IDで声を区別。同名の別人物を誤って同じ話者へ統合しない。
- `text`（原文）は明示的な編集以外で変更しない。読み方は `tts_text` へ記録。
- 規模の固定上限をJSON仕様に持ち込まない。ただし実行環境での容量・時間・GPU利用制限は別途管理。
- 感情IDはJSONでは英語で保持し、UIでは絵文字と日本語を表示する。Irodoriへ渡すかどうかは画面設定に従う。
- 音声生成時の内部分割はシナリオを変更しない。UIでの一括分割・結合はプレビュー後の明示操作とし、Undoを可能にする。
- 異常値は可能な範囲で救済する一方、参照話者の欠落・原文の欠落などは音声生成前に止める。
- 再生成キャッシュは参照WAVの内容・文章・演技・絵文字・シード・ステップ数・モデル識別情報に結び付ける。
- 原稿全文 `source` がない場合、完全性を検証できたと偽らない。

## 6. AI開発エージェントに渡す依頼文（コピー可能）

> **作業対象：** Koebuta v1.00 ノートブックをローカルアプリへ移植する。まずコードと仕様・README・既存テストを読み、差分と作業計画を示す。元のノートブック、元原稿、生成済み音声、参照音声は読み取り専用として扱う。
>
> **目標：** Windows 11 + WSL2 Ubuntu + NVIDIA GPUで、ローカルホスト限定のGradio画面から標準シナリオJSONを読み込み、話者ごとの声を設定し、発話試聴・全編生成・WAV/JSON保存ができること。
>
> **実装方針：** 音声合成の前処理・状態管理・画面をモジュール分離する。既存３カラムUIの操作導線を維持する。音声生成設定は右カラムの最上段で常時表示する。長さ警告、単一発話の分割、個別結合、事前確認チェック付き一括調整、Undo、感情絵文字の表示と保存時の感情ID復元を維持する。
>
> **絶対条件：** 元データを勝手に削除・上書きしない。認証情報をリポジトリやログへ含めない。外部にWeb UIを公開しない。`git push` などの外部書き込みは、接続先・差分・権限の確認と利用者の承認を得てから実施する。
>
> **検証：** 既存の非GPUテストを先に実行し、失敗ログを記録する。JSON往復、同名話者、原文保全、ルビ・読み上げ文、短文・長文の任意調整、Undo、キャッシュの衝突回避、Gradioイベント完了までテストする。GPU実行は利用権限と消費量を確認してから短い試験を行う。
>
> **提出物：** 実行手順、依存バージョンと固定コミット、変更ファイル一覧、テストの実行コマンドと結果、未検証項目、既知の制限、取り消し手順をまとめる。未実行テストを成功と記載しない。

## 7. 段階的な受け入れ確認

1. **静的：** `python -m compileall` 相当の構文確認。JSON例とコードセルを解析できる。
2. **非GPU：** 既存テスト + 異常値・同名話者・短文・長文・感情絵文字・セッション分離の回帰テスト。
3. **UI：** Gradioの画面構築、操作時のエラー、右上の設定変更の効果を確認。セッション間で話者・音声を混ぜない。
4. **GPU（承認後）：** 短い試作文→少数発話→全編結合の順で検証。処理時間・VRAM・ファイル保存先を記録。
5. **リリース：** バージョンと変更履歴更新、機密情報・大きなWAV・キャッシュの混入チェック、Git差分のレビュー、利用者承認後のプッシュ。

## 8. Gitへの反映手順（接続先がある場合のみ）

リポジトリがまだない場合は、先にプライベート／パブリックの公開範囲を決めてGitリポジトリを作成します。シナリオ原稿や声の素材を公開してよいか、必ず確認してください。

```bash
# 作業リポジトリに移動後
git status --short
git remote -v
git diff --check
git diff --stat

# 加えるファイルは名前を明示する（音声・原稿・秘密ファイルは加えない）
git add Koebuta_Colabv1.00.ipynb 01_SPEC_SHEET.md 02_CHAT_PROMPT.md \
   03A_LONG_FORM_ADDON.md 03B_AGENT_ADDON.md 03C_READING_ADDON.md \
   USER_GUIDE_FAQ.md LOCAL_DEVELOPMENT_HANDOFF.md README_Koebuta_v1.00.md \
   test_koebuta_without_gpu_v1.00.py test_koebuta_stability_v1.00.py
git diff --cached --stat
git diff --cached --check

# GPU実機テスト等の受け入れ確認後、内容を見てコミットする
git commit -m 'Add safe manual splitting and batch adjustment confirmation'
git push
```

**今の配布物にはリモートのGitリポジトリ情報がありません。** ここに記した手順は例であり、コミットやプッシュを実行したことを意味しません。


## v1.00安定化の引き継ぎ

- 自動分割は目標文字数付近の段落・文末・改行・読点等を優先し、候補がなければ文字数付近へフォールバックする。ルビの親文字と読み、絵文字の書記素単位は分割しない。原文と読みの連結一致を検査する。
- 分割・結合の要確認印は任意拡張 `segments[].koebuta_edit` として保持する。確認済みとUndoも移植する。
- 表示元のページ・ID・作品状態をセッションへ保存する。保存先をページ入力欄だけから決めない。検証エラー時は入力表を維持する。
- Undoは `project/voices/sample` のスナップショットを一括復元。参照WAVと試作WAVは一意なファイル名にして上書きしない。旧WAVの自動削除は行っていないため、長期運用での掃除は別途設計する。
- Gradioの操作と生成は共通の `concurrency_id` に直列化する。複数セッションでも待機が発生する。生成完了時には開始時の作品状態と比較し、変更後の作品へ古い結果を入れない。
- モデル・codec revision・上流commitをキャッシュキーへ含める。上流コードの既定取得先はmainのままで、取得したcommitを記録する。GPU動作確認済みの上流commitはまだ決まっていない。
- 既存試験は `python test_koebuta_without_gpu_v1.00.py`、追加試験は `python test_merge_reading.py`。後者は前者も実行する。`nbformat/pandas/numpy/soundfile/gradio==6.5.1/regex` が必要。任意の実作品fixtureがない場合はSKIPと表示する。人工45行fixtureは追加試験内に常備する。
- 今回はCLI・オフラインHTML版を追加していない。HTML版はGit反映後に別作業とする。Colab GPUとブラウザー実操作の受け入れ確認を残す。


## v1.00 ルビ説明と最終追加試験

手動結合でルビの対象が結合境界をまたいで広がる場合、各行の読みを `tts_text` に保持する。例：`東` と `京《きょう》` の結合は、原文を `東京《きょう》`、読みを `東きょう` として保持する。

非GPU回帰試験の全体は `python test_merge_reading.py` で実行する。この入口から `test_review_fixes.py` → `test_force_length.py` → `test_batch_fix.py` → `test_koebuta_stability_v1.00.py` → `test_koebuta_without_gpu_v1.00.py` を順に呼び出す。実作品fixtureがない試験はSKIP。実GPU・ブラウザー操作・音質の確認は別途必要。

入力元と `text_format` を指定し、曖昧な括弧の意図はLLMと利用者が確認する。原文の記法を統一せず、必要な発話の完成した `tts_text` に読みを指定する。なろうの丸括弧を意味に従って判別する機能をKoebutaへ追加したものではない。具体的な依頼方法は `02_CHAT_PROMPT.md`・`03C_READING_ADDON.md`、対応範囲は `USER_GUIDE_FAQ.md` を参照。

