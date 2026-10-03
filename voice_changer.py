#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable

import numpy as np

try:
    import pyaudio
except ImportError as exc:
    raise SystemExit(
        "PyAudio не установлен. Установи зависимости:\n"
        "  python3 -m pip install -r requirements.txt"
    ) from exc


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    short: str
    pitch: float = 1.0
    gain: float = 1.0
    drive: float = 0.0
    tone: float = 0.0
    ring_hz: float = 0.0
    ring_depth: float = 0.0
    tremolo_hz: float = 0.0
    tremolo_depth: float = 0.0
    bit_depth: int = 0
    echo_ms: float = 0.0
    echo_mix: float = 0.0
    echo_feedback: float = 0.0
    gate: float = 0.0025


PRESETS: dict[str, Preset] = {
    "0": Preset("0", "чистый", "без эффекта"),
    "1": Preset("1", "злой", "ниже + хрип", pitch=0.78, gain=1.25, drive=2.8, tone=-0.45),
    "2": Preset("2", "веселый", "выше + ярко", pitch=1.18, gain=1.05, tone=0.45, tremolo_hz=5.0, tremolo_depth=0.10),
    "3": Preset("3", "смешной", "очень выше", pitch=1.45, gain=1.0, tone=0.35, ring_hz=8.0, ring_depth=0.12),
    "4": Preset("4", "робот", "металл + дрожь", pitch=0.97, gain=1.1, drive=1.4, ring_hz=38.0, ring_depth=0.78, bit_depth=7),
    "5": Preset("5", "демон", "очень ниже + эхо", pitch=0.58, gain=1.15, drive=3.4, tone=-0.65, echo_ms=105.0, echo_mix=0.24, echo_feedback=0.28),
    "6": Preset("6", "радио", "телефонный", pitch=1.0, gain=1.25, drive=1.8, tone=0.85, bit_depth=8),
}


class ModulatedPitchShifter:
    """Low-latency delay-line pitch shifter for live voice effects."""

    def __init__(self, sample_rate: int, min_delay_ms: float = 14.0, max_delay_ms: float = 70.0) -> None:
        self.sample_rate = sample_rate
        self.min_delay = max(1, int(sample_rate * min_delay_ms / 1000.0))
        self.max_delay = max(self.min_delay + 2, int(sample_rate * max_delay_ms / 1000.0))
        self.delay_range = self.max_delay - self.min_delay
        self.buffer = np.zeros(self.max_delay + 4096, dtype=np.float32)
        self.write_pos = 0
        self.phase = 0.0

    def _read_delay(self, delay_samples: float) -> float:
        size = self.buffer.size
        read_pos = self.write_pos - delay_samples
        base = math.floor(read_pos)
        frac = read_pos - base
        i0 = base % size
        i1 = (i0 + 1) % size
        return float(self.buffer[i0] * (1.0 - frac) + self.buffer[i1] * frac)

    def _delay_from_phase(self, phase: float, factor: float) -> float:
        if factor >= 1.0:
            return self.max_delay - phase * self.delay_range
        return self.min_delay + phase * self.delay_range

    def process(self, x: np.ndarray, factor: float) -> np.ndarray:
        if abs(factor - 1.0) < 0.015:
            return x.copy()

        y = np.empty_like(x)
        step = abs(factor - 1.0) / float(self.delay_range)
        size = self.buffer.size

        for idx, sample in enumerate(x):
            self.buffer[self.write_pos] = float(sample)

            phase_a = self.phase
            phase_b = (self.phase + 0.5) % 1.0
            delay_a = self._delay_from_phase(phase_a, factor)
            delay_b = self._delay_from_phase(phase_b, factor)

            win_a = math.sin(math.pi * phase_a) ** 2
            win_b = math.sin(math.pi * phase_b) ** 2
            y[idx] = self._read_delay(delay_a) * win_a + self._read_delay(delay_b) * win_b

            self.phase = (self.phase + step) % 1.0
            self.write_pos = (self.write_pos + 1) % size

        return y


