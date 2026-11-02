# Koebuta Notebook × Scenario Inspector v0.1.6：仕様整合・修正項目

作成日：2026-11-02
対象：`karin-tsumugi-lab/koebuta-colab` / `Koebuta_Colabv1.00.ipynb` と `Koebuta Scenario Inspector v0.1.6`
状態：**調査・実装項目の整理のみ。ノートブック本体は変更していない。**

## 0. 基本原則

- `scenario.json`（`schema_version: 1`）を作品フォルダの単一の正本とする。`source` と各 `text` はTTSの都合で書き換えない。
- `koebuta_settings`、話者 `reference_wav`、発話 `koebuta_tts_parts`、`koebuta_edit`、`koebuta_merge_backup`、`blank_line_pause_ms` は既存スキーマv1の**任意拡張フィールド**として扱う。既存JSONを読めなくしない。
- 編集・表示の互換性（Notebook UI）よりも、**音声生成結果がInspectorで意図した設定・境界・休止を反映すること**を優先する。
- 現行Notebookは読み込み・書き出し時に `_extras` で未知の項目を多く保持するが、**生成時に拡張項目を意味づけしない**。保持と実行対応は別問題。
- 元のNotebookで未指定だった設定のデフォルトや画面UIの既存選択は、移行時に不用意に上書きしない。

## 1. P0：音声生成の仕様互換（必須）

### N-01：`koebuta_settings` をランタイムへ反映

**対象**：ロード後の設定解決、Notebook UI初期値、`build_plan()`、`resolve_pauses()` 呼び出し元。

| 設定 | Inspector v0.1.6の初期値 | Notebook側の処理 |
|---|---:|---|
| `reading_mode` | `cast` | `cast` → 話者別音声、`shared` → 共用音声。Notebookの内部 `reading` と対応づける |
| `use_emotion` | `true` | 感情絵文字を合成テキストへ付けるか |
| `use_acting` | `false` | 演技指示をキャプションに含めるか |
| `narrator_emotion` | `false` | 地の文にも絵文字を付与するか |
| `seed` | `314` | 合成のseed |
| `steps` | `40` | 推論ステップ数 |
| `default_pause_ms` | `280` | 共通の発話後休止 |
| `default_blank_line_pause_ms` | `1200` | 空行時の既定休止（拡張） |
| `default_text_format` | `none` | 各発話に `text_format` がない場合の読み変換方式 |
| `shared_reference_wav` | `null` | `shared` 時の参照WAVパス |

- 優先順位は明文化する：原則 **明示的なNotebook UIでの変更 > JSONの `koebuta_settings` > 互換デフォルト**。ただし「UIが単に初期表示した値」と「ユーザーが変更した値」は区別する。最も単純なのはロード時にJSONでUIを初期化し、実行時にUIの値を使う方式。
- JSONに `koebuta_settings` がない旧形式は今までどおり開けること。旧Notebookの `reading` 既定値は `shared`、Inspectorの新規既定値は `cast` なので、**無指定時に勝手に配役へ切り替えない**。
- 設定の型・範囲と未知キーは検証する。未知キーは保持するが生成には影響させない。

### N-02：作品フォルダ基準の参照WAV解決

**対象**：読み込み経路、話者データ、参照WAV選択、`build_plan()` の `voices` 引数構築。

- `speakers.<speaker_id>.reference_wav = "voices/<name>.wav"` を`scenario.json`の親ディレクトリから解決する。
- `reading_mode=shared` なら `koebuta_settings.shared_reference_wav` を採用し、`cast` なら各使用話者の `reference_wav` を使う。
- 絶対パス、`..`、バックスラッシュ混在による脱出、シンボリックリンクによる作品外参照は拒否。フォルダ外へのアクセスを黙認しない。
- 欠落・読込不能・WAVデコード失敗は合成開始前に一覧で提示。未設定の音声を `voice_caption` から自動生成する挙動を勝手に追加しない。
- Colabアップロード方式では元の親フォルダ情報が失われるため、作品フォルダ/Driveのパスを指定する入口を設ける。既存のNotebook音声選択UIは手動上書き手段として残してよい。

### N-03：`koebuta_tts_parts` を合成分割の正本として尊重

**対象**：`validate_project()`、`build_plan()` の `split_text(spoken,140)` 呼出し。

