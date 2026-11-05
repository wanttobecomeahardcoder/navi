#!/usr/bin/env python3

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


# путь до папки NAVI
path = Path(__file__).resolve().parent

# IPC-сокет, через который frontend может попросить launcher завершить всё
control_socket_path = '/tmp/navi-control.sock'

# все дочерние процессы launcher
processes = []

# главный флаг работы launcher
running = True

# блокировка, чтобы shutdown не выполнялся несколько раз одновременно
shutdown_lock = threading.Lock()


def cleanup_sockets():
    # удаляем старые IPC-сокеты перед запуском
    for socket_path in (
        '/tmp/navi-ui.sock',
        '/tmp/navi-whisper.sock',
        '/tmp/navi-listener-control.sock',
        control_socket_path,
    ):
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def shutdown(signum=None, frame=None):
    # полностью останавливаем всё дерево NAVI
    
    global running

    with shutdown_lock:
        if not running:
            return

        running = False

    # сначала отправляем всем процессам нормальное завершение
    for process in reversed(processes):
        if process.poll() is None:
            try:
                # каждый процесс запускается в своей группе
                os.killpg(
                    process.pid,
                    signal.SIGTERM,
                )
            except ProcessLookupError:
                pass
            except OSError:
                try:
                    process.terminate()
                except OSError:
                    pass

    # даём процессам немного времени нормально закрыться
    deadline = time.monotonic() + 3

    while time.monotonic() < deadline:
        alive = False

        for process in processes:
            if process.poll() is None:
                alive = True
                break

        if not alive:
            break

        time.sleep(0.05)

    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(
                    process.pid,
                    signal.SIGKILL,
                )
            except ProcessLookupError:
                pass
            except OSError:
                try:
                    process.kill()
                except OSError:
                    pass

    for process in processes:
        try:
            process.wait(timeout=1)
        except (
                subprocess.TimeoutExpired,
                OSError,
        ):
            pass

    cleanup_sockets()


def start_process(filename):
    # запускаем все остальные элементы
    process = subprocess.Popen(
        [
            sys.executable,
            str(path / filename),
        ],
        cwd=str(path),
        start_new_session=True,
    )

    processes.append(process)

    return process


def control_server():
    # сервер управления launcher
    # сообщение завершения: {'type': 'shutdown'}

    global running

    try:
        os.unlink(control_socket_path)

    except FileNotFoundError:
        pass

    except OSError:
        pass

    server = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )

    try:
        server.bind(control_socket_path)
        server.listen(4)
        server.settimeout(0.5)

    except OSError:
        server.close()
        return

    while running:
        try:
            connection, _ = server.accept()

        except socket.timeout:
            continue

        except OSError:
            break

        try:
            data = b''

            # читаем JSON-сообщение до символа новой строки
            while b'\n' not in data:
                chunk = connection.recv(4096)

                if not chunk:
                    break

                data += chunk

            if data:
                raw = data.split(
                    b'\n',
                    1,
                )[0]

                try:
                    message = json.loads(
                        raw.decode('utf-8')
                    )

                    if message.get('type') == 'shutdown':
                        shutdown()

                except json.JSONDecodeError:
                    pass

        except OSError:
            pass

        finally:
            try:
                connection.close()

            except OSError:
                pass

    try:
        server.close()

    except OSError:
        pass

    try:
        os.unlink(control_socket_path)

    except FileNotFoundError:
        pass

    except OSError:
        pass


def main():
    global running

    # обрабатываем ctrl+c и SIGTERM
    signal.signal(
        signal.SIGINT,
        shutdown,
    )

    signal.signal(
        signal.SIGTERM,
        shutdown,
    )

    # перед запуском удаляем старые сокеты
    cleanup_sockets()

    # сначала запуск whisper worker, т.к. он поднимет свой сокет для listener
    worker = start_process(
        'whisper_worker.py'
    )

    # небольшая задержка для старта IPC
    time.sleep(0.3)

    # затем запускаем listener
    listener = start_process(
        'listener.py'
    )

    time.sleep(0.3)

    # последним запускаем frontend
    frontend = start_process(
        'frontend.py'
    )

    # отдельный поток слушает команду закрытия от frontend
    control_thread = threading.Thread(
        target=control_server,
        daemon=True,
    )

    control_thread.start()

    try:
        while running:
            # если frontend закрылся, закрываем всё
            if frontend.poll() is not None:
                running = False
                break

            # если listener неожиданно упал закрываем всё, чтобы не оставлять полуработающий NAVI
            if listener.poll() is not None:
                running = False
                break

            # если whisper worker умер также закрываем всё дерево
            if worker.poll() is not None:
                running = False
                break

            time.sleep(0.2)

    except KeyboardInterrupt:
        pass

    finally:
        shutdown()


if __name__ == '__main__':
    main()
