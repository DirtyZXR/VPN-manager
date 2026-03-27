# Анализ и исправление системы уведомлений

## ✅ СДЕЛАНО:

### Основное исправление: Несоответствие group_key при проверке и логировании уведомлений

**Проблема:** Уведомления отправлялись каждый цикл проверки (каждые 10 минут) вместо одного раза.

**Причина:** В методах `_send_expiry_notification()` и `_send_traffic_notification()` ключ `group_key` всегда генерировался из `subscription.id`, а для PROFILE уровня должен был быть из `connection.id`. Это приводило к несоответствию ключей при проверке и логировании:

- **Проверка** (`_notification_sent()`): искала лог с ключом `[conn.id]`
- **Логирование** (`_send_expiry_notification()`): создавала лог с ключом `[sub.id]`
- **Результат:** Лог не находился → уведомление отправлялось снова

**Исправление:**
1. Добавлен метод `_get_notification_group_key()` который генерирует правильный ключ на основе уровня уведомления (PROFILE/SUBSCRIPTION/USER)
2. Обновлены методы `_send_expiry_notification()` и `_send_traffic_notification()` для использования правильного ключа
3. Добавлен параметр `subs_with_conns` в `_send_traffic_notification()` для поддержки PROFILE уровня

**Файл:** `app/services/notification_checker.py`
- Строки 516-541: добавлен метод `_get_notification_group_key()`
- Строка 635: обновлено в `_send_expiry_notification()`
- Строки 634-688: обновлен `_send_traffic_notification()` (добавлен параметр и обновлена логика)
- Строка 234: обновлен вызов `_send_traffic_notification()` с передачей `subs_with_conns`

## ⚠️ НАЙДЕНО ДОПОЛНИТЕЛЬНЫЕ ПРОБЛЕМЫ:

### 1. Проблема в `_group_subscriptions_by_traffic()` 🔴

**Место:** Строки 366-372 в `app/services/notification_checker.py`

```python
if len(group["subscriptions"]) == 1:
    subscription = group["subscriptions"][0]
    level = NotificationLevel.SUBSCRIPTION  # ← ПРОБЛЕМА!
    key = self._get_group_key([subscription.id])
```

**Проблема:** Не учитывается количество подключений для определения уровня PROFILE

**Описание:** В отличие от `_group_subscriptions_by_expiry()` где есть логика для PROFILE уровня (если одно подключение → уровень PROFILE), в `_group_subscriptions_by_traffic()` нет такой логики. Все уведомления трафика идут на уровень SUBSCRIPTION или USER.

**Влияние:** Логическая ошибка, но не вызывает дублирования уведомлений

**Что нужно исправить:** Добавить логику для определения PROFILE уровня аналогично `_group_subscriptions_by_expiry()`:

```python
if len(group["subscriptions"]) == 1:
    subscription = group["subscriptions"][0]

    # Find connections for this subscription
    sub_data = next(
        (item for item in subs_with_conns
         if item["subscription"].id == subscription.id),
        None
    )

    if sub_data and len(sub_data["connections"]) == 1:
        # Single connection -> profile level
        level = NotificationLevel.PROFILE
        key = self._get_group_key([sub_data["connections"][0].id])
    else:
        # Multiple connections or no connections data -> subscription level
        level = NotificationLevel.SUBSCRIPTION
        key = self._get_group_key([subscription.id])
```

---

### 2. Проблема с транзакциями в `main.py` 🟡

**Место:** Строки 77-79 в `app/main.py`

```python
async with async_session_factory() as session:
    notification_checker = NotificationChecker(session)
    await notification_checker.check_and_notify()
# ← НЕТ КОММИТА!
```

**Проблема:** При выходе из контекста происходит автоматический ROLLBACK если нет явного COMMIT

**Описание:** Хотя в методах `_send_expiry_notification()` и `_send_traffic_notification()` есть коммиты, но:

1. Если происходит ошибка ДО вызова методов отправки
2. Если никакие уведомления не отправляются в цикле
3. Если происходит ошибка после коммита, но до завершения цикла

Тогда изменения в сессии НЕ сохраняются!

**Влияние:** Минимальное, так как методы отправки делают коммит, но есть риск потери изменений в некоторых случаях

**Что нужно исправить:** Добавить гарантированный commit в конце цикла:

```python
async with async_session_factory() as session:
    notification_checker = NotificationChecker(session)
    await notification_checker.check_and_notify()
    await session.commit()  # ← ДОБАВИТЬ ЭТО
```

---

### 3. Неиспользуемый метод `NotificationLog.should_notify()` 🟡

**Место:** Строки 84-115 в `app/database/models/notification_log.py`

```python
@classmethod
def should_notify(
    cls,
    user_id: int,
    notification_type: str,
    level: str,
    group_key: str,
    sent_at: datetime,
    cooldown_hours: int = 24,
) -> bool:
```

**Проблема:** Метод существует, но НЕ ИСПОЛЬЗУЕТСЯ в коде

**Описание:** Вместо него используется `_notification_sent()` в `NotificationChecker`. Это создает дублирование логики проверки.

**Влияние:** Усложняет поддержку, но не вызывает проблем

**Что нужно сделать:**
- Либо удалить метод `should_notify()` если он больше не нужен
- Либо использовать его вместо `_notification_sent()` для упрощения кода

---

## 📊 СТАТУС КРИТИЧЕСКИХ ПРОБЛЕМ:

| Проблема | Статус | Влияние |
|-----------|---------|---------|
| Дублирование уведомлений каждые 10 минут | ✅ ИСПРАВЛЕНО | Критическое |
| Неверный уровень в traffic уведомлениях | ⚠️ НАЙДЕНО | Среднее |
| Отсутствие commit в main.py | ⚠️ НАЙДЕНО | Низкое |
| Неиспользуемый метод | ⚠️ НАЙДЕНО | Низкое |

## 🎯 РЕЗУЛЬТАТ:

Основная проблема с дублированием уведомлений **ИСПРАВЛЕНА**!

Теперь уведомления будут отправляться корректно - один раз для каждого события, с правильными кулдаунами и группировкой по уровням.
