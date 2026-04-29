# Детальный план реализации Автоинсталлеров (InstallerService)

## 1. Обзор архитектуры
Автоинсталлеры (InstallerService) предназначены для автоматического развертывания VPN-сервисов (3x-ui, AmneziaWG, MTProxy) на чистых или частично настроенных серверах через SSH.
Они используют паттерн "Провайдеров", опираясь на существующие `SSHManager` и `PortManager`.

### Основные компоненты:
*   `BaseInstaller`: Базовый класс, содержащий общие методы для подготовки сервера.
*   `AWGInstaller`, `MTProxyInstaller`, `XUIInstaller`: Специфичные классы для установки конкретных сервисов.
*   Интеграция с `AutoDiscoveryService` (чтобы после установки сразу проверить, что сервис поднялся).
*   UI-хэндлеры (FSM) в `app/bot/handlers/admin/servers.py` для инициации установки админом.

---

## 2. Базовая подготовка сервера (BaseInstaller)
Перед установкой любого сервиса бот должен гарантировать наличие базовых зависимостей на сервере.
Выполняется при каждом вызове инсталлера.

**Шаги `_prepare_server()`:**
1. Обновление пакетов: `apt-get update -y`
2. Проверка и установка Docker:
   * Команда: `docker --version || (curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh)`
3. Установка необходимых утилит: `apt-get install -y ufw sqlite3 curl jq`
4. Включение UFW (если не включен) с базовым правилом для SSH:
   * `ufw --force enable`
   * `ufw allow <ssh_port>/tcp`

---

## 3. Сценарии установки сервисов

### 3.1. Установка AmneziaWG (`AWGInstaller`)
**Процесс:**
1. Выделение порта: Запрос свободного UDP-порта у `PortManager` (например, `30120`).
2. Открытие порта в UFW: `ufw allow 30120/udp`.
3. Создание директории конфигов: `mkdir -p /opt/amnezia/awg`.
4. Генерация ключей сервера:
   * Выполняем генерацию Private/Public ключей для самого сервера (если делаем через docker - можно запустить временный контейнер для генерации или использовать Python библиотеку, но лучше через утилиту `awg`).
5. Создание базового `awg0.conf` с параметрами обфускации (Jc, Jmin, Jmax, S1-S4, H1-H4 - генерируются случайно).
6. Поднятие контейнера:
   * Используется образ `amneziavpn/amnezia-wg` (или аналог, поддерживающий AWG в Docker).
   * Проброс портов: `-p 30120:51820/udp`.
   * Volume: `-v /opt/amnezia/awg:/opt/amnezia/awg`.
   * Режим: `--cap-add NET_ADMIN --cap-add SYS_MODULE`.
7. **Сохранение в БД:** Создание записи `AWGService` и `AWGInbound` (с указанием сгенерированного порта).

### 3.2. Установка MTProxy (`MTProxyInstaller`)
**Процесс:**
1. Выделение порта: Запрос свободного TCP-порта (например, `443` или `8443`).
2. Открытие порта: `ufw allow 8443/tcp`.
3. Создание конфигурации:
   * Директория: `mkdir -p /opt/mtproxy`.
   * Файл секретов: `touch /opt/mtproxy/secrets.txt`.
4. Поднятие контейнера (образ с поддержкой Fake-TLS):
   * `docker run -d --name mtproxy --restart always -p 8443:443 -v /opt/mtproxy/secrets.txt:/data/secrets.txt telegrammessenger/proxy` (или форк).
5. **Сохранение в БД:** Создание `MTProxyService` и `MTProxyInbound`.

### 3.3. Установка 3x-ui (`XUIInstaller`)
Самый сложный инсталлер, так как требует взаимодействия с базой данных панели.

**Логика UI (до установки):**
Бот спрашивает: "Настроить параметры 3x-ui вручную или сгенерировать случайные (Auto)?"
*Если Auto:* Бот генерирует сложный логин/пароль, порт (например `2053`), `panel_path` (например `/admin-XYZ/`), `subPath` (`/sub-ABC/`), `subJsonPath` (`/json-DEF/`).
*Если Вручную:* FSM последовательно собирает эти 6 параметров у админа.

**Процесс установки:**
1. UFW: `ufw allow <panel_port>/tcp`.
2. Создание директории: `mkdir -p /opt/vpn/3x-ui/db`.
3. Поднятие контейнера (используем `host` network для корректной работы Inbounds, либо проброс портов):
   * `docker run -d --name 3x-ui --network host -v /opt/vpn/3x-ui/db:/etc/x-ui ghcr.io/mhsanaei/3x-ui:latest`
4. **Конфигурация SQLite (Магия):**
   * Ждем 3-5 секунд для инициализации БД контейнером: `sleep 5`.
   * Меняем порт и пути через `sqlite3` прямо в файле БД или через `docker exec`:
   ```bash
   docker exec -i 3x-ui sqlite3 /etc/x-ui/x-ui.db "DELETE FROM settings WHERE key IN ('webPort', 'webBasePath', 'subPath', 'subJsonPath');"
   docker exec -i 3x-ui sqlite3 /etc/x-ui/x-ui.db "INSERT INTO settings (key, value) VALUES ('webPort', '<PORT>'), ('webBasePath', '<PANEL_PATH>'), ('subPath', '<SUB_PATH>'), ('subJsonPath', '<JSON_PATH>');"
   ```
5. Смена пароля администратора через встроенную CLI утилиту 3x-ui:
   * `docker exec -i 3x-ui x-ui setting -username "<USERNAME>" -password "<PASSWORD>"`
6. Рестарт контейнера для применения: `docker restart 3x-ui`.
7. **Сохранение в БД:** Создание `XUIPanel` (пароль шифруется нашим `ENCRYPTION_KEY`).

---

## 4. Задачи для разработчика (Пошагово)

1. **Создать `app/services/installers/base.py`**:
   Реализовать класс `BaseInstaller` с методами `_ensure_docker()`, `_ensure_ufw()`.
2. **Создать `app/services/installers/xui_installer.py`** (и другие):
   Наследовать от `BaseInstaller`, реализовать метод `install(...)`.
3. **Обновить FSM в `app/bot/states/admin.py`**:
   Добавить стейты для ручного сбора параметров установки 3x-ui (`waiting_for_install_xui_port`, `waiting_for_install_xui_paths` и т.д.).
4. **Добавить обработчики в `app/bot/handlers/admin/servers.py`**:
   * Для кнопок `service_install_awg_`
   * Для кнопок `service_install_mtproxy_`
   * Для кнопок `service_install_xui_` (с развилкой Auto/Manual).
5. **Обработка Inbounds для 3x-ui**:
   Опционально: после установки 3x-ui бот может сразу через API XUIService создать базовый Inbound (например, VLESS Reality), чтобы панель была сразу готова к работе.

---
*Документ подготовлен для передачи следующему этапу разработки. Текущая структура БД (Polymorphic Inheritance) полностью поддерживает добавление сервисов.*