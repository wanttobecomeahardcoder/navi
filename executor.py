from os import system, setsid
from os import path as ospath
from subprocess import run, Popen, DEVNULL
import sys
import logging
import warnings

from pathlib import Path
import json
import re
import numpy as np
import sounddevice as sd
import torch

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as Chrome_Options
from selenium.webdriver.chrome.service import Service as Chrome_Service
from selenium.webdriver.firefox.service import Service as Firefox_Service

from num2words import num2words

# убираем логи selenium, чтобы он не занимал поток
logging.getLogger('selenium').setLevel(logging.CRITICAL)

# убираем логи торча, чтобы убрать некрасивый лог
warnings.filterwarnings("ignore")

# путь до расположения файла
path = str(Path(__file__).resolve().parent)

# имя пользователя
name = open(path + '/support_files/name.txt', 'r', encoding='utf-8').readline().rstrip()

# буквенные написания цифр для перевода в цифровой вариант
digits_map = {
    "ноль": 0, "один": 1, "первую":1, "первая":1, 'первый':1, "два": 2, "вторая": 2, "вторую": 2, "второй": 2, "три": 3,
    "третья": 3, "третью": 3, "третий": 3, "четыре": 4, "четвёртую": 4, "четвёртая": 4, "четвёртый": 4, "пять": 5,
    "пятую": 5, "пятая": 5, "пятый": 5, "шесть": 6, "шестую": 6, "шестая": 6, "шестой": 6, "семь": 7, "седьмую": 7,
    "седьмая": 7, "седьмой": 7, "восемь": 8, "восьмую": 8, "восьмая": 8, "восьмой": 8, "девять": 9, "девятую": 9,
    "девятая": 9, "девятый": 9
}

# длинные команды, чтобы не захламлять функции плей, паузы, предыдущего и следующего медиа

play_cmd = r"""for bus in $(dbus-send --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames | grep -oP 'org\.mpris\.MediaPlayer2\.[^\s"]+'); do dbus-send --print-reply --dest=$bus /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Play; done"""
pause_cmd = r"""for bus in $(dbus-send --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames | grep -oP 'org\.mpris\.MediaPlayer2\.[^\s"]+'); do dbus-send --print-reply --dest=$bus /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Pause; done"""
next_cmd = r"""for bus in $(dbus-send --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames | grep -oP 'org\.mpris\.MediaPlayer2\.[^\s"]+'); do dbus-send --print-reply --dest=$bus /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Next; done"""
previous_cmd = r"""for bus in $(dbus-send --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames | grep -oP 'org\.mpris\.MediaPlayer2\.[^\s"]+'); do dbus-send --print-reply --dest=$bus /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Previous; done"""

# ---------------------------------------------------------------------
# IPC / вывод
# ---------------------------------------------------------------------

<<<<<<< HEAD
def emit(payload):
    # Все ответы executor идут в stdout как JSON.
=======
def emit(payload:str):
    # все ответы executor идут в stdout как JSON
>>>>>>> 9e71007 (major update. project renamed.)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        flush=True,
    )


# ---------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------

model = None

hub_dir = torch.hub.get_dir()
cache_path = ospath.join(hub_dir, "snakers4_silero-models_master")

try:
    if ospath.exists(cache_path):
        model, _ = torch.hub.load(
            repo_or_dir=cache_path,
            model="silero_tts",
            language="ru",
            speaker="v5_ru",
            source="local",
            force_reload=False,
        )

    else:
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language="ru",
            speaker="v5_ru",
        )

except Exception as error:
    emit(
        {
            'type': 'log',
            'message': f'tts error: {error}',
        }
    )
    model = None

# настройки CPU
torch.set_num_threads(4)
torch.set_num_interop_threads(1)

SAMPLE_RATE = 24000
SPEAKER = "xenia"

