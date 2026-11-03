# 声の候補比較と採用 ― 実行用

Koebuta CLI（`irodori_generate.py`）で、seedだけを変えた試聴候補を作り、利用者に選んでもらう手順。設計提案は含まない。生成数は依頼された候補数を上限とし、追加生成は利用者の意向を確認する。

## 手順

1. 入力を揃える：一人朗読、`voiceMode=design`、同じ試聴文・同じ声質説明・同じモデル・steps=40。短すぎる相づちだけを避け、比較できる長さの文章を使う。比較が目的なら演技・感情はOFF。既存の参照WAVは指定しない。
2. seed以外が完全に同一な設定JSONを、候補の数だけ作る。全件 `--dry-run` を通す（dry-run成功は「検査合格」であって生成成功ではない）。
3. 最初の候補だけ `--new --gpu T4` で新規セッション＋環境準備。以後は同じ `--session` に `--skip-prepare` で続け、候補ごとに別の `--job` と **新しい `--out`** を使う。同時実行はしない。既存の出力フォルダーは上書きせず、再実行は拒否される。
4. 途中でセッションを止めない。詳細ログに「ロード済みのIrodoriを再利用します」が出れば常駐モデルの再利用が確認できる。
5. 追加候補の予定がなければ、最終候補に `--stop-after-download` を付ける。終了後は `pipeline.json` の停止状態も確認する。別途手動停止する場合は対象ランタイムの識別情報を照合し、不明なら停止せず報告する。
6. 候補ごとに終了コード、`AUDIO_READY`、`pipeline.json` の status/verification、完成WAVの存在を確認し、候補番号・seed・WAVの場所・成否を一覧で利用者へ出す。失敗や未確認を成功として並べない。
7. 採用は利用者が決める。選ばれた候補のWAV・seed・声質説明・モデル・steps・ハッシュを記録し、そのWAVを本番の共通参照WAV（クローン参照）にする。別の短い本文でも生成・試聴し、声の引き継ぎを確認する。

## 実行例

作業パスは**実環境に合わせて置き換える**。以下はCLIがPATHから呼べる環境の例。別の実行ファイルを明示する必要がある場合だけ `YOMIBUTA_COLAB_BIN` にその環境の絶対パスを設定する。セッション名・job・outは今回専用の未使用名にする。

```bash
cd /path/to/koebuta-colab/cli

# 候補1：新規セッション＋準備（まだ止めない）
python3 irodori_generate.py --scenario scenario.json --settings settings_seed1.json \
  --session voice-search --job s1 --out run_seed1 --new --gpu T4

# 候補2〜9：同一セッション。jobとoutは候補ごとに変える
python3 irodori_generate.py --scenario scenario.json --settings settings_seed2.json \
  --session voice-search --job s2 --out run_seed2 --skip-prepare

# 最終候補：追加生成の予定がなければ、回収成功後に停止
python3 irodori_generate.py --scenario scenario.json --settings settings_seed10.json \
  --session voice-search --job s10 --out run_seed10 --skip-prepare --stop-after-download
```

設定JSONの例（他候補では `seed` の値だけを変える）:

```json
{ "title": "声の候補比較", "voiceMode": "design", "reading": "shared",
  "baseCaption": "落ち着いた明瞭な声の成人女性。やや低めで、ゆったりと丁寧に話す。感情を抑えた、乾いた響き。",
  "acting": false, "emotion": false, "narratorEmotion": false,
  "ttsModel": "Aratako/Irodori-TTS-v4.1-Small", "seed": 1, "steps": 40, "pause": 0.28 }
```

## 提供資料による実測報告

添付資料 `VOICE_CANDIDATE_FLOW_SLIM.md` では、2026-11-02、T4、試聴文68字×1発話で次の実測値が報告されている。**実行ログは添付されておらず、本説明書の更新時には再測定・独立検証していない**。別環境での所要時間や短縮率の保証に使わない。

- 初回（セッション作成＋環境準備込み）：4分11秒
- 2件目以降（モデル常駐のまま）：44〜55秒／件
- 10候補の総所要：約11分半
- 初回実行前後の**アカウント残量差分**：0.06 CU。準備を含む期間の値であり、初回ジョブ単独の消費とは断定しない。以後もCLIが表示する残量はアカウント全体の値として扱う。

## やってはいけないこと

- 未実装の引数（`--seeds` 等）を作って実行しない。入口は現行CLIのみ。
- 接続が切れても同じ生成をすぐ再実行しない。まず `pipeline.json` と `recovery_command.json` を確認し、回収コマンドがあればそれで元の成果物を回収する。回収失敗＝生成失敗ではない。
- 本人（利用者）が選んでいない候補を「採用済み」にしない。seedは再現用の情報であり、別の文章でも同じ声になる保証ではない。クローン参照は声を引き継ぐために使い、完全に同じ声になる保証とは分ける。
- 「接続1回」「一括回収1回」と報告しない。現行CLIでは呼出し・転送・回収は候補ごとに発生する。
- セッションを保持し続ける場合は、CU消費が続くことを利用者へ伝える。無期限に放置しない。中断時に「自動で止まったはず」と仮定しない。

## 元の実行環境だけの注意

- 提供資料のVMでは、出口プロキシが空ボディPOSTのContent-Lengthを落とすため、venv内の `colab_cli/client.py` に最小ボディを付与するパッチを適用したとの記録がある。この変更は**他の環境へ自動適用しない**。同じ環境を再構築する場合も、症状と元の変更内容を確認してから対処する。
- 元の環境で認証済みという記録は、別環境の認証を保証しない。各環境で認証状態を確認し、認証情報を表示・保存・転送しない。

Colabの利用・外部送信・GPU利用の前提と承認は [AIエージェント向け運用指示](../AGENTS.md) に従う。この手順は参照WAVを使わない声候補比較用であり、既存の参照WAV割当を上書きする指示ではない。