- 発話に `koebuta_tts_parts` がなければ従来どおり `tts_text` またはルビ変換後の本文を `split_text` する。
- `koebuta_tts_parts` があれば **2片以上の非空文字列**であること、かつ **`''.join(parts) == tts_text`** が完全一致することを検証する。不整合なら警告だけで進まず生成を止める。
- 有効なpartsがある場合、Notebook側の自然分割を優先せず、ユーザーの指定したpartsを**順序どおり生成単位**とする（140字上限等のモデルの実制約がある場合は個別片を追加分割し、その理由を明示）。
- 音声合成単位IDは `t010#1`, `t010#2` のように親発話ID＋片番号で決定的に生成し、キャッシュキーの衝突を防ぐ。既存IDとの衝突を検査する。
- 感情絵文字付与は現在の `build_plan()` と同じく親発話の**最初の生成片にのみ**付与（将来変更する場合は別仕様）。休止は**最後の生成片のみ**適用し、中間片は0ms。演技・声・seed・stepsは同じ親発話の値を使う。
- `text` と `source` は重複・切断・変更しない。partsだけを編集した場合の `tts_text` 再構築方針は、Inspectorと同じく連結値を正本へ反映する。
- 短文警告は親発話だけでなく**生成片ごと**にも行う。

### N-04：休止の優先順位をInspectorに統一

**対象**：`resolve_pauses()`、設定の読み込み・検証。

| 状態 | 適用する休止 |
|---|---|
| `pause_after_ms` が明示されている | 指定値（`0` を含む） |
| 間に `separator` がある | 区切りの休止を、直前の発話に対し既定値と比較して適用（明示値がある場合は優先） |
| `blank_lines_after > 0` で `blank_line_pause_ms` が指定されている | その発話に指定された空行時の休止 |
| `blank_lines_after > 0` で個別指定なし | `max(default_pause_ms, default_blank_line_pause_ms)`（初期1200ms） |
| 上記以外 | `default_pause_ms`（初期280ms） |

- `blank_line_pause_ms` / `default_blank_line_pause_ms` は拡張項目。Inspectorでは列を隠しているがJSONでは保持する。
- 明示 `0`、連続separator、発話先頭・末尾separator、空行とseparatorの競合をそれぞれテストする。
- Notebookの既存 `resolve_pauses()` は既定1200msの空行は扱うが、個別空行時間とJSON内の共通時間の扱いを拡張する必要がある。

## 2. P1：データ保全・安全確認

### N-05：独自フィールドの往復保持を回帰試験で保証

- `koebuta_settings`（rootの `_extras`）、`reference_wav`（speakerの `_extras`）、`koebuta_tts_parts` / `koebuta_merge_backup` / `blank_line_pause_ms`（segmentの `_extras`）を、ロード→保存・編集→保存の両方で保持。
- `koebuta_edit` の `actions`、`needs_review`、`forced`、`fallback` を保持。Notebookが独自操作でアクションを追加する場合も未知の属性を失わない。
- Notebookで行結合・行分割を実行した時、構造が変わる発話の拡張項目を黙って消さない。`koebuta_merge_backup` 付きの行やparts付きの行を旧来ロジックで処理するときは、**対応処理または処理拒否**にする。
- Notebookからのエクスポートで `source` が創作・省略・変更されないことを確認。

### N-06：強制結合済み発話の演出情報について警告

- Inspectorの `koebuta_merge_backup` は、強制結合に取り込まれた発話／separatorの情報を保持する履歴であり、**生成時に復元・再読込するべき本文ではない**。
- `koebuta_edit.forced` が真、または `koebuta_merge_backup` に複数話者が含まれ、`reading_mode=cast` の場合、先頭話者の声で全体が読まれることを明示して確認を求める（処理停止／確認方式はUIで決定）。
- 取り込まれた行の感情・演技・中間休止は現在の1発話設定へ吸収されるため、生成前警告で可視化する。

### N-07：`source` の部分照合とJSON検査を移植／整合

- Notebookには既に順序付きの `source` 部分照合がある。Inspectorと同様に**完全一致の証明ではない**と明示。
- `koebuta_tts_parts` はsourceに存在する本文として照合せず、対応する親の `text` だけ検査する。
- 必須項目、未知話者、重複ID、空の本文、未知emotionや未変換ルビ等のエラー種別を現行のValidatorへ追加・整合。

## 3. P2：操作UIの整合（Notebookに編集機能を残す場合）

### N-08：結合・分割UI

- HTML版の**TTS内部だけの分割**をNotebookで編集できるようにするなら、発話の表示を親行＋partsにし、選択したTTS片の編集／隣接片の再結合／分割解除に対応。
- 通常結合は同話者・演技・感情・原文隣接・休止等を検査。後続行の未知属性が失われる場合は拒否する。
- 明示的な強制結合では、話者・空行・区切り・明示休止等の差異を確認し、先頭話者／感情／演技、末尾休止を採用。元の各行の完全データを `koebuta_merge_backup` へ残す。
- 自動整形の短文/長文判定は設定できるが、判定値自体はInspector v0.1.6では **JSONへ保存しないUI状態**。NotebookもJSONに無断追加しない。
- 操作成功後の選択解除、検査結果・操作ボタンの上部固定、Undo/RedoはUX整合として別スプリント扱い。音声生成の互換性には必須ではない。

