# Koebuta Fast — 単一話者の自動読み上げ例

AIの返答を短い感情付き台本として受け取り、Koebuta v1 JSONへ変換して、参照WAVを使ったIrodori-TTS生成へ渡す独立パイプラインです。利用者提供の `koebuta_fast_speak_concept.zip` を収録しています。コードを変更せず、入口のREADMEとサンプルだけを整えました。[元のREADMEと発展構想](DISTRIBUTED_README.md) も残しています。

## GPUなしで試す

Python 3.11以降を推奨します。このフォルダーを作業フォルダーにして実行してください。次の処理は標準ライブラリだけで動作し、モデル取得・GPU生成・Colab接続を行いません。

```bash
python3 speak_pipeline.py --input reply_example.txt --emit-json
python3 speak_pipeline.py --input reply_example.txt --plan-only
```

Windowsでは `python3` を `python` に読み替えます。入力ファイルを省略すると標準入力を読みます。`--emit-json` と `--plan-only` は併用できません。

`--emit-json` は元の発話単位を持つ `schema_version: 1`、`speakers`、`segments` のJSONを出力します。`--plan-only` は音声生成時の分割・短文結合後の要求を表示します。AIに渡す書式は [SPEAK_PROMPT_JA.md](SPEAK_PROMPT_JA.md) の依頼文を参照してください。通常文章はneutralとして受け付けます。

## 音声生成

このFast版が動く環境に、互換性のあるIrodori-TTS、CUDA、モデルへのアクセス、`huggingface_hub`、`numpy`、`soundfile` 等が必要です。ローカルGPUまたは利用者が別途準備したGPU環境で実行します。Colab CLI版の接続・転送機能は使いません。

```bash
python3 speak_pipeline.py --input reply_example.txt --ref voice.wav --caption-file caption.txt --out speech_out_new --irodori-dir /path/to/Irodori-TTS
```

`voice.wav` は許諾のある参照音声、`caption.txt` は共通の声・話し方の説明です。captionは省略できます。参照音声は必須で、VoiceDesignへの自動切替はありません。`--seed` は既定314、`--steps` は20/40/60から選び、既定40です。モデルはコード内でIrodori v4.1-Smallのrevisionを指定しています。上流の任意の最新版との互換性を確認済みとは扱いません。

出力は `chunk_001.wav` 等と、連結した `speech.wav` です。処理中は `speech.partial.wav` を使います。**既存出力を拒否する実装ではないため、実行ごとに新しい `--out` を指定してください。** 生成失敗時に残る部分出力を完成音声として扱わないでください。

`--play` は `ffplay` を使って生成と並行して再生します。入力台本全体を先に読み込む方式で、LLMの出力途中から音声化するリアルタイム入力ではありません。

## 対応範囲と他構成との違い

- JSON入力は話者一覧が一人のものだけです。複数話者は生成前に停止します。
- `tts_text` を優先します。ルビの自動変換はなく、未展開ルビには完成した読み上げ文を用意してください。
- 生成用の単位だけを80文字目安で分割し、読みが15文字未満の短文を可能な範囲で隣へ結合します。絵文字は短文判定の文字数から除きます。元JSONは書き換えません。別の感情を結合した場合は、文字数の多い感情を採用します。speak_pipeline.py と emoji_tags.py を同じフォルダーに配置してください。
- `pause_after_ms`、区切り、空行情報の境界を跨ぐ短文結合は避けます。既定の発話間は280msで、最後の発話後には無音を付けません。空行情報は結合を防ぐために使われますが、Notebookと同じ1200msの空行休止を自動設定する実装ではありません。
- `koebuta_settings`、`reference_wav`、`koebuta_tts_parts` を生成設定・参照WAV・分割境界として自動取り込みません。参照WAVは `--ref` で指定します。HTML版の設定をそのまま再現する入口として案内しないでください。
- Colab接続・転送、GPU選択、複数話者、LLMの呼び出し、別モデルによる感情判定、完全自動復旧は含みません。

## 検証

```bash
python3 -m unittest discover -s tests -v
```

2026-11-02の今回のWindows / Python 3.14で、18件中17件が成功、1件は `numpy` / `soundfile` が利用できずスキップしました。スキップはモック音声の結合・休止時間の試験です。元READMEの「18件成功」は過去の環境での報告であり、今回の結果とは分けて扱います。

同梱サンプルのJSON変換・計画表示も確認しました。実GPU推論、上流APIとの接続、試聴による音質・遅延は今回未検証です。「Fast」は用途名であり、速度改善を実測済みという意味ではありません。
