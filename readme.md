# SillyTavernでIrodori-TTSを使用する拡張
Irodori-TTS側にAPIサーバを拡張し、Silly側は専用のゲートウェイを作成します

OpenAI互換APIより柔軟な設定を拡張できます

# Silly側のインストール
拡張機能をインストールから、 https://github.com/Ebycow/SillyTavern-Irodori-TTS-Extension.git を指定して追加

TTSメニューから"Irodori TTS"を指定してEnabled、ボイスマップのDefault Voiceを指定するか、キャラクターにボイスを指定する

# Irodori TTS側
動作するIrodori TTS https://github.com/Aratako/Irodori-TTS のフォルダ上にこのリポジトリをクローンしてapi_server.pyを実行

refディレクトリにref_[chara_name].mp3など音声ファイルを配置するとSilly側にマッピング可能な音声キャラクターとして認識される


実行の例：
```
uv run ./SillyTavern-Irodori-TTS-Extension/api_server.py --hf-checkpoint Aratako/Irodori-TTS-500M-v2 --host 0.0.0.0 --ref-dir ./SillyTavern-Irodori-TTS-Extension/ref 
```