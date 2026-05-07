"""
Мониторинг разблокировки нескольких пользователей в Telegram
Проверяет каждые 3 секунды, доступен ли профиль каждого пользователя
"""

import asyncio
import sys
import os
import json
from datetime import datetime
from telethon import TelegramClient, errors
from telethon.tl.types import User

CONFIG_FILE = 'config.json'
SESSION_FILE = 'monitor_session'

# Интервал проверки в секундах
CHECK_INTERVAL = 3


def load_config():
    """Загрузка конфигурации из файла"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_config(config):
    """Сохранение конфигурации в файл"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def setup_config():
    """Первоначальная настройка"""
    print("=" * 60)
    print("ПЕРВОНАЧАЛЬНАЯ НАСТРОЙКА")
    print("=" * 60)
    print("\n1. Получите API credentials на https://my.telegram.org/apps")
    print("2. Войдите с номером телефона и создайте приложение")
    print("3. Скопируйте API ID и API Hash\n")

    api_id = input("Введите API ID: ").strip()
    api_hash = input("Введите API Hash: ").strip()

    print("\n4. Введите username'ы пользователей для мониторинга (с @)")
    print("   Вводите по одному, пустая строка для завершения\n")

    target_users = []
    while True:
        user = input(f"Пользователь #{len(target_users) + 1} (или Enter для завершения): ").strip()
        if not user:
            break
        if not user.startswith('@'):
            user = '@' + user
        target_users.append(user)

    if not target_users:
        print("\n✗ Нужно указать хотя бы одного пользователя!")
        sys.exit(1)

    config = {
        'api_id': int(api_id),
        'api_hash': api_hash,
        'target_users': target_users
    }

    save_config(config)
    print(f"\n✓ Конфигурация сохранена в {CONFIG_FILE}")
    print(f"✓ Будет мониториться {len(target_users)} пользователей\n")

    return config


class MultiUserMonitor:
    def __init__(self, api_id, api_hash, target_users):
        self.client = TelegramClient(SESSION_FILE, api_id, api_hash)
        self.target_users = target_users
        self.user_states = {}
        self.total_checks = 0

    async def start(self):
        """Запуск мониторинга"""
        await self.client.start()
        print(f"[{self._timestamp()}] ✓ Подключено к Telegram\n")

        # Получаем информацию о всех целевых пользователях
        print(f"[{self._timestamp()}] Поиск пользователей...")
        for target in self.target_users:
            try:
                entity = await self.client.get_entity(target)
                if isinstance(entity, User):
                    self.user_states[entity.id] = {
                        'entity': entity,
                        'blocked': None,
                        'checks': 0,
                        'name': entity.first_name or entity.username or str(entity.id)
                    }
                    print(f"[{self._timestamp()}] ✓ {entity.first_name} (@{entity.username}) - ID: {entity.id}")
                else:
                    print(f"[{self._timestamp()}] ✗ {target} - это не пользователь!")
            except Exception as e:
                print(f"[{self._timestamp()}] ✗ Ошибка при поиске {target}: {e}")

        if not self.user_states:
            print(f"\n[{self._timestamp()}] ✗ Не найдено ни одного пользователя для мониторинга!")
            return

        print(f"\n[{self._timestamp()}] Начинаю мониторинг {len(self.user_states)} пользователей")
        print(f"[{self._timestamp()}] Проверка каждые {CHECK_INTERVAL} сек")
        print(f"[{self._timestamp()}] Уведомление только при разблокировке")
        print(f"[{self._timestamp()}] Нажмите Ctrl+C для остановки\n")

        # Основной цикл мониторинга
        try:
            while True:
                await self._check_all_users()
                await asyncio.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print(f"\n[{self._timestamp()}] Мониторинг остановлен пользователем")
        finally:
            await self.client.disconnect()

    async def _check_all_users(self):
        """Проверка статуса всех пользователей"""
        self.total_checks += 1

        for user_id, state in self.user_states.items():
            await self._check_user_status(user_id, state)

    async def _check_user_status(self, user_id, state):
        """Проверка статуса одного пользователя"""
        state['checks'] += 1

        try:
            user = await self.client.get_entity(user_id)
            is_blocked = False

            if user.status is None:
                is_blocked = True
            elif hasattr(user.status, '__class__'):
                status_type = user.status.__class__.__name__
                if status_type == 'UserStatusEmpty':
                    is_blocked = True
                else:
                    is_blocked = False

        except errors.UserIsBlockedError:
            is_blocked = True
        except errors.YouBlockedUserError:
            print(f"[{self._timestamp()}] ⚠ Вы сами заблокировали {state['name']}")
            is_blocked = True
        except Exception as e:
            if "blocked" in str(e).lower():
                is_blocked = True
            else:
                is_blocked = True

        # Определяем изменение статуса
        if state['blocked'] is None:
            state['blocked'] = is_blocked
        elif state['blocked'] and not is_blocked:
            await self._notify_unblocked(state)
        elif not state['blocked'] and is_blocked:
            state['blocked'] = True

        state['blocked'] = is_blocked

    async def _notify_unblocked(self, state):
        """Уведомление о разблокировке"""
        timestamp = self._timestamp()
        entity = state['entity']
        username = f"@{entity.username}" if entity.username else "без username"

        message = f"🎉 РАЗБЛОКИРОВКА!\n\n" \
                  f"Пользователь {state['name']}\n" \
                  f"Username: {username}\n" \
                  f"ID: {entity.id}\n\n" \
                  f"разблокировал вас!\n\n" \
                  f"Время: {timestamp}\n" \
                  f"Проверка #{state['checks']}"

        print(f"\n{'='*60}")
        print(message)
        print(f"{'='*60}\n")

        try:
            await self.client.send_message('me', message)
            print(f"[{timestamp}] ✓ Уведомление отправлено в Избранное")
        except Exception as e:
            print(f"[{timestamp}] ✗ Ошибка отправки уведомления: {e}")

        state['blocked'] = False

    @staticmethod
    def _timestamp():
        """Текущее время для логов"""
        return datetime.now().strftime("%H:%M:%S")


async def main():
    """Точка входа"""
    # Загружаем или создаём конфигурацию
    config = load_config()

    if not config:
        print("Конфигурация не найдена. Запускаю первоначальную настройку...\n")
        config = setup_config()

    # Запуск мониторинга
    monitor = MultiUserMonitor(
        config['api_id'],
        config['api_hash'],
        config['target_users']
    )
    await monitor.start()


if __name__ == '__main__':
    asyncio.run(main())