class ToneFilter:
    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.low = 0.0

    def process(self, x: np.ndarray, tone: float) -> np.ndarray:
        if abs(tone) < 0.01:
            return x

        cutoff = 1500.0 if tone < 0 else 2600.0
        alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / self.sample_rate)
        low = self.low
        lowpassed = np.empty_like(x)

        for idx, sample in enumerate(x):
            low += alpha * (float(sample) - low)
            lowpassed[idx] = low

        self.low = low
        amount = min(1.0, abs(tone))
        if tone < 0:
            return x * (1.0 - amount) + lowpassed * amount

        high = x - lowpassed
        return np.clip(x + high * (0.9 * amount), -1.0, 1.0)


class Echo:
    def __init__(self, sample_rate: int, max_delay_ms: float = 900.0) -> None:
        self.sample_rate = sample_rate
        self.buffer = np.zeros(int(sample_rate * max_delay_ms / 1000.0) + 1, dtype=np.float32)
        self.pos = 0

    def process(self, x: np.ndarray, delay_ms: float, mix: float, feedback: float) -> np.ndarray:
        if delay_ms <= 1.0 or mix <= 0.001:
            return x

        delay = min(self.buffer.size - 1, max(1, int(self.sample_rate * delay_ms / 1000.0)))
        y = np.empty_like(x)
        size = self.buffer.size

        for idx, sample in enumerate(x):
            read_pos = (self.pos - delay) % size
            delayed = self.buffer[read_pos]
            y[idx] = sample + delayed * mix
            self.buffer[self.pos] = sample + delayed * feedback
            self.pos = (self.pos + 1) % size

        return y


class VoiceProcessor:
    def __init__(self, sample_rate: int, preset: Preset) -> None:
        self.sample_rate = sample_rate
        self.preset = preset
        self.pitch = ModulatedPitchShifter(sample_rate)
        self.tone = ToneFilter(sample_rate)
        self.echo = Echo(sample_rate)
        self.ring_phase = 0.0
        self.tremolo_phase = 0.0

    def set_preset(self, preset: Preset) -> None:
        self.preset = preset

    def _oscillator(self, hz: float, n: int, phase_attr: str) -> np.ndarray:
        phase = getattr(self, phase_attr)
        step = 2.0 * math.pi * hz / self.sample_rate
        values = np.sin(phase + step * np.arange(n, dtype=np.float32))
        setattr(self, phase_attr, float((phase + step * n) % (2.0 * math.pi)))
        return values.astype(np.float32, copy=False)

    def process(self, x: np.ndarray) -> np.ndarray:
        preset = self.preset
        y = x.astype(np.float32, copy=True)

        rms = float(np.sqrt(np.mean(y * y))) if y.size else 0.0
        if rms < preset.gate:
            y *= 0.20

        y *= preset.gain
        y = self.pitch.process(y, preset.pitch)

        if preset.drive > 0.01:
            drive = preset.drive
            y = np.tanh(y * drive) / math.tanh(drive)

        if preset.ring_hz > 0.0 and preset.ring_depth > 0.0:
            carrier = self._oscillator(preset.ring_hz, y.size, "ring_phase")
            y *= (1.0 - preset.ring_depth) + preset.ring_depth * carrier

        if preset.tremolo_hz > 0.0 and preset.tremolo_depth > 0.0:
            trem = self._oscillator(preset.tremolo_hz, y.size, "tremolo_phase")
            y *= 1.0 - preset.tremolo_depth * 0.5 + preset.tremolo_depth * 0.5 * trem

        if preset.bit_depth > 0:
            levels = float(2 ** preset.bit_depth)
            y = np.round(y * levels) / levels

        y = self.tone.process(y, preset.tone)
        y = self.echo.process(y, preset.echo_ms, preset.echo_mix, preset.echo_feedback)

        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak > 0.96:
            y *= 0.96 / peak

        return np.nan_to_num(y, copy=False, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)


def device_name(device: dict) -> str:
    return str(device.get("name", "")).strip()


def list_devices(pa: pyaudio.PyAudio) -> list[dict]:
    devices: list[dict] = []
    for index in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(index)
        devices.append(info)
    return devices


