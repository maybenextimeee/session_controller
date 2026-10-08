# Session Controller — для разработчиков

Как запустить программу из исходников, прогнать тесты, собрать установщик и
выпустить релиз. План и архитектура — в [PLAN.md](PLAN.md).

## Запуск из исходников (Windows)

Нужен Python 3.12 или новее: <https://www.python.org/downloads/>
(при установке отметь «Add python.exe to PATH»).

Один раз, в папке проекта (PowerShell или cmd):

```bat
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

1. `py -m venv .venv` создаёт виртуальную среду (папку `.venv`).
2. Вторая команда ставит библиотеки в эту среду. Повторять после изменения
   `requirements*.txt`.

Если PowerShell пишет «Не удалось загрузить модуль ".venv"», значит папки `.venv`
ещё нет — выполни первую команду.

**Запуск:** двойной клик по `start.bat` в папке проекта. Или из терминала:

```bat
.\.venv\Scripts\python -m session_controller
```

**Не запускай из терминала VS Code**, если в списке включён «VS Code»: чтобы
очистить VS Code, программе нужно его закрыть, а вместе с ним закрылась бы и
она сама (программа это замечает и отказывается начинать сессию). То же с
терминалом Claude Code и целью «Claude Code».

Файлы программы лежат в `%LOCALAPPDATA%\SessionController`: `settings.json`,
`session.json` (журнал идущей сессии), `backup\` (снимок «как было»), `log.txt`.
Для опытов можно указать другую папку переменной `SESSION_CONTROLLER_HOME`.

**Тесты:**

```bat
.\.venv\Scripts\python -m pytest
```

## Сборка exe и установщика

Автоматически: при каждом пуше на GitHub сервер с Windows прогоняет тесты,
собирает программу и установщик (вкладка **Actions** → нужный запуск →
**Artifacts**).

Вручную на своём компьютере (для установщика нужен
[Inno Setup 6](https://jrsoftware.org/isdl.php)):

```bat
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Результат — в папке `dist`. Значок программы рисуется кодом
(`session_controller/icons.py`); после его изменения обнови `assets/icon.ico`:
`python packaging/make_icon.py`.

## Как выпустить релиз

1. Поменяй версию в `session_controller/__init__.py` и текст релиза в
   `packaging/release-notes.md`, закоммить и запушь в `main`.
2. Дождись, пока на вкладке **Actions** сборка `main` станет зелёной.
3. Поставь тег `v` + версия и запушь его:

   ```bat
   git tag v0.5.0
   git push origin v0.5.0
   ```

Через несколько минут на странице Releases появится релиз: сверху текст из
`packaging/release-notes.md`, в файлах — установщик. Если тег не совпадает с
версией в `__init__.py`, сборка остановится и релиз не создастся.

## Структура

```
session_controller/
├── __main__.py     ← точка входа (python -m session_controller)
├── app.py          ← окно (главная и настройки), трей, реакция на выключение Windows
├── theme.py        ← светлая и тёмная тема, шрифты, стиль окна
├── widgets.py      ← переключатели, карточки, кнопка сессии, слой поверх окна, фон
├── dialogs.py      ← окна-вопросы и сообщения в стиле программы
├── icons.py        ← значок программы и значки браузеров / приложений
├── session.py      ← движок: начать / завершить сессию, журнал, восстановление
├── targets.py      ← что очищаем: браузеры, приложения, где они хранят входы
├── processes.py    ← поиск и закрытие программ
├── snapshot.py     ← снимок папки или файла и откат к нему
├── registry.py     ← реестр Windows
├── credentials.py  ← диспетчер учётных данных Windows
├── settings.py     ← настройки
├── paths.py        ← где лежат файлы программы
├── winapi.py       ← функции Windows, которых нет в Qt
└── autostart.py    ← автозапуск вместе с Windows
tests/              ← тесты (pytest); test_windows.py — только для Windows
packaging/          ← сборка: exe (PyInstaller), установщик (Inno Setup), значок, текст релиза
assets/icon.ico     ← значок для exe и установщика
.github/workflows/  ← автосборка на GitHub
docs/PLAN.md        ← план проекта, этапы, архитектура
start.bat           ← запуск из исходников двойным кликом
```

Чтобы добавить новую программу, достаточно описать её в `targets.py`: какие
папки и файлы запоминать и как называется её процесс. Одна программа — одна
карточка: разные программы не объединяем.