def speak(text: str):
    if model is None:
        return
    try:
        with torch.inference_mode():
            audio = model.apply_tts(
                text=text,
                speaker=SPEAKER,
                sample_rate=SAMPLE_RATE,
            )

        audio = audio.cpu().numpy().astype(np.float32)

        sd.play(audio, samplerate=SAMPLE_RATE)
        sd.wait()

    except Exception as _error:
        emit(
            {
                'type': 'log',
                'message': f'tts error: {_error}',
            }
        )

# ---------------------------------------------------------------------
# проверка на число
# ---------------------------------------------------------------------

# проверяет только следующее слово(недоработано)
def _check_number_for_click(possible_number, move:str) -> int:
    try:
        possible_number = int(possible_number)
        speak(f'нажимаю {move} {num2words(possible_number, lang='ru')} раз')
        return int(possible_number)
    except (IndexError, ValueError):
        if digits_map.get(possible_number) is not None:
            num = digits_map.get(possible_number)
            speak(f'нажимаю {move} {num2words(num, lang='ru')}')
            if num%10 in (2, 3, 4):
                speak('раза')

            else:
                speak('раз')
                
            return digits_map.get(possible_number)
        else:
            speak(f'нажимаю {move}')
            return 1


# проверяет только следующее слово(недоработано)
def _check_number(possible_number) -> int | None:
    try:
        possible_number = int(possible_number)
        return possible_number
    except (IndexError, ValueError):
        if digits_map.get(possible_number) is not None:
            return digits_map.get(possible_number)
        else:
            return None

# ---------------------------------------------------------------------
# алиасы
# ---------------------------------------------------------------------

def _get_aliases() -> list:
    _aliases = []
    with (open(path + '/support_files/aliases.txt', 'r', encoding='utf-8') as f):
        for i in f:
            _aliases += [[i.split(' : ')[0], i.split(' : ')[1]]]
    return _aliases

# ---------------------------------------------------------------------
# словарь
# ---------------------------------------------------------------------

# слово:вывод, слово будет проверяться в блоке ввода и выводиться вывод
def _get_dictionary() -> list:
    _dictionary = []
    with (open(path + '/support_files/dictionary.txt', 'r', encoding='utf-8') as f):
        for i in f:
            _dictionary += [[i.split(' : ')[0], i.split(' : ')[1]]]
    return _dictionary

# ---------------------------------------------------------------------
# кастомные команды
# ---------------------------------------------------------------------

def _get_custom_commands() -> list:
    _custom_commands = []
    with(open(path + '/support_files/custom_commands.txt', 'r', encoding='utf-8') as f):
        for i in f:
            _custom_commands += [[i.split(' : ')[0], i.split(' : ')[1].split(' ')]]
    return _custom_commands

aliases = _get_aliases()
custom_commands = _get_custom_commands()
dictionary = _get_dictionary()

# ---------------------------------------------------------------------
# определение браузера
# ---------------------------------------------------------------------

browser = None

def _initial_browser(_browser_type:str | None):
    global browser

    if browser is None:

        if _browser_type is None:
            return None

        elif _browser_type == "firefox":
            if system("pgrep firefox >/dev/null 2>&1") == 256:
                speak(f'извини, {name}, похоже, браузер не открыт')
                return None

            service_firefox = Firefox_Service(
                service_args=[
                    "--marionette-port", "2828",
                    "--connect-existing"
                ],
                log_output="/dev/null"
            )
            browser = webdriver.Firefox(service=service_firefox)

        else:
            if system("pgrep chromium") != 256 or system("pgrep chrome") != 256:
                options_chrome = Chrome_Options()
                options_chrome.add_experimental_option(
                    "debuggerAddress", "127.0.0.1:9222"
                )
                options_chrome.add_argument("--log-level=3")
                options_chrome.add_argument("--silent")

                service_chrome = Chrome_Service(log_output="/dev/null")

                browser = webdriver.Chrome(
                    service=service_chrome,
                    options=options_chrome
                )

            else:
                speak(f'извини, {name}, похоже, браузер не открыт')
                return None

        return browser

    else:
        return browser


browser_type = None

