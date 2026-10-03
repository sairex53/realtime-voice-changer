# RealtimeVoiceChanger

Меняет голос в реальном времени через BlackHole:

`физический микрофон -> Python effects -> BlackHole 2ch -> Telegram / Voice Recorder`

## Запуск

1. Открой `./run_voice_changer.command`.
2. Выбери пресет цифрой.
3. В Telegram выбери микрофон `BlackHole 2ch`.
4. Для Voice Recorder/Voice Memos выбери в macOS: `System Settings -> Sound -> Input -> BlackHole 2ch`.

## Пресеты

- `0` - чистый: без эффекта
- `1` - злой: ниже + хрип
- `2` - веселый: выше + ярко
- `3` - смешной: очень выше
- `4` - робот: металл + дрожь
- `5` - демон: очень ниже + эхо
- `6` - радио: телефонный

Во время работы можно ввести другой номер пресета и нажать Enter. Выход: `q` + Enter или `Ctrl-C`.

## Если выбран не тот микрофон

Показать устройства:

```bash
cd realtime-voice-changer
python3 voice_changer.py --list-devices
```

Запустить вручную с конкретными номерами из своего списка:

```bash
python3 voice_changer.py --input НОМЕР_МИКРОФОНА --output НОМЕР_BLACKHOLE
```

## Если хочешь слышать себя

В `Audio MIDI Setup` можно сделать `Multi-Output Device`, где включены `BlackHole 2ch` и твои наушники/колонки. Тогда запускай:

```bash
python3 voice_changer.py --output "Multi-Output Device"
```

Приложения всё равно должны слушать `BlackHole 2ch` как микрофон.

## Важно

macOS не даёт Python незаметно заменить все системные input-устройства. Чтобы приложение слышало изменённый голос, оно должно использовать `BlackHole 2ch` как микрофон. Программа сама берёт реальный микрофон, меняет голос и отправляет результат в BlackHole.

Если Terminal/Python спросит доступ к микрофону, разреши. Если запроса не было и звука нет: `System Settings -> Privacy & Security -> Microphone`.
