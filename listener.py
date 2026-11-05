#!/usr/bin/env python3

import json
import logging
import signal
import socket
import threading
import subprocess
from time import monotonic, sleep
import wave
from pathlib import Path
from subprocess import DEVNULL

import numpy as np
import pyaudio
from playsound3 import playsound
from vosk import KaldiRecognizer, Model, SetLogLevel


# путь до папки NAVI
path = Path(__file__).resolve().parent

# IPC-сокет frontend
ui_socket_path = '/tmp/navi-ui.sock'

# IPC-сокет Whisper worker
worker_socket_path = '/tmp/navi-whisper.sock'


# локальная модель vosk для wake word
vosk_model_path = (
    path
    / 'models'
    / 'vosk'
    / 'vosk-model-small-ru-0.22'
)


# настройки микрофона
sample_rate = 16000
channels = 1
sample_width = 2
chunk_size = 4000


# максимальная длина одной команды
max_command_time = 10

# сколько тишины считать концом команды
silence_time = 0.9

# порог громкости микрофона
silence_threshold = 650


# wake word
wake_words = [
    'нави',
    'наве',
]


# звуковые сигналы
start_sound = (
    path
    / 'support_files'
    / 'start.mp3'
)

end_sound = (
    path
    / 'support_files'
    / 'start.mp3'
)


# временный WAV-файл команды
command_file = path / 'command.wav'


# флаг работы listener
running = True
paused = False
listener_control_socket = "/tmp/navi-listener-control.sock"


# vosk слишком много пишет в консоль, поэтому отключаем его технические сообщения
SetLogLevel(-1)


# логируем только реальные ошибки
logging.basicConfig(
    level=logging.ERROR,
)

def listen_control():
    global paused

    control_path = Path(listener_control_socket)

    if control_path.exists():
        control_path.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(listener_control_socket)
    server.listen(5)

    while running:
        connection, _ = server.accept()

        try:
            data = connection.recv(1024).decode().strip()

            if data == 'pause':
                paused = True

            elif data == 'resume':
                paused = False

        finally:
            connection.close()

    server.close()


def send(data):
    # отправляем событие в frontend
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM,) as sock:
            sock.settimeout(0.5)

            sock.connect(
                ui_socket_path
            )

            message = (
                json.dumps(
                    data,
                    ensure_ascii=False,
                )
                + '\n'
            )

            sock.sendall(
                message.encode('utf-8')
            )

    except (
        FileNotFoundError,
        ConnectionRefusedError,
        BrokenPipeError,
        socket.timeout,
        OSError,
    ):
        pass


def log(message):
    # отправляем лог в frontend
    send(
        {
            'type': 'log',
            'message': message,
        }
    )


def send_state(state):
    # удобная обёртка для состояния фронтенда
    send(
        {
            'type': 'state',
            'state': state,
        }
    )


def play_signal(sound):
    # проигрываем звук
    # пробуем через ffplay, mpv и playsound3, чтобы точно проиграть

    if not sound.exists():
        log(
            f'звуковой файл не найден: {sound}'
        )
        return

    players = [
        [
            'ffplay',
            '-nodisp',
            '-autoexit',
            '-loglevel',
            'quiet',
            str(sound),
        ],
        [
            'mpv',
            '--no-video',
            '--really-quiet',
            str(sound),
        ],
    ]

    for command in players:
        try:
            subprocess.run(
                command,
                stdout=DEVNULL,
                stderr=DEVNULL,
                check=True,
            )

            return

        except FileNotFoundError:
            # такой проигрыватель просто не установлен
            continue

        except subprocess.CalledProcessError:
            continue

        except OSError:
            continue

    # последняя попытка через playsound3
    try:
        playsound(
            str(sound)
        )

    except Exception as error:
        log(
            f'ошибка воспроизведения звука: {error}'
        )


def get_volume(data):
    # получаем RMS-громкость текущего аудиоблока
    samples = np.frombuffer(
        data,
        dtype=np.int16,
    )

    if samples.size == 0:
        return 0.0

    return float(
        np.sqrt(
            np.mean(
                samples.astype(
                    np.float32
                ) ** 2
            )
        )
    )


def is_wake_word(text):
    text = text.strip().lower()

    words = text.split()

    return any(
        word in words
        for word in wake_words
    )


