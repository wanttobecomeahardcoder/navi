#!/usr/bin/env python3

import json
import logging
import os
import signal
import socket
import threading
from pathlib import Path


# ограничиваем количество потоков ещё до импорта faster-whisper
os.environ.setdefault(
    'OMP_NUM_THREADS',
    '2',
)

os.environ.setdefault(
    'MKL_NUM_THREADS',
    '2',
)

os.environ.setdefault(
    'OPENBLAS_NUM_THREADS',
    '2',
)


from faster_whisper import WhisperModel


# путь до папки NAVI
path = Path(__file__).resolve().parent

ui_socket_path = '/tmp/navi-ui.sock'

# IPC-сокет listener
worker_socket_path = '/tmp/navi-whisper.sock'


# локальная модель faster-whisper
whisper_model_path = (
    path
    / 'models'
    / 'whisper'
)


# ограничиваем CPU
whisper_cpu_threads = 4


# флаг работы worker
running = True


# при запуске worker не занимаем CPU,
# а загружаем только при первой команде
whisper = None


# не даём двум командам одновременно грузить whisper
busy_lock = threading.Lock()


logging.basicConfig(
    level=logging.ERROR,
)


def send(data):
    # отправляем событие frontend
    try:
        with socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        ) as sock:
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
    # удобная отправка лога
    send(
        {
            'type': 'log',
            'message': message,
        }
    )


def send_state(state):
    # удобная отправка состояния
    send(
        {
            'type': 'state',
            'state': state,
        }
    )


def shutdown(signum=None, frame=None):
    # нормальное завершение worker
    global running

    running = False


def create_whisper():
    # загружаем локальную faster-whisper модель

    global whisper

    if whisper is not None:
        return whisper

    if not whisper_model_path.exists():
        raise FileNotFoundError(
            f'не найдена локальная модель Whisper: '
            f'{whisper_model_path}'
        )

    send(
        {
            'type': 'worker',
            'state': 'starting',
        }
    )

    log(
        'загружаю Whisper'
    )

    whisper = WhisperModel(
        str(whisper_model_path),
        device='cpu',
        compute_type='int8',
        cpu_threads=whisper_cpu_threads,
        num_workers=1,
    )

    send(
        {
            'type': 'worker',
            'state': 'online',
        }
    )

    log(
        'Whisper загружен'
    )

    return whisper


def transcribe(filename):
    # получаем модель
    model = create_whisper()

    # распознаём WAV локально
    segments, _ = model.transcribe(
        str(filename),
        language='ru',
        beam_size=3,
        vad_filter=True,
        vad_parameters={
            'min_silence_duration_ms': 500,
        },
        condition_on_previous_text=False,
    )

    # собираем сегменты в одну строку
    text = ''.join(
        segment.text
        for segment in segments
    ).strip()

    return text


def process_command(filename):
    # не запускаем вторую транскрипцию,
    # пока первая ещё работает
    if not busy_lock.acquire(
        blocking=False
    ):
        log(
            'Whisper занят, команда пропущена'
        )
        return

    try:
        filename = Path(
            filename
        )

        if not filename.exists():
            log(
                'файл команды не найден'
            )
            return

        send_state(
            'processing'
        )

        # распознаём команду
        text = transcribe(
            filename
        )

        try:
            filename.unlink()

        except FileNotFoundError:
            pass


        except OSError:
            pass

        if text:
            # передаём исходный текст дальше
            send(
                {
                    'type': 'command',
                    'text': text,
                }
            )

            log(
                f'команда: {text}'
            )

        else:
            log(
                'команда не распознана'
            )

        send_state(
            'idle'
        )

    except Exception as error:
        logging.exception(
            'ошибка обработки команды'
        )

        send(
            {
                'type': 'worker',
                'state': 'error',
                'message': str(error),
            }
        )

        send_state(
            'idle'
        )

        try:
            Path(filename).unlink()

        except FileNotFoundError:
            pass

        except OSError:
            pass

    finally:
        busy_lock.release()


def handle_connection(connection):
    # читаем JSON lines от listener
    
    try:
        buffer = b''

        while running:
            data = connection.recv(
                65536
            )

            if not data:
                break

            buffer += data

            while b'\n' in buffer:
                line, buffer = buffer.split(
                    b'\n',
                    1,
                )

                if not line:
                    continue

                try:
                    message = json.loads(
                        line.decode('utf-8')
                    )

                except json.JSONDecodeError:
                    log(
                        'получено повреждённое IPC-сообщение'
                    )
                    continue

                if (
                    message.get('type')
                    == 'transcribe'
                ):
                    filename = message.get(
                        'file'
                    )

                    if filename:
                        # каждая команда обрабатывается в отдельном потоке
                        threading.Thread(
                            target=process_command,
                            args=(filename,),
                            daemon=True,
                        ).start()

    except (
        ConnectionResetError,
        BrokenPipeError,
        OSError,
    ):
        pass

    finally:
        try:
            connection.close()

        except OSError:
            pass


def server():
    # удаляем старый socket
    try:
        os.unlink(
            worker_socket_path
        )
    except FileNotFoundError:
        pass
    except OSError:
        pass

    server_socket = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )

    server_socket.bind(
        worker_socket_path
    )

    server_socket.listen(4)

    server_socket.settimeout(
        0.5
    )

    send(
        {
            'type': 'worker',
            'state': 'online',
        }
    )

    log(
        'whisper worker готов'
    )

    try:
        while running:
            try:
                connection, _ = (
                    server_socket.accept()
                )

            except socket.timeout:
                continue

            except OSError:
                break

            # не блокируем основной сервер чтением одного клиента
            threading.Thread(
                target=handle_connection,
                args=(connection,),
                daemon=True,
            ).start()

    finally:
        try:
            server_socket.close()
        except OSError:
            pass

        try:
            os.unlink(
                worker_socket_path
            )
        except FileNotFoundError:
            pass
        except OSError:
            pass


def main():
    # проверяем модель до запуска сервера
    if not whisper_model_path.exists():
        raise FileNotFoundError(
            f'не найдена локальная модель Whisper: '
            f'{whisper_model_path}'
        )

    signal.signal(
        signal.SIGINT,
        shutdown,
    )

    signal.signal(
        signal.SIGTERM,
        shutdown,
    )

    try:
        server()

    except Exception as error:
        logging.exception(
            'whisper worker завершился с ошибкой'
        )

        send(
            {
                'type': 'worker',
                'state': 'error',
                'message': str(error),
            }
        )

    finally:
        send(
            {
                'type': 'worker',
                'state': 'offline',
            }
        )


if __name__ == '__main__':
    main()