def print_devices(pa: pyaudio.PyAudio) -> None:
    print("\nAudio devices:")
    for d in list_devices(pa):
        print(
            f"  {int(d['index']):2d}: {device_name(d)} | "
            f"in={int(d['maxInputChannels'])} out={int(d['maxOutputChannels'])} "
            f"rate={int(d['defaultSampleRate'])}"
        )


def resolve_device(pa: pyaudio.PyAudio, spec: str, *, need_input: bool) -> int:
    devices = list_devices(pa)
    if spec.isdigit():
        index = int(spec)
        info = pa.get_device_info_by_index(index)
        channels = info["maxInputChannels"] if need_input else info["maxOutputChannels"]
        if channels <= 0:
            kind = "input" if need_input else "output"
            raise SystemExit(f"Устройство #{index} не имеет {kind}-каналов.")
        return index

    needle = spec.lower()
    matches = [
        int(d["index"])
        for d in devices
        if needle in device_name(d).lower()
        and (d["maxInputChannels"] if need_input else d["maxOutputChannels"]) > 0
    ]
    if not matches:
        raise SystemExit(f"Не нашёл устройство по имени: {spec!r}")
    return matches[0]


def choose_input_device(pa: pyaudio.PyAudio, requested: str | None) -> int:
    if requested:
        return resolve_device(pa, requested, need_input=True)

    try:
        default = pa.get_default_input_device_info()
        if default["maxInputChannels"] > 0 and "blackhole" not in device_name(default).lower():
            return int(default["index"])
    except OSError:
        pass

    for d in list_devices(pa):
        name = device_name(d).lower()
        if d["maxInputChannels"] > 0 and "blackhole" not in name:
            return int(d["index"])

    raise SystemExit("Не нашёл физический input-микрофон. Проверь подключение микрофона.")


def choose_output_device(pa: pyaudio.PyAudio, requested: str | None) -> int:
    if requested:
        return resolve_device(pa, requested, need_input=False)

    for d in list_devices(pa):
        if d["maxOutputChannels"] > 0 and "blackhole" in device_name(d).lower():
            return int(d["index"])

    raise SystemExit(
        "Не нашёл BlackHole как output-устройство.\n"
        "Установи BlackHole 2ch или запусти с --output и номером нужного виртуального выхода."
    )


def resample_linear(x: np.ndarray, frames_out: int) -> np.ndarray:
    if x.size == frames_out:
        return x.astype(np.float32, copy=False)
    if x.size == 0:
        return np.zeros(frames_out, dtype=np.float32)
    if x.size == 1:
        return np.full(frames_out, float(x[0]), dtype=np.float32)

    src = np.arange(x.size, dtype=np.float32)
    dst = np.linspace(0.0, float(x.size - 1), frames_out, dtype=np.float32)
    return np.interp(dst, src, x).astype(np.float32)


def menu() -> None:
    print("\nPresets:")
    for key in sorted(PRESETS):
        p = PRESETS[key]
        print(f"  {p.key} - {p.name}: {p.short}")
    print("Во время работы можно ввести номер пресета и Enter. q + Enter = выход.\n")


def ask_preset(default: str = "1") -> Preset:
    menu()
    choice = input(f"Выбери пресет [{default}]: ").strip() or default
    while choice not in PRESETS:
        choice = input("Нет такого пресета. Введи цифру из списка: ").strip()
    return PRESETS[choice]