for alias, _text in aliases:
    if alias == 'браузер':
        browser_type = _text.rstrip()
        break


# ---------------------------------------------------------------------
# фокус
# ---------------------------------------------------------------------

last_focus = None


def _focus_element(_browser, query=None, restore=False, announce=True):
    global last_focus

    if _browser is None:
        _browser = _initial_browser(browser_type)

    if _browser is not None:
        if restore:
            if last_focus is None:
                if announce:
                    speak(f'я ещё не запоминала поле, извини {name}')
                return False

            if _browser.current_url != last_focus['url']:
                if announce:
                    speak(f'страница изменилась; назови элемент заново, {name}')
                return False

            descriptor = last_focus

        else:
            descriptor = None

        try:
            result = _browser.execute_script(r"""
                const query = (arguments[0] || '').trim().toLocaleLowerCase();
                const saved = arguments[1];
                const visible = el => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const norm = value => (value || '').toLocaleLowerCase()
                    .replace(/[^\p{L}\p{N}]+/gu, ' ').replace(/\s+/g, ' ').trim();
                const similarity = (a, b) => {
                    if (!a || !b) return 0;
                    if (a === b) return 1;
                    if (a.includes(b) || b.includes(a)) return Math.min(a.length, b.length) / Math.max(a.length, b.length) * 0.25 + 0.7;
                    const rows = Array.from({length: a.length + 1}, () => Array(b.length + 1).fill(0));
                    for (let i = 0; i <= a.length; i++) rows[i][0] = i;
                    for (let j = 0; j <= b.length; j++) rows[0][j] = j;
                    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) {
                        rows[i][j] = Math.min(rows[i-1][j] + 1, rows[i][j-1] + 1,
                            rows[i-1][j-1] + (a[i-1] === b[j-1] ? 0 : 1));
                    }
                    const charScore = 1 - rows[a.length][b.length] / Math.max(a.length, b.length);
                    const aw = new Set(a.split(' ')), bw = new Set(b.split(' '));
                    let common = 0;
                    for (const word of aw) if (bw.has(word)) common++;
                    const wordScore = common / Math.max(aw.size, bw.size);
                    return Math.max(charScore, wordScore * 0.9);
                };
                const fields = 'input, textarea, select, [contenteditable="true"], [role="textbox"]';
                const elements = Array.from(document.querySelectorAll(
                    'input, textarea, select, button, a, [contenteditable="true"], ' +
                    '[role="button"], [role="textbox"], label, [placeholder], [aria-label], [title], [id]'
                ));
    
                if (saved) {
                    const attrs = ['id', 'name', 'placeholder', 'aria-label', 'title'];
                    let matches = elements.filter(el => visible(el) &&
                        attrs.some(attr => saved[attr] && el.getAttribute(attr) === saved[attr]));
    
                    if (!matches.length && saved.text) {
                        matches = elements.filter(el => visible(el) &&
                            norm(el.innerText || el.value || el.getAttribute('aria-label')) === norm(saved.text));
                    }
    
                    return matches.slice(0, 2);
                }
    
                if (!query) return [];
    
                const scores = new Map();
                const add = (el, score) => {
                    if (el && visible(el)) {
                        scores.set(el, Math.max(scores.get(el) || 0, score));
                    }
                };
    
                for (const el of elements) {
                    if (!visible(el)) continue;
    
                    let score = 0;
                    for (const attr of ['placeholder', 'aria-label', 'title', 'name', 'id']) {
                        const value = norm(el.getAttribute(attr));
                        if (value === query) score = Math.max(score, 100);
                        else if (value && value.includes(query)) score = Math.max(score, 88);
                        else if (value) {
                            const similar = similarity(query, value);
                            if (similar >= 0.58) score = Math.max(score, 55 + similar * 30);
                        }
                    }
    
                    const label = norm(el.labels
                        ? Array.from(el.labels).map(item => item.innerText).join(' ')
                        : '');
    
                    if (label === query) score = Math.max(score, 100);
                    else if (label && label.includes(query)) score = Math.max(score, 88);
                    else if (label && similarity(query, label) >= 0.58)
                        score = Math.max(score, 55 + similarity(query, label) * 30);
    
                    const text = norm(el.innerText || (el.tagName === 'INPUT' ? el.value : ''));
                    if (text === query) score = Math.max(score, 85);
                    else if (text && text.includes(query)) score = Math.max(score, 80);
                    else if (text && similarity(query, text) >= 0.58)
                        score = Math.max(score, 50 + similarity(query, text) * 25);
    
                    if (score) add(el, score);
    
                    if (text && (text === query || text.includes(query))) {
                        const child = el.querySelector(fields);
                        if (child && visible(child)) {
                            add(child, text === query ? 80 : 60);
                        }
                    }
                }
    
                const ranked = Array.from(scores.entries()).sort((a, b) => b[1] - a[1]);
                if (!ranked.length) return [];
    
                const best_score = ranked[0][1];
                return ranked.filter(item => item[1] === best_score)
                    .slice(0, 5).map(item => item[0]);
            """, query or '', descriptor)

            if not result:
                if announce:
                    speak(f'не нашла такой элемент на странице, извини, {name}')
                return False

            if len(result) > 1:
                if announce:
                    speak(f'я нашла несколько похожих элементов; пожалуйста, уточни подпись, {name}')
                return False

            element = result[0]

            _browser.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
                element
            )

            try:
                element.click()

            except Exception:
                pass

            last_focus = _browser.execute_script("""
                const el = arguments[0];
                const target = el.matches('input, textarea, select, [contenteditable="true"], [role="textbox"]')
                    ? el
                    : (el.querySelector('input, textarea, select, [contenteditable="true"], [role="textbox"]') || el);
    
                target.focus();
    
                return {
                    url: location.href,
                    id: target.getAttribute('id') || '',
                    name: target.getAttribute('name') || '',
                    placeholder: target.getAttribute('placeholder') || '',
                    'aria-label': target.getAttribute('aria-label') || '',
                    title: target.getAttribute('title') || '',
                    text: (target.innerText || target.value || target.getAttribute('aria-label') || '').trim()
                };
            """, element)

            if announce:
                speak(f'фокус установлен')

            return True

        except Exception as _error:
            emit({
                'type': 'log',
                'message': f'ошибка фокуса: {type(_error).__name__}: {_error}'
            })

            if announce:
                speak(f'не получилось установить фокус, извини, {name}')

            return False

    speak(f'извини, {name}, что-то пошло не так, попробуй ещё раз')
    return False


