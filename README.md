# Motion Detector

![Python](https://img.shields.io/badge/python-3.12-blue)
![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-v0.1-orange)
![Platform](https://img.shields.io/badge/platform-linux-lightgrey)

Система видеонаблюдения с детекцией движения и публикацией событий через MQTT. Проект рассчитан на запуск на локальном сервере рядом с камерой, без публикации чего-либо в интернет.

Текущая версия — **v0.1**: работает запись архива, детекция движения, публикация событий в MQTT. Контейнеры для отправки уведомлений (Telegram и др.) разрабатываются отдельно и подключаются через MQTT как независимые сервисы.

**Репозиторий:** <https://github.com/VeterChul/motion_detector>

---

## Содержание

- [Что это и зачем](#что-это-и-зачем)
- [Принципы](#принципы)
- [Архитектура](#архитектура)
- [Контейнеры](#контейнеры)
- [MQTT: контракт между сервисами](#mqtt-контракт-между-сервисами)
- [Перед первым запуском](#перед-первым-запуском)
- [Параметры конфигурации](#параметры-конфигурации)
- [Запуск](#запуск)
- [Проверка работоспособности](#проверка-работоспособности)
- [Диагностика проблем](#диагностика-проблем)
- [Известные особенности](#известные-особенности)
- [Структура репозитория](#структура-репозитория)
- [Версии](#версии)
- [Что дальше](#что-дальше)

---

## Что это и зачем

Система для одной USB-камеры с микрофоном:

- ведёт **непрерывную запись** видео со звуком с хранением архива;
- **детектирует движение** в реальном времени;
- **публикует события** о движении в MQTT для дальнейшей обработки;
- автоматически перезапускает упавшие контейнеры.

Отправка уведомлений (Telegram, e-mail, что угодно) — это **отдельные сервисы**, которые подключаются к брокеру MQTT. Их можно менять, не затрагивая основную систему.

---

## Принципы

- **Разделение ответственности.** Запись архива, детекция движения и логика уведомлений — три независимые задачи. Каждая живёт в своём контейнере.
- **Асинхронная связь через MQTT.** Все сервисы общаются через MQTT-топики. Detector публикует события движения, отправители подписываются на них.
- **Архив — источник правды по видео.** Детектор не хранит видео у себя. Отправитель забирает нужные интервалы из архива mediamtx через Playback API.
- **Никаких публикаций наружу.** Все сервисы работают во внутренней Docker-сети. Только HLS для живого просмотра доступен на `127.0.0.1`.

---

## Архитектура

Камера и микрофон подключены к серверу по USB. MediaMTX захватывает с них видео и звук, кодирует и пишет непрерывный архив в fMP4 на диск. Он же раздаёт RTSP-поток и предоставляет Playback API для запроса произвольных интервалов архива.

Detector подключается к RTSP-потоку, декодирует кадры, прогоняет их через MOG2 и публикует события движения в MQTT. Все события — маленькие JSON-сообщения с временными метками.

Mosquitto — брокер MQTT. Через него detector публикует события, а отправители (например, контейнер для Telegram) на них подписываются. В v0.1 отправителей нет, но detector уже публикует события — это контракт, который не изменится при появлении новых сервисов.

Архив пишется в `/srv/cctv/recordings`. Данные сервисов-отправителей (SQLite, outbox) будут храниться отдельно, в v0.1 этих данных нет.

Дополнительно работает `autoheal` — служебный контейнер, который перезапускает unhealthy-контейнеры. Docker Compose сам этого не делает.

---

## Контейнеры

### `mediamtx`

Медиасервер. Захватывает видео (v4l2, MJPEG) и звук (ALSA) с камеры и микрофона, кодирует в H.264 + AAC (одним процессом ffmpeg, поэтому видео и звук синхронизированы), ведёт непрерывную запись архива в fMP4 с автоудалением старых файлов, раздаёт RTSP на `:8554`, предоставляет Playback API на `:9997` и HLS на `127.0.0.1:8888`.

**Авторизация:**

- `publish` — только с localhost (для ffmpeg внутри контейнера).
- `read`, `playback`, `api` — пользователю `cctv` с паролем из `.env`.

---

### `detector`

Python-сервис. Подключается к RTSP-потоку mediamtx, декодирует кадры через PyAV, уменьшает их до 320 px, переводит в grayscale, размывает и прогоняет через MOG2. Публикует в MQTT события `motion_started` и `motion_stopped`, а также `heartbeat` раз в 5 секунд. Сохраняет кадры начала движения в `/data/snaps/`.

**Внутренняя структура:**

| Модуль | Ответственность |
|---|---|
| `main.py` | Точка входа, оркестрация потоков, основной цикл |
| `source.py` | Подключение к RTSP, чтение кадров, переподключение |
| `motion.py` | MOG2, препроцессинг, детекция движения |
| `publisher.py` | MQTT-клиент, публикация событий |

---

### `mosquitto`

MQTT-брокер. Принимает подключения только с логином/паролем (`allow_anonymous false`), хранит persistent-сессии и очереди QoS 1 для offline-подписчиков, ведёт системные топики `$SYS/...` для healthcheck.

---

### `autoheal`

Служебный контейнер. Слушает Docker-события через `/var/run/docker.sock` и перезапускает контейнеры с меткой `autoheal=true`, когда их healthcheck переходит в `unhealthy`. Сам перезапускается через `restart: always`, если падает.

Docker Compose не умеет сам этого делать — `restart: unless-stopped` перезапускает только упавшие контейнеры, а «зависшие, но живые» (unhealthy) остаются.

---

## MQTT: контракт между сервисами

Все сообщения — маленькие JSON. Detector **публикует**, отправители **подписываются**.

| Топик | QoS | Retained | Payload | Смысл |
|---|---|---|---|---|
| `cctv/detector/motion_started` | 1 | нет | `{"t": <unix>}` | Подтверждено движение в момент `t` |
| `cctv/detector/motion_stopped` | 1 | нет | `{"t": <unix>, "last_motion": <unix>}` | Событие закрыто. `last_motion` — время последнего кадра с движением |
| `cctv/detector/heartbeat` | 0 | нет | `{"t": ..., "uptime": ..., "frames": ..., "last_frame_age": ..., "motion_active": bool}` | «Я жив», раз в 5 секунд |
| `cctv/detector/state` | 1 | **да** | `{"last_motion": ..., "active": bool}` | Текущее состояние (retained — новый подписчик сразу получает) |

**Правила контракта:**

1. В MQTT передаются только метаданные (десятки байт). Никаких видео, картинок, бинарников.
2. QoS 1 для событий — гарантия доставки.
3. `state` — retained, чтобы отправитель при старте сразу знал текущее состояние.
4. Все временные метки — Unix time в UTC (секунды с плавающей точкой).

---

## Перед первым запуском

Пошаговая настройка перед первым `docker compose up`. Ничего не пропускайте — каждый шаг важен.

### 1. Клонировать репозиторий

```bash
git clone https://github.com/VeterChul/motion_detector cctv
cd cctv
```

### 2. Определить устройства камеры и микрофона

```bash
# Камера: список устройств
v4l2-ctl --list-devices

# Устойчивые пути по ID
ls -l /dev/v4l/by-id/

# Поддерживаемые форматы (важно: 1080p часто только в MJPEG)
v4l2-ctl --device=/dev/video0 --list-formats-ext

# Микрофоны
arecord -l
```

Запомните:

- **Путь к камере** — например, `/dev/v4l/by-id/usb-SunplusIT_Inc_Integrated_Camera_01.00.00-video-index0`.
- **Имя звуковой карты** — из вывода `arecord -l`, например `PCH` или `Camera`.

### 3. Подготовить папки

```bash
sudo mkdir -p /srv/cctv/recordings
sudo mkdir -p /srv/cctv/data/detector-snaps
sudo chown -R "$(id -u):$(id -g)" /srv/cctv
```

### 4. Создать `.env` из шаблона

```bash
cp .env.example .env
```

Открыть `.env` и заполнить **все** значения:

```env
# mediamtx: логин/пароль для detector (и будущих отправителей)
MTX_APP_USER=cctv
MTX_APP_PASS=<придумайте_пароль_1>

# MQTT: логин/пароль для подключения к брокеру
MQTT_USER=detector
MQTT_PASS=<придумайте_пароль_2>

# Часовой пояс (для корректного отображения времени)
TZ=Europe/Moscow
```

**Важно:** пароли без кавычек, без пробелов по краям. Проверить:

```bash
cat -A .env | grep -E 'MTX|MQTT'
```

В конце каждой строки должен быть `$` (перевод строки), без `^M` и лишних пробелов.

### 5. Сгенерировать `mosquitto/passwd`

Файл с хешем пароля MQTT. Логин должен совпадать с `MQTT_USER` из `.env`, пароль — с `MQTT_PASS`.

```bash
# Удалить старый, если есть
rm -f mosquitto/passwd

# Сгенерировать от вашего пользователя
docker run --rm -it --user "$(id -u):$(id -g)" \
  -v "$PWD/mosquitto:/work" \
  eclipse-mosquitto:2.0.20 \
  mosquitto_passwd -c /work/passwd detector

# Ввести пароль дважды (тот же, что MQTT_PASS в .env)
```

Исправить владельца файла на UID пользователя внутри контейнера mosquitto (1883):

```bash
sudo chown 1883:1883 mosquitto/passwd
sudo chmod 600 mosquitto/passwd
```

**Проверка:**

```bash
ls -la mosquitto/passwd
# ожидается: -rw------- 1 1883 1883 ... mosquitto/passwd
```

Если владелец не 1883 — брокер не сможет прочитать файл и упадёт.

### 6. Настроить `mediamtx/mediamtx.yml`

Открыть `mediamtx/mediamtx.yml` и заполнить два места.

**6.1. Пароль в `authInternalUsers`:**

```yaml
  - user: cctv
    pass: <тот_же_пароль_что_в_MTX_APP_PASS>
```

MediaMTX не читает `${MTX_APP_PASS}` из окружения в этом поле — пароль нужно вписать прямо в файл.

**6.2. Пути к устройствам в секции `paths.cam`:**

Найти блок `runOnInit` и заменить:

- `/dev/v4l/by-id/usb-SunplusIT_...-video-index0` — на ваш путь к камере (из шага 2).
- `hw:CARD=PCH` — на имя вашей звуковой карты (из шага 2).

**Важно про звук:** флаг `-use_wallclock_as_timestamps 1` нужно указывать **только на видеовходе**, но **не на ALSA-входе**. На аудио он вызывает рассинхрон меток и плееры не смогут открыть файлы.

Правильно:

```
-f v4l2 -use_wallclock_as_timestamps 1 ... -i /dev/v4l/by-id/...
-f alsa ... -i hw:CARD=PCH
```

Неправильно (ломает аудио):

```
-f alsa -use_wallclock_as_timestamps 1 ... -i hw:CARD=PCH
```

### 7. Настроить `detector/config.yaml`

Проверить, что все секции на месте. Параметры разобраны в разделе [Параметры конфигурации](#параметры-конфигурации). Минимальный вид:

```yaml
mediamtx:
  host: mediamtx
  port: 8554
  path: cam
  transport: tcp

mqtt:
  host: mosquitto
  port: 1883
  topic_prefix: cctv/detector

detector:
  process_every: 6
  width: 320
  min_area_ratio: 0.005
  warmup_frames: 100
  post_roll: 60
  max_skreen_count: 10

heartbeat:
  interval: 5
  file: /tmp/heartbeat

log:
  frame_log_interval: 5
```

### 8. Проверить, что камера и микрофон свободны

```bash
sudo lsof /dev/video0
sudo lsof /dev/snd/*
```

Если камеру или микрофон держит PulseAudio (типично для десктопной Ubuntu), на время тестов остановить:

```bash
systemctl --user stop pulseaudio.socket pulseaudio.service
```

Иначе ffmpeg внутри mediamtx получит `Device or resource busy`.

### 9. Проверить `.gitignore`

Убедиться, что в `.gitignore` есть:

```
.env
mosquitto/passwd
detector/wheels/
mediamtx/mediamtx.yml
```

Файл `mediamtx.yml` содержит пароль — в git ему не место.

---

## Параметры конфигурации

### `.env`

| Переменная | Обязательна | Смысл |
|---|---|---|
| `MTX_APP_USER` | да | Логин для подключения detector к RTSP и Playback API mediamtx |
| `MTX_APP_PASS` | да | Пароль. Должен совпадать с `pass:` в `mediamtx.yml` |
| `MQTT_USER` | да | Логин для MQTT. Должен совпадать с логином в `mosquitto/passwd` |
| `MQTT_PASS` | да | Пароль MQTT. Должен совпадать с паролем при генерации `mosquitto/passwd` |
| `TZ` | да | Часовой пояс, например `Europe/Moscow`. Влияет на время в логах |

### `mediamtx/mediamtx.yml`

| Параметр | Значение | Смысл |
|---|---|---|
| `logLevel` | `info` | Уровень логов. `debug` для отладки, `info` для продакшена |
| `authInternalUsers` | — | Правила доступа. `publish` только с localhost, `read`/`playback`/`api` — пользователю `cctv` |
| `apiAddress` | `:9997` | Порт API mediamtx. Используется Playback API и healthcheck |
| `rtspAddress` | `:8554` | Порт RTSP. К нему подключается detector |
| `hlsAddress` | `:8888` | Порт HLS для живого просмотра |
| `paths.cam.runOnInit` | — | Команда ffmpeg для захвата. Здесь задаются устройства, кодеки, параметры |
| `paths.cam.record` | `yes` | Включить запись архива |
| `paths.cam.recordFormat` | `fmp4` | Формат записи. fMP4 — сегментированный, mp4 — обычный |
| `paths.cam.recordPath` | `/recordings/%path/...` | Шаблон пути. `%path` = имя path (`cam`) |
| `paths.cam.recordDeleteAfter` | `72h` | Через сколько удалять старые записи |
| `paths.cam.recordSegmentDuration` | `5m` | **Обязательно.** Длина одного файла. Без этого получаются многогигабайтные файлы, которые плееры не открывают |
| `paths.cam.recordPartDuration` | `1s` | Длина fMP4-фрагмента. Позволяет воспроизводить файл, пока он пишется |
| `paths.cam.playback` | `yes` | Включить Playback API для запроса интервалов |

### `detector/config.yaml`

#### Секция `mediamtx`

| Параметр | Значение | Смысл |
|---|---|---|
| `host` | `mediamtx` | Имя сервиса в Docker-сети |
| `port` | `8554` | Порт RTSP |
| `path` | `cam` | Имя path в mediamtx |
| `transport` | `tcp` | Транспорт RTSP. `tcp` надёжнее, `udp` быстрее |

#### Секция `mqtt`

| Параметр | Значение | Смысл |
|---|---|---|
| `host` | `mosquitto` | Имя сервиса брокера |
| `port` | `1883` | Порт MQTT |
| `topic_prefix` | `cctv/detector` | Префикс топиков. К нему добавляется имя события |

#### Секция `detector`

| Параметр | Значение | Смысл |
|---|---|---|
| `process_every` | `6` | Обрабатывать каждый N-й кадр. При 30 fps даёт ~5 обработок/сек |
| `width` | `320` | Ширина кадра для анализа. Меньше — быстрее, но менее точно |
| `min_area_ratio` | `0.005` | Минимальная доля кадра с движением для срабатывания. 0.005 = 0.5%. Больше — меньше ложных, но можно пропустить слабое движение |
| `warmup_frames` | `100` | Сколько кадров только учить фон. При `process_every=6` и 30 fps это ~20 секунд |
| `post_roll` | `60` | Секунд тишины до закрытия события. Должно совпадать у всех сервисов, работающих с событием |
| `max_skreen_count` | `10` | Сколько кадров начала движения сохранять в `/data/snaps/` |

#### Секция `heartbeat`

| Параметр | Значение | Смысл |
|---|---|---|
| `interval` | `5` | Секунд между публикациями heartbeat |
| `file` | `/tmp/heartbeat` | Файл, обновляемый для healthcheck контейнера |

#### Секция `log`

| Параметр | Значение | Смысл |
|---|---|---|
| `frame_log_interval` | `5` | Раз в сколько секунд писать в лог количество полученных кадров |

---

## Запуск

```bash
# Собрать образ detector (тянет зависимости, первый раз долго)
docker compose build detector

# Запустить все сервисы
docker compose up -d

# Проверить статус
docker compose ps
```

Ожидаемый `docker compose ps` через минуту:

```
NAME        STATUS
autoheal    Up (healthy)
detector    Up (healthy)
mediamtx    Up (healthy)
mosquitto   Up (healthy)
```

### Порядок старта

Docker Compose учитывает `depends_on`. Реальный порядок:

1. Запускается `mosquitto`. Через ~15 секунд — `healthy`.
2. Запускается `mediamtx`. Через ~40 секунд — `healthy` (ffmpeg подключился к камере).
3. Запускается `detector`. Через ~60 секунд — `healthy` (heartbeat начал обновляться).
4. `autoheal` стартует сразу, но начинает следить только после `START_PERIOD=60` секунд.

Если `mediamtx` не запускается — detector тоже не стартует. Проверьте `docker compose logs mediamtx`.

---

## Проверка работоспособности

### Архив пишется

```bash
ls -lh /srv/cctv/recordings/cam/
```

Каждые 5 минут появляется новый файл. Размер растёт, пока файл пишется.

### RTSP отдаётся

```bash
docker compose exec mediamtx \
  ffprobe -rtsp_transport tcp -i rtsp://localhost:8554/cam
```

В выводе — две дорожки: `Video: h264` и `Audio: aac`.

### Detector читает кадры

```bash
docker compose logs -f detector
```

Ожидаемое:

```
INFO: MQTT connected
INFO: Detector started
INFO: Received 25 frames, last: shape=(1080, 1920, 3)
INFO: Received 50 frames, last: shape=(1080, 1920, 3)
```

### MQTT работает

Открыть второе окно терминала:

```bash
docker compose exec mosquitto \
  mosquitto_sub -h localhost -u detector -P '<MQTT_PASS>' -t 'cctv/#' -v
```

Каждые 5 секунд приходит heartbeat:

```
cctv/detector/heartbeat {"t": 1791179030.919, "uptime": 100.0, "frames": 2956, "last_frame_age": 0.06, "motion_active": false}
```

### Детекция движения работает

Помахать рукой перед камерой. В `mosquitto_sub` должно появиться:

```
cctv/detector/motion_started {"t": 1791179030.919}
```

Подождать `post_roll` секунд (по умолчанию 60, для тестов можно уменьшить) после прекращения движения:

```
cctv/detector/motion_stopped {"t": 1791179090.919, "last_motion": 1791179030.919}
```

В логах detector — строки `saved frame: /data/snaps/.../001.jpg`.

### Живой просмотр через SSH-туннель

HLS доступен только на `127.0.0.1` хоста с mediamtx. С удалённой машины:

```bash
ssh -L 8888:127.0.0.1:8888 user@your-server
```

Затем открыть в браузере `http://localhost:8888/cam`.

---

## Диагностика проблем

### mediamtx не поднимается

Смотреть логи:

```bash
docker compose logs mediamtx
```

| Симптом | Причина |
|---|---|
| `Device or resource busy` | Камера или микрофон заняты другим приложением |
| `No such file or directory` | Неверный путь в `runOnInit` |
| `Invalid argument` при v4l2 | Не тот формат (например, YUYV вместо MJPEG для 1080p) |
| Нет `publisher started` | ffmpeg молча упал, посмотрите `logLevel: debug` |

### Detector в цикле Restarting

```bash
docker compose logs detector
```

| Симптом | Причина |
|---|---|
| `KeyError: 'detector'` | В `config.yaml` нет секции `detector` |
| `401 Unauthorized` | Пароль в `.env` ≠ пароль в `mediamtx.yml` |
| `No module named 'numpy'` | Не хватает зависимости, пересобрать образ |
| `exited with code 0` | Пустые файлы в образе. Проверить `docker compose run --rm --entrypoint cat detector /app/detector/main.py` |

### mosquitto не пускает

```bash
docker compose logs mosquitto
```

| Симптом | Причина |
|---|---|
| `Unable to open password file` | Права на `mosquitto/passwd` (должно быть `1883:1883`, `600`) |
| `not authorised` | Пароль в `.env` ≠ пароль в `mosquitto/passwd` |

### Плеер не открывает видео

Основная причина — рассинхрон меток из-за `-use_wallclock_as_timestamps 1` на ALSA-входе. Проверить:

```bash
ffprobe -v error -show_format -show_streams <файл>.mp4 | grep duration
```

Все три duration (format, video, audio) должны быть **примерно равны**. Если аудио показывает часы или дни — флаг `-use_wallclock_as_timestamps` на ALSA нужно убрать.

Второе: `recordSegmentDuration`. Если его нет, файлы получаются многогигабайтные, и плееры могут не открывать их.

### Detector не публикует события

- Проверить, что warmup прошёл (`warmup_frames` × `process_every` кадров).
- Проверить `min_area_ratio` — возможно, слишком высокий.
- Проверить, что камера в фокусе и освещение не меняется резко.
- Посмотреть сохранённые кадры в `/srv/cctv/data/detector-snaps/`.

---

## Известные особенности

### fMP4 и живые файлы

MediaMTX пишет fMP4-сегменты. Файл, который **прямо сейчас пишется**, имеет неполные метаданные и может не открываться в некоторых плеерах. Смотреть нужно только **закрытые** сегменты — те, что появились 5+ минут назад и больше не растут.

### Audio timestamps

Флаг `-use_wallclock_as_timestamps` на ALSA-входе даёт метки, которые не вмещаются в формат MP4 (32-битное поле длительности). Это приводит к «24-часовым» аудио-дорожкам и падениям плееров. **Не использовать этот флаг на аудиовходе.**

### HLS на localhost

Порт 8888 опубликован как `127.0.0.1:8888:8888`. Это значит:

- с самого хоста mediamtx он доступен на `http://127.0.0.1:8888/cam`;
- из локальной сети — **нет**.

Проверить: `ss -tlnp | grep 8888` должно показать `127.0.0.1:8888`, а не `0.0.0.0:8888`. Docker обходит UFW, поэтому без `127.0.0.1:` HLS оказался бы доступен всей локальной сети.

### Autoheal

Образ `willfarrell/autoheal:1.2.0` иногда падает с `SIGSEGV` (код 139) при работе с новыми версиями Docker API. Это не критично: `restart: always` поднимает его обратно за секунды. В будущих версиях планируется замена на собственный Python-скрипт.

---

## Структура репозитория

```
cctv/
├── docker-compose.yml          # описание сервисов
├── .env.example                # шаблон секретов
├── .gitignore
├── README.md
├── LICENSE
│
├── mediamtx/
│   └── mediamtx.yml            # конфиг медиасервера
│
├── mosquitto/
│   ├── mosquitto.conf          # конфиг брокера
│   └── passwd                  # файл паролей (генерируется, в git не попадает)
│
└── detector/
    ├── Dockerfile
    ├── requirements.txt
    ├── config.yaml
    ├── wheels/                 # локальные .whl-файлы (в git не попадают)
    └── detector/
        ├── __init__.py
        ├── main.py             # точка входа
        ├── source.py           # чтение RTSP
        ├── motion.py           # детекция движения
        └── publisher.py        # MQTT-клиент
```

### Что не в git

- `.env` — секреты.
- `mosquitto/passwd` — хеши паролей.
- `mediamtx/mediamtx.yml` — содержит пароль mediamtx.
- `detector/wheels/` — большие `.whl`-файлы (av ~35 МБ, numpy ~17 МБ).
- `__pycache__/`, `.venv/`, `*.db`.

### Внешние тома на хосте

- `/srv/cctv/recordings` — архив видео.
- `/srv/cctv/data/detector-snaps` — кадры начала движения (для отладки).

---

## Версии

- `mediamtx`: `1.9.3-ffmpeg` (фиксированная)
- `mosquitto`: `2.0.20` (фиксированная)
- `autoheal`: `1.2.0` (фиксированная)
- Python в detector: `3.12-slim`

Все версии зафиксированы. `latest` не используется: обновление может принести breaking changes и сломать систему без предупреждения.

---

## Что дальше

В следующих версиях:

- **Контейнеры-отправители.** Каждый канал уведомлений (Telegram, e-mail, Matrix и т.п.) — отдельный сервис, подписанный на те же MQTT-топики.
- **Собственный autoheal** на Python вместо заброшенного образа `willfarrell/autoheal`.
- **Маски игнорируемых зон** в detector: окна, мониторы, часы.
- **Калибровочный режим** — сбор статистики детекции для тюнинга порогов.
- **Вторая ступень детекции** (YOLO-nano) для отсеивания ложных срабатываний.

---

## Лицензия

См. файл [LICENSE](LICENSE).