def stdin_controller(processor: VoiceProcessor, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            line = input().strip().lower()
        except EOFError:
            return
        if line == "q":
            stop.set()
            return
        if line in PRESETS:
            processor.set_preset(PRESETS[line])
            p = PRESETS[line]
            print(f"Preset: {p.key} - {p.name} ({p.short})")


def open_streams(
    pa: pyaudio.PyAudio,
    input_index: int,
    output_index: int,
    block_ms: float,
) -> tuple[pyaudio.Stream, pyaudio.Stream, int, int, int, int, int, int]:
    input_info = pa.get_device_info_by_index(input_index)
    output_info = pa.get_device_info_by_index(output_index)

    input_rate = int(input_info["defaultSampleRate"])
    output_rate = int(output_info["defaultSampleRate"])
    input_channels = max(1, min(2, int(input_info["maxInputChannels"])))
    output_channels = max(1, min(2, int(output_info["maxOutputChannels"])))
    input_frames = max(64, int(input_rate * block_ms / 1000.0))
    output_frames = max(64, int(output_rate * block_ms / 1000.0))

    input_stream = pa.open(
        format=pyaudio.paFloat32,
        channels=input_channels,
        rate=input_rate,
        input=True,
        input_device_index=input_index,
        frames_per_buffer=input_frames,
        start=False,
    )
    output_stream = pa.open(
        format=pyaudio.paFloat32,
        channels=output_channels,
        rate=output_rate,
        output=True,
        output_device_index=output_index,
        frames_per_buffer=output_frames,
        start=False,
    )
    return input_stream, output_stream, input_rate, output_rate, input_channels, output_channels, input_frames, output_frames


def run(args: argparse.Namespace) -> int:
    pa = pyaudio.PyAudio()
    try:
        if args.list_devices:
            print_devices(pa)
            return 0

        input_index = choose_input_device(pa, args.input)
        output_index = choose_output_device(pa, args.output)
        input_info = pa.get_device_info_by_index(input_index)
        output_info = pa.get_device_info_by_index(output_index)

        preset = PRESETS[args.preset] if args.preset else ask_preset()
        processor = VoiceProcessor(int(output_info["defaultSampleRate"]), preset)

        input_stream, output_stream, input_rate, output_rate, input_channels, output_channels, input_frames, output_frames = open_streams(
            pa, input_index, output_index, args.block_ms
        )

        print("\nRouting:")
        print(f"  Microphone input : #{input_index} {device_name(input_info)} ({input_rate} Hz)")
        print(f"  Processed output : #{output_index} {device_name(output_info)} ({output_rate} Hz)")
        print(f"  Active preset    : {preset.key} - {preset.name} ({preset.short})")
        print("\nВ Telegram/Voice Recorder выбери input: BlackHole 2ch.")
        print("Если нужна запись системно: macOS System Settings -> Sound -> Input -> BlackHole 2ch.")
        print("Стоп: Ctrl-C или q + Enter.\n")

        stop = threading.Event()
        controls = threading.Thread(target=stdin_controller, args=(processor, stop), daemon=True)
        controls.start()

        input_stream.start_stream()
        output_stream.start_stream()

        while not stop.is_set():
            raw = input_stream.read(input_frames, exception_on_overflow=False)
            block = np.frombuffer(raw, dtype=np.float32)
            if input_channels > 1:
                block = block.reshape(-1, input_channels).mean(axis=1)

            block = resample_linear(block, output_frames)
            processed = processor.process(block)

            if output_channels > 1:
                out = np.repeat(processed[:, None], output_channels, axis=1)
            else:
                out = processed
            output_stream.write(out.astype(np.float32, copy=False).tobytes(), exception_on_underflow=False)

    except KeyboardInterrupt:
        print("\nОстановлено.")
    except OSError as exc:
        print("\nAudio error:", exc)
        print("Проверь разрешение Microphone для Terminal/Python и что BlackHole не занят странной частотой.")
        return 1
    finally:
        try:
            if "input_stream" in locals():
                input_stream.stop_stream()
                input_stream.close()
            if "output_stream" in locals():
                output_stream.stop_stream()
                output_stream.close()
        finally:
            pa.terminate()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Realtime voice changer: physical mic -> effects -> BlackHole virtual microphone.",
    )
    parser.add_argument("--list-devices", action="store_true", help="показать audio devices и выйти")
    parser.add_argument("--input", help="input device index или часть имени, например 1 или 'USB'")
    parser.add_argument("--output", help="output device index или часть имени, по умолчанию BlackHole")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="номер пресета без интерактивного выбора")
    parser.add_argument("--block-ms", type=float, default=20.0, help="размер аудио-блока, меньше = ниже задержка")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
