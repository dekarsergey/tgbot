# 🤖 Telegram-бот с проверкой подписки и админ-панелью

## Структура проекта

```
tgbot/
├── bot.py                  # Точка входа
├── config.py               # Загрузка .env (безопасно)
├── requirements.txt
├── .env.example            # Шаблон переменных окружения
├── .gitignore              # .env и база не попадут в git
├── database/
│   └── db.py               # SQLite: пользователи, события, статистика
├── handlers/
│   ├── user.py             # Цепочка сообщений, проверка подписки
│   └── admin.py            # Adminка (только для ADMIN_IDS)
└── middlewares/
    └── logging_middleware.py  # Авторегистрация юзеров + UTM-метки
```

---

## 🚀 Быстрый старт

### 1. Установи зависимости

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Создай .env

```bash
cp .env.example .env
nano .env   # или открой в любом редакторе
```

Заполни:
| Переменная   | Где взять |
|-------------|-----------|
| `BOT_TOKEN` | @BotFather → /newbot |
| `CHANNEL_ID` | @username канала или числовой ID |
| `ADMIN_IDS`  | Свой Telegram ID → @userinfobot |

### 3. Добавь бота в канал как администратора

Бот должен быть администратором канала с правом **просматривать участников** — иначе проверка подписки не будет работать.

### 4. Запусти бота

```bash
python bot.py
```

---

## 🛡 Безопасность

- Токен хранится **только в `.env`** — никаких хардкодов
- `.env` добавлен в `.gitignore` — не попадёт в репозиторий
- Команда `/admin` доступна **только пользователям из `ADMIN_IDS`**
- Все остальные получат игнор на уровне фильтра роутера

---

## 📊 Возможности админ-панели (`/admin`)

| Раздел | Что показывает |
|--------|---------------|
| 📊 Статистика | Всего юзеров, подписанных, новых за день/неделю, активных за 24ч |
| 👥 Последние юзеры | 10 последних: имя, @username, дата, источник, статус подписки |
| 📡 Источники трафика | Откуда пришли пользователи (UTM-метки из ссылки) |
| 📣 Рассылка | Отправить сообщение всем пользователям сразу |

---

## 🔗 UTM-метки (источники трафика)

Делай разные ссылки для разных площадок:

```
https://t.me/ВАШ_БОТ?start=instagram
https://t.me/ВАШ_БОТ?start=youtube
https://t.me/ВАШ_БОТ?start=reels_23may
```

В разделе **«Источники трафика»** сразу увидишь, откуда приходят люди.

---

## 🖥 Деплой на VPS

```bash
# Создай systemd-сервис для автозапуска
sudo nano /etc/systemd/system/tgbot.service
```

```ini
[Unit]
Description=Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/tgbot
ExecStart=/home/ubuntu/tgbot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tgbot
sudo systemctl start tgbot
sudo systemctl status tgbot
```