def _focus_query(text):
    text = re.sub(
        r'(?i)\b(?:navi|нави|пожалуйста|прошу|установи|поставь|повтори|верни|восстанови|найди|сфокусируйся|фокус|на|в|поле|поля|кнопке|кнопку|ссылке|ссылку|элементе|элемент|текстом|подписи|подписью|к|предыдущему|предыдущее|последнему|последнее)\b',
        '',
        text
    )

    return re.sub(r'\s+', ' ', text).strip(' .,!?:;«»"')


def navi(text):
    # ---------------------------------------------------------------------
    # переменные браузера
    # ---------------------------------------------------------------------

    global browser_type
    global browser

    # ---------------------------------------------------------------------
    # фокус
    # ---------------------------------------------------------------------

    if any(phrase in text.lower() for phrase in (
        'повтори фокус',
        'верни фокус',
        'вернись к предыдущему полю',
        'восстанови фокус',
        'продолжи ввод'
    )):
        _focus_element(browser, restore=True)

    elif (
        'фокус' in text.lower()
        or 'сфокусируйся' in text.lower()
        or 'найди элемент' in text.lower()
        or 'найди поле' in text.lower()
    ):
        query = _focus_query(text)

        if query:
            _focus_element(browser, query=query)
        else:
            speak(f'назови текст на элементе, {name}')

    # ---------------------------------------------------------------------
    # ввод
    # ---------------------------------------------------------------------

    elif 'введи' in text.lower() or 'веди' in text.lower() or 'напиши' in text.lower():
        # если веб-фокус потерялся, пробуем восстановить его перед вводом
        if last_focus is not None and browser_type is not None:
            if browser is not None:
                _focus_element(browser, restore=True, announce=False)

        text = (
            text.replace('введи', '')
            .replace('Введи', '')
            .replace('напиши', '')
            .replace('Напиши', '')
            .replace('Веди', '')
            .replace('веди', '')

        for pair in dictionary:
            if pair[0] == text.lower().replace(' ', '').replace(',', '').replace('.', ''):
                run(['wtype', pair[1]], check=True)
                speak(f'ввёла текст прикреплённый к {pair[0]} в словаре')
                break
        else:
            run(['wtype', text], check=True)
            speak(f'как скажешь, {name}')

    # ---------------------------------------------------------------------
    # открытие
    # ---------------------------------------------------------------------

    elif 'открой' in text.lower() or 'открою' in text.lower() or 'запусти' in text.lower():
        soft = (text.lower().replace('открой', '').replace('открою', '').replace('запусти', '').replace(' ', '')
                .replace('.', '').replace(',', ''))
        if system('which ' + soft) == 0:
            Popen(
                soft,
                stdout=DEVNULL,
                stderr=DEVNULL,
                preexec_fn=setsid
            )
            speak(f'запустила {soft}')

        elif 'сайт' in soft:
            site = soft.replace('сайт', '').replace('«', '').replace('»', '')
            if browser is None:
                browser = _initial_browser(browser_type)

            if browser is not None:
                for key, elem in dictionary:
                    if site == key:
                        browser.switch_to.new_window('tab')
                        browser.get(elem)
                        speak(f'открыла сайт {site}')
                        break

                else:
                    speak(f'не удалось открыть сайт {site}, извини {name}')

        elif 'браузер' in text.lower():

            if browser_type == 'firefox':
                cmd = ['firefox', '--marionette', '-start-debugger-server', '2828']
                Popen(
                    cmd,
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                    preexec_fn=setsid
                )
                browser = _initial_browser(browser_type)

                speak('запустила браузер')

            elif browser_type is not None:
                Popen(
                    browser_type,
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                    preexec_fn=setsid
                )
                browser = _initial_browser(browser_type)

                speak('запустила браузер')

            else:
                speak(f'извини, {name}, похоже браузер не назначен в файле конфигурации')


        else:
            for _alias in aliases:
                if _alias[0] == soft:
                    cmd = ''.join(_alias[1]).rstrip().split(' ')
                    Popen(
                        cmd,
                        stdout=DEVNULL,
                        stderr=DEVNULL,
                        preexec_fn=setsid
                    )
                    speak(f'запустила {soft}')
                    break
            else:
                speak(f'я не нашла {soft}, извини, {name}')

    # ---------------------------------------------------------------------
    # закрытие
    # ---------------------------------------------------------------------

    elif 'закрой' in text.lower() or 'закрою' in text.lower() or 'заверши' in text.lower():
        soft = text.lower().replace('закрой', '').replace('закрою', '').replace('заверши', '').replace(' ', '').replace('.', '').replace(',', '')
        if system('pgrep ' + soft) != 256:
            system('pkill -15 ' + soft)
            speak(f'закрыла {soft}')

        elif 'браузер' in soft.lower():
            if system('pgrep ' + browser_type) != 256:
                system('pkill -15 ' + browser_type)
                browser = None
                speak('закрыла браузер')

        elif 'сайт' in soft or 'вкладку' in soft:
            site = soft.replace('сайт', '').replace('вкладку', '')

            if browser is None:
                browser = _initial_browser(browser_type)

            if browser is not None:
                try:
                    if 'эту' in site or 'этот' in site:
                        browser.close()
                        handles = browser.window_handles
                        browser.switch_to.window(handles[-1])
                        speak('закрыла вкладку')

                    # закрытие по номеру
                    else:
                        handles = browser.window_handles

                        if len(handles) == 1:
                            for key, elem in dictionary:
                                if key == site and elem in browser.current_url:
                                    browser.get('tab')
                                    speak(f'закрыла единственную вкладку')
                                    break

                        if _check_number(site) is not None:
                            tab = _check_number(site) - 1
                            browser.switch_to.window(handles[tab])
                            browser.close()
                            handles = browser.window_handles
                            browser.switch_to.window(handles[0])
                            speak(
                                f'закрыла вкладку {next((k for k, v in digits_map.items() if v == tab + 1), None)}')

                        # закрытие по тайтлу
                        else:
                            _continue = True
                            for handle in handles:
                                browser.switch_to.window(handle)

                                for key, elem in dictionary:
                                    if key == site and elem.rstrip() in browser.current_url:
                                        browser.close()
                                        handles = browser.window_handles
                                        browser.switch_to.window(handles[0])
                                        speak(f'закрыла вкладку {key}, {name}')
                                        _continue = False
                                        break

                                if not _continue:
                                    break

                except:
                    speak(f'извини, {name}, что-то пошло не так')

            else:
                speak(f'извини, {name}, похоже, браузер не открыт')

        else:
            for _alias in aliases:
                if _alias[0] == soft:
                    if system('pgrep ' + _alias[1]) != 256:
                        system('pkill -15 ' + alias[1])
                        speak(f'закрыла {soft}, {name}')
                        break
            else:
                speak(f'извини, {name}, я не нашла {soft}')

    # ---------------------------------------------------------------------
    # перемещение
    # ---------------------------------------------------------------------

    elif 'перелистни' in text.lower() or 'перемести' in text.lower():
        text = (text.replace('перелистни', '').replace('перемести', '').replace('на', '').replace('вкладку', '')
                .replace(' ', '').replace(',', '').replace('.', ''))

        if _check_number(text) is not None:
            tab = _check_number(text.replace(' ', '').replace(',', '').replace('.', '')) - 1
            if tab > 0:
                if browser is None:
                    browser = _initial_browser(browser_type)

                if browser is not None:
                    handles = browser.window_handles

                    try:
                        browser.switch_to.window(handles[int(tab)])
                        speak(f'как скажешь, {name}')
                    except:
                        speak(f'извини, {name} возникла ошибка, попробуй ещё раз')

            else:
                speak(f'извини, {name}, но номер должен быть больше нуля')

        else:
            speak(f'прости, {name}, я не смогла определить номер нужной вкладки')

    # ---------------------------------------------------------------------
    # нажатие
    # ---------------------------------------------------------------------

    elif 'нажми' in text.lower():
        try:
            text = text.lower().replace('нажми', '').replace('.', '').replace(',', '').replace('-', ' ').replace('—', ' ').split(' ')[1::] + ['']
            # нажимаем все проговоренные клавиши
            for i, move in enumerate(text):
                if move in ('вверх', 'верх', 'наверх'):
                    exec("run(['wtype', '-k', 'Up'], check=True)\n" * _check_number_for_click(text[i+1], 'вверх'))

                elif move in ('вниз', 'низ'):
                    exec("run(['wtype', '-k', 'Down'], check=True)\n" * _check_number_for_click(text[i+1], 'вниз'))

                elif move in ('влево', 'лево', 'налево'):
                    exec("run(['wtype', '-k', 'Left'], check=True)\n" * _check_number_for_click(text[i+1], 'влево'))

                elif move in ('вправо', 'право', 'направо'):
                    exec("run(['wtype', '-k', 'Right'], check=True)\n" * _check_number_for_click(text[i+1], 'вправо'))

                elif move in ('ентер', 'enter', 'en'):
                    exec("run(['wtype', '-k', 'Return'], check=True)\n" * _check_number_for_click(text[i+1], 'ентер'))

                elif move in ('tab', 'tap', 'таб', 'тап', 'top', 'топ'):
                    exec("run(['wtype', '-k', 'Tab'], check=True)\n" * _check_number_for_click(text[i+1], 'таб'))

                elif move in ('launcher', 'лаунчер'):
                    exec("run(['cosmic-launcher'], check=True)\n" * _check_number_for_click(text[i+1], 'лаунчер'))

                elif move in ('стереть', 'бэкспейс', 'backspace', 'удалить', 'очистить', 'отчистить'):
                    exec("run(['wtype', '-k', 'BackSpace'], check=True)\n" * _check_number_for_click(text[i+1], 'backspace'))

                elif move in ('эскейп', 'ескейп', 'escape'):
                    exec("run(['wtype', '-k', 'Escape'], check=True)\n" * _check_number_for_click(text[i+1], 'backspace'))

                elif move in ('пробел', 'спейс', 'space'):
                    exec("run(['wtype', '-k', 'Space'], check=True)\n" * _check_number_for_click(text[i+1], 'backspace'))

        except (IndexError, ValueError):
            pass
            speak(f'извини, {name}, возникла ошибка, у меня не получилось ничего нажать')

    # ---------------------------------------------------------------------
    # мультимедиа
    # ---------------------------------------------------------------------

    elif 'громкость' in text.lower() or 'звук' in text.lower():
        text = text.lower().replace('.', '').replace(',', '').replace(' ', '').replace('громкость', '').replace('звук', '')

        if 'выключи' in text:
            system('wpctl set-mute @DEFAULT_AUDIO_SINK@ 1')

        elif 'включи' in text:
            system('wpctl set-mute @DEFAULT_AUDIO_SINK@ 0')

        else:
            value = _check_number(text)
            if value is not None:
                system(f'wpctl set-volume @DEFAULT_AUDIO_SINK@ {value / 100}')
                speak(f'установила громкость {num2words(value, lang='ru')}')

            else:
                speak(f'извини, {name}, я не услышала что нужно сделать')

    elif ('старт' in text.lower() or 'воспроизв' in text.lower() or 'воспроизв' in text.lower()
          or 'play' in text.lower()):

        system(play_cmd)

    elif 'пауза' in text.lower() or 'стоп' in text.lower():
        system(pause_cmd)

    elif 'следующий' in text.lower() or 'скип' in text.lower() or 'даль' in text.lower():

        system(next_cmd)

    elif 'пред' in text.lower() or 'назад' in text.lower() or 'обратно' in text.lower() or 'верни' in text.lower():
        system(previous_cmd)

    # ---------------------------------------------------------------------
    # приветствие
    # ---------------------------------------------------------------------

    elif 'привет' in text.lower() or 'здравствуй' in text.lower() or 'дома' in text.lower():
        speak(f'здравствуй, {name}, чем я могу тебе помочь?')

    # ---------------------------------------------------------------------
    # кастомные команды
    # ---------------------------------------------------------------------

    else:
        for pair in custom_commands:
            if pair[0] in text.lower():
                run(pair[1])
                speak(f'выполнила команду {pair[0]}')
                break

        else:
            speak(f'извини, {name} я не поняла команду')


# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def main():
    # сообщаем frontend, что executor запущен
    emit(
        {
            'type': 'state',
            'state': 'idle',
        }
    )

    emit(
        {
            'type': 'log',
            'message': 'executor ready',
        }
    )

    # получаем уже распознанный текст через stdin
    for line in sys.stdin:
        line = line.strip()


        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        # завершение executor
        if message.get('type') == 'shutdown':
            break

        # выполнение команды
        if message.get('type') == 'command':
            text = message.get('text', '')

            if not text:
                continue

            emit(
                {
                    'type': 'state',
                    'state': 'processing',
                }
            )

            try:
                navi(text)

                emit(
                    {
                        'type': 'response',
                        'message': 'done',
                        'state': 'idle',
                    }
                )

            except Exception as _error:
                emit(
                    {
                        'type': 'log',
                        'message': f'executor error: {_error}',
                    }
                )

                emit(
                    {
                        'type': 'state',
                        'state': 'error',
                    }
                )

if __name__ == '__main__':
    main()
