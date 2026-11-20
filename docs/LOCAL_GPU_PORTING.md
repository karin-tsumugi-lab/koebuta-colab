# Koebuta v3をローカルGPUへ移植する

この案内は、手元のGPUで Irodori-TTS を試し、Koebutaのシナリオから連続生成する処理を移植する方向けです。Koebuta v3の配布CLIは生成をColabに送ります。シナリオの編集と `--dry-run` による生成前の検査は手元で行えます。[Colabで生成する手順](../cli/README.md)

## 1. 手元でIrodori-TTSを試す

LinuxまたはWindowsのWSL2 UbuntuとNVIDIA GPUを例に進めます。推論用のPython、PyTorch、GPUドライバーの組み合わせは、使用するIrodori-TTSの版に合わせてください。モデル、コーデック、出力WAVを保存できる空き容量も確認します。[Irodori-TTS公式のインストール手順](https://github.com/Aratako/Irodori-TTS#installation)

1. 推論を実行する端末で `nvidia-smi` を実行し、GPUが見えることを確認します。
2. Irodori-TTSの公式手順でGPU対応の環境を用意します。NVIDIA CUDA 12.8構成の例は `uv sync --extra cu128` です。その環境で `uv run --no-sync python -c "import torch; print(torch.cuda.is_available())"` を実行し、`True` が出ることを確認します。
3. 公式の試し方で短い一文をWAVにして試聴します。クローンでは利用権限のある参照WAVを使います。参照WAVなしで声を指定する場合はVoiceDesignで試せます。[公式の単発生成例](https://github.com/Aratako/Irodori-TTS#simple-inference) · [VoiceDesignの例](https://github.com/Aratako/Irodori-TTS#voicedesign)

## 2. Koebutaのシナリオから生成計画を確認する

HTML Inspectorでシナリオを確認し、Koebutaのルートから以下を実行します。実作品では例のパスを作品の `scenario.json` と `settings.json` に置き換えます。

```bash
python3 cli/irodori_generate.py \
  --scenario cli/irodori_cli_examples/generate_scenario.json \
  --settings cli/irodori_cli_examples/generate_settings.json \
  --dry-run
```

`requests` で発話ID、合成に渡す文と設定、参照WAV、発話後の間を確認します。作者ルビと手動確定した追加ルビは計画に反映されます。未判定の追加ルビが `ruby_pending` に出た場合、短い手動試験ではInspectorで読みを確定してから再検査すると、合成に使う文を確認できます。[ルビとシナリオの仕様](V3_SCENARIO_SPEC.md)

## 3. 連続生成を移植する

- [生成計画とシナリオ検査](../cli/irodori_cli/faithful.py) を再利用し、Colabランタイムの準備、ファイル転送、実行・回収の代わりに、手元の推論環境で生成を開始する入口を用意します。
- [推論とWAV出力の実装](../cli/irodori_cli/faithful_worker.py) では、Irodori-TTSの配置先が `/content/Irodori-TTS` に固定されています。配置先と実行環境はローカルの設定から受け取り、[使用コードとモデルの固定版](../cli/irodori_cli/environments.py) を起点に、チェックポイント、コーデック、トークナイザー、透かしの互換性を確認します。追加ルビの `auto` に対応する場合は、推論環境で既存の類似度判定も接続します。
- 発話ID、話者と参照WAVの対応、ルビ、感情・演技指示、休止を維持します。個別WAVは発話IDを先頭に付け、シナリオ順に休止を挟んで結合します。`notes` は編集用として保存し、合成入力から除外します。
- 短い数発話で個別WAVと結合WAVを生成し、読み、話者、順序、休止を試聴で確かめます。発話IDを指定した部分再生成も試してから長編へ進みます。

V3のローカルGPUへの移植は未実装で、この案内に沿った連続生成の実機検証は未実施です。
