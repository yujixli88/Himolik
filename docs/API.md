# Himolik: API для фронтенда

Все ответы в JSON. Ошибки: `{"error": "код", ...}`. Токен передаётся заголовком `Authorization: Bearer <token>`.

## Жёсткие правила для вёрстки (из-за защиты CSP)
Сервер отправляет `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'`. Поэтому:
- **никакого inline-JS и inline-CSS** (`<script>...</script>`, `style="..."`, `onclick="..."`): только внешние файлы из `/static/...`;
- **никаких CDN** (qrcodejs, Google Fonts, Bootstrap CDN и т. п.): всё хранить в `static/`. QR делает сервер, `qrcodejs` не нужен;
- картинки: только с нашего домена или `data:`.
Для локальной отладки можно запустить с `DEBUG=true`: CSP тогда не отправляется.

## Обязательное требование Положения (п. 4.8)
В интерфейсе чата должна быть заметная надпись, что ученик общается с ИИ, например: «Химолик — ИИ-лаборант. Он может ошибаться, важное проверяй у учителя». Не отправляйте и не просите в чате фамилию, телефон и другие личные данные: достаточно имени или ника.

## Публичные
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/catalog` | Предметы, реагенты и приборы (`items`: id, formula, name{ru,kk}, tag), готовые наборы (`presets`), имя ассистента |
| GET | `/api/rooms/{code}/qr.svg` | QR-код (SVG) со ссылкой `/?room=КОД`. Вставлять как `<img src>` |
| GET | `/healthz` | Проверка живости |

## Учитель
1. `POST /api/rooms` с `{"subject":"chemistry"|"physics","title":"…","items":["hcl","naoh",…]}`. В ответе `code` (6 цифр), `token` (сохранить в `localStorage`), `join_url`.
2. `GET /api/teacher/room` (с токеном). Состав комнаты и `students[]`: `name`, `online`, `found`/`total` (прогресс), `actions`, `questions`, `off_topic`. Опрашивать раз в 3–5 секунд.
3. `GET /api/teacher/students/{sid}/chat`: журнал вопросов ученика к ИИ (для контроля учителем).
4. `POST /api/teacher/chat` с `{"message":"…","lang":"ru"|"kk"}`: спросить ИИ по предмету, работе и выбранным приборам/реагентам. Состояние опыта учителя пустое; диалог хранится до закрытия комнаты.
5. `DELETE /api/teacher/room`: закрыть комнату.
6. `POST /api/teacher/restore` (то же тело, что у создания): восстановить комнату с тем же кодом, если сервер перезапустился (ответ 404 `room_not_found`).

## Ученик
1. `POST /api/join` с `{"code":"123456","name":"Айдар"}`. Код берётся из `?room=` в URL (QR) или вводится руками. В ответе `token` (сохранить), `room`, `state`, `found`, `total`, `snapshot`.
   При повторном входе или после перезапуска сервера передайте ещё `token`, `snapshot`, `found`: прогресс восстановится.
2. `GET /api/me`: текущее состояние.
3. `POST /api/act`:
   - химия: `{"action":"add","item":"hcl"}`, `{"action":"remove","index":0}`, `{"action":"reset"}`;
   - физика: то же + `{"action":"toggle","index":3}` (выключатель).
   Ответ: `state` (то, что рисовать), `snapshot`, `events` (новые наблюдения), `found`, `total`.
   - `state` у химии: `flask[]`, `liquid` (цвет), `solids[]`, `gas[]`, `heat`, `ph`, …
   - `state` у физики: `elements[]`, `emf`, `r_total`, `current`, `closed`, `short`, `burned`.
4. `POST /api/chat` с `{"message":"…","lang":"ru"|"kk"}`. Ответ: `{"answer":"…","on_topic":true|false}`. Если `on_topic=false`, ИИ вежливо отказал, показывайте `answer` как обычно.

## Коды ошибок
`400` bad_request / bad_code / bad_name · `401` unauthorized · `404` room_not_found / student_not_found · `409` room_full · `410` room_closed · `413` too_large · `422` bad_request · `429` rate_limited / ai_busy (есть `retry_after` в секундах и `message`) · `503` ai_unavailable (есть `message`) / server_busy.
При `401` у учителя или ученика отправьте человека на экран входа. При `404 room_not_found` вызовите `restore` (учитель) или `join` со снимком (ученик).

## Лимиты ИИ
400 символов в вопросе · 6 вопросов в минуту и 80 в час на ученика · 40 в минуту на комнату · 9 запросов в минуту ко всему Gemini.