def wait_for_wakeword(stream, model):
    # vosk работает постоянно, но слушает только wake word
    grammar = json.dumps(
        wake_words + ['[unk]'],
        ensure_ascii=False,
    )

    recognizer = KaldiRecognizer(
        model,
        sample_rate,
        grammar,
    )

    while running:
        if paused:
            stream.read(chunk_size, exception_on_overflow=False)
            continue

        data = stream.read(
            chunk_size,
            exception_on_overflow=False,
        )

        if recognizer.AcceptWaveform(data):
            result = json.loads(
                recognizer.Result()
            )

            text = result.get(
                'text',
                '',
            )

            if text:
                log(
                    f'vosk: {text}'
                )

            if is_wake_word(text):
                return True

    return False


def record_command(stream):
    # записываем команду после wake word
    frames = []

    started = False

    # время последней активности голоса
    silent_for = 0.0

    started_at = monotonic()

    while running:
        data = stream.read(
            chunk_size,
            exception_on_overflow=False,
        )

        frames.append(data)

        volume = get_volume(data)

        elapsed = (
            monotonic()
            - started_at
        )

        if volume >= silence_threshold:
            started = True
            silent_for = 0.0

        elif started:
            silent_for += (
                chunk_size
                / sample_rate
            )

        if (
            started
            and silent_for >= silence_time
        ):
            break

        # защита от бесконечной записи
        if elapsed >= max_command_time:
            break

    return b''.join(frames)


def save_wav(data):
    # сохраняем запись в обычный PCM WAV
    with wave.open(str(command_file), 'wb',) as file:
        file.setnchannels(
            channels
        )

        file.setsampwidth(
            sample_width
        )

        file.setframerate(
            sample_rate
        )

        file.writeframes(data)


def send_to_worker(filename):
    # передаём готовую запись whisper worker
    for _ in range(15):
        try:
            with socket.socket(
                socket.AF_UNIX,
                socket.SOCK_STREAM,
            ) as sock:
                sock.settimeout(1)

                sock.connect(
                    worker_socket_path
                )

                message = {
                    'type': 'transcribe',
                    'file': str(filename),
                }

                packet = (
                    json.dumps(
                        message,
                        ensure_ascii=False,
                    )
                    + '\n'
                )

                sock.sendall(
                    packet.encode('utf-8')
                )

                return True

        except (
            FileNotFoundError,
            ConnectionRefusedError,
            BrokenPipeError,
            socket.timeout,
            OSError,
        ):
            sleep(0.2)

    return False


def shutdown(signum=None, frame=None):
    # нормальное завершение listener
    global running

    running = False


def main():
    global paused

    # проверяем занят ли executor
    control_thread = threading.Thread(target=listen_control, daemon=True)
    control_thread.start()

    if not vosk_model_path.exists():
        raise FileNotFoundError(
            f'не найдена модель Vosk: '
            f'{vosk_model_path}'
        )

    # сигналы завершения
    signal.signal(
        signal.SIGINT,
        shutdown,
    )

    signal.signal(
        signal.SIGTERM,
        shutdown,
    )

    send(
        {
            'type': 'listener',
            'state': 'starting',
        }
    )

    log(
        'запускаю локальный wake word'
    )

    vosk = Model(
        str(vosk_model_path)
    )

    audio = pyaudio.PyAudio()

    stream = None

    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sample_rate,
            input=True,
            frames_per_buffer=chunk_size,
        )

        stream.start_stream()

        send(
            {
                'type': 'listener',
                'state': 'online',
            }
        )

        send_state('idle')

        log(
            'локальный listener запущен'
        )

        while running:
            # ждём "NAVI"
            if not wait_for_wakeword(
                stream,
                vosk,
            ):
                break

            if not running:
                break

            # wake word пойман
            send(
                {
                    'type': 'wake',
                }
            )

            log(
                'NAVI активирована'
            )

            send_state(
                'listening'
            )

            # сигнал начала записи
            play_signal(
                start_sound
            )

            # записываем команду
            command_audio = record_command(
                stream
            )

            if not running:
                break

            # сигнал конца записи
            play_signal(
                end_sound
            )

            # сохраняем запись
            save_wav(
                command_audio
            )

            send_state(
                'processing'
            )

            paused = True

            # передаём запись whisper worker
            if not send_to_worker(command_file):
                log('не удалось связаться с whisper worker')
                paused = False
                send_state('idle')

    except Exception as error:
        if running:
            logging.exception(
                'listener завершился с ошибкой'
            )

            send(
                {
                    'type': 'listener',
                    'state': 'error',
                    'message': str(error),
                }
            )

    finally:
        # закрываем микрофон
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass

            try:
                stream.close()
            except Exception:
                pass

        audio.terminate()

        send(
            {
                'type': 'listener',
                'state': 'offline',
            }
        )


if __name__ == '__main__':
    main()