### N-09：休止表示UI

- 発話の休止時間は、計算した有効msを表示。ラベルは `共通`、`空行有`、`個別指定`（separator由来は `区切り`）。
- 自動計算した値を無条件で `pause_after_ms` に書き込まない。数値をユーザーが編集したときだけ明示し、個別指定を解除する操作を用意。
- 空行数や空行時のmsは標準一覧に独立列を出さず、必要なら詳細欄で扱う。

### N-10：ファイル保存時の安全性

- Notebook側でもワークフォルダへの書き込み前に外部更新の有無を調べる（ハッシュ/mtime）。既存データに上書きするならバックアップとエラー復旧を設計。
- Inspector v0.1.6でも、外部更新との競合検出・強制終了時の多ファイル完全トランザクションは未実装。Notebook対応が済んでもエディタ側の残存リスクは別途管理する。

## 4. 既存Notebook関数との対応表

| 関数 / 領域 | 変更の必要性 |
|---|---|
| `normalize_scenario()` | 任意拡張の正規化前検証、各値の取扱いを明確化。既存 `_extras` 保持は活用 |
| `export_scenario()` | 任意拡張の保持をテスト。構造変更時の欠落を禁止 |
| `validate_project()` | `koebuta_tts_parts` の完全一致、WAVの利用可能性、生成前の強制結合警告など |
| `reading()` | 現行の決定的変換を基本維持。Inspectorとの結果差を別テストで抽出 |
| `split_text()` | parts未指定時のみ使用。parts指定時の強制分割方針を追加 |
| `resolve_pauses()` | JSON共通時間・空行個別時間の適用 |
| `build_plan()` | settings反映、WAVルーティング、partsと生成単位の決定、最終片休止 |
| `request_key()` / キャッシュ | parts境界変更時の単位ID・キャッシュ再利用の正否を確認 |
| `_safe_auto_merge()` / `merge_row_with_next()` / `_safe_auto_split()` / `split_single_row()` | 任意拡張の処理保護。UI編集を残す場合に新方式を移植 |
| UI（Gradio） | 設定のロード・表示・編集、WAV選択、検査表示。全面移植は必須ではない |

## 5. 最低限の受け入れテスト

1. Inspector v0.1.6で保存した `schema_version:1` JSONがNotebookで無損失ロード・保存できる。
2. `koebuta_tts_parts`を持つ発話は、指定した片数・順序・文字列で合成プランへ展開され、全文を二重読みしない。
3. partsの連結が `tts_text` と異なる場合、合成開始前にエラーで止まる。
4. 既存partsなしJSONは従来の `split_text()` 処理を維持する。
5. 朗読方式 `shared/cast`、各WAV・共用WAV、感情・演技の各スイッチがJSONから読み取られる。
6. 各休止：共通280ms、空行既定1200ms、空行個別、明示0ms、separator連続、TTS分割の最終片のみ休止を検査する。
7. 強制結合済みで複数話者が `koebuta_merge_backup` にある場合は演出変更を警告する。バックアップは合成しない。
8. NotebookでJSONを再出力しても、`source`、`koebuta_tts_parts`、`reference_wav`、未知属性と結合バックアップを失わない。
9. `sakurano_kino_shitaniwa_koebuta_B.json` を回帰入力とし、長文 `t010` をInspectorでTTS分割したJSONを読み込んで、指定どおりの生成片になることを検査する。
10. Pythonの `reading()` とInspectorの `reading()` のルビ・Unicode境界の差を代表ケースで比較し、差が残る場合は明示する。

## 6. 推奨実装順と影響範囲

1. **P0**：JSON設定読込とバリデーション → partsによる `build_plan` → 休止時間 → WAVフォルダ解決。
2. **P1**：拡張フィールドの往復保持 → 強制結合警告 → 実作品回帰テスト。
3. **P2**：Notebook側の編集画面・操作系を必要性に応じて追加。CLIとInspectorの役割を二重化しない。

**実装開始前に決めること**：Notebook既存の声・生成UIとJSON値が競合した際の優先順位、140字を超える明示partsの扱い、WAV配置をColabへ渡す方法。どれも推測で実装せず、小さな結合テストと仕様確認で確定する。

