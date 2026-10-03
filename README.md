# Realtime Voice Changer

Change your microphone sound in real time on macOS and send it to a virtual audio device for calls or recording.

`Microphone → Python audio effects → BlackHole 2ch → calling / recording app`

## Requirements

- macOS and Python 3.10+.
- PortAudio for PyAudio.
- BlackHole 2ch installed as a virtual audio device.
- Microphone permission for the terminal or Python launcher.

## Install and run

With Homebrew available, install the native audio dependency:

```sh
brew install portaudio
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python voice_changer.py --list-devices
python voice_changer.py
```

Install BlackHole 2ch separately before starting the audio stream. The script selects a physical input microphone and a BlackHole output automatically. In the calling or recording app, select **BlackHole 2ch** as its microphone.

To select devices explicitly, use an index from `--list-devices` or part of the device name:

```sh
python voice_changer.py --input 1 --output 'BlackHole'
```

`run_voice_changer.command` uses `.venv/bin/python` when available, falls back to Python on PATH, and accepts the same arguments. Set `PYTHON_BIN` to use another interpreter.

## Presets

| Number | Effect |
| --- | --- |
| 0 | Clean |
| 1 | Lower and rougher |
| 2 | Higher and brighter |
| 3 | Very high |
| 4 | Robot |
| 5 | Demon with echo |
| 6 | Radio / telephone |

Enter a number while running to switch presets. Press Q followed by Enter, or Ctrl-C, to exit.

## Troubleshooting

If no input is available, check microphone permissions and `--list-devices`. If no output is found, verify BlackHole is installed. The program does not change another app's microphone setting: select BlackHole in that app yourself. Adjust `--block-ms` to trade latency against audio stability.

Audio processing is local. These are signal-processing effects, not voice cloning. Live audio behavior depends on the selected hardware and driver configuration.

See [the Russian usage notes](README_RU.md) for additional routing examples.

## License

[MIT](LICENSE) © 2026 sairex53.
