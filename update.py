import os
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str], description: str) -> None:
    """Выполняет команду и выводит результат."""
    print(f"⏳ {description}...")
    try:
        # Запускаем команду с перехватом вывода
        result = subprocess.run(
            command, check=True, text=True, capture_output=True, encoding="utf-8"
        )
        print(f"✅ Успешно: {description}")
        # Выводим результат, если есть полезная информация
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                print(f"   > {line}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при выполнении: {description}")
        print("Подробности ошибки:")
        print(e.stderr or e.stdout)
        sys.exit(1)


def main():
    print("🚀 Запуск процесса обновления бота...\n")

    base_dir = Path(__file__).resolve().parent
    venv_dir = base_dir / ".venv"

    # Проверка наличия .venv
    if not venv_dir.exists():
        print(f"❌ Виртуальное окружение не найдено в: {venv_dir}")
        print("Убедитесь, что оно называется '.venv' и находится в корне проекта.")
        sys.exit(1)

    # Определение путей к исполняемым файлам в зависимости от ОС (Windows / Linux)
    if os.name == "nt":  # Windows
        pip_exe = venv_dir / "Scripts" / "pip.exe"
        python_exe = venv_dir / "Scripts" / "python.exe"
    else:  # Linux / macOS
        pip_exe = venv_dir / "bin" / "pip"
        python_exe = venv_dir / "bin" / "python"

    if not pip_exe.exists() or not python_exe.exists():
        print(f"❌ Исполняемые файлы Python/pip не найдены внутри {venv_dir}")
        sys.exit(1)

    # 1. Установка / Обновление зависимостей
    req_file = base_dir / "requirements.txt"
    if req_file.exists():
        run_command(
            [str(pip_exe), "install", "-r", str(req_file)],
            "Установка зависимостей из requirements.txt",
        )
    else:
        print("⚠️ Файл requirements.txt не найден, пропускаем обновление зависимостей.")

    # 2. Применение миграций БД
    # Вызываем python -m alembic для большей надежности (чтобы alembic точно использовал библиотеки из .venv)
    if (base_dir / "alembic.ini").exists():
        run_command(
            [str(python_exe), "-m", "alembic", "upgrade", "head"],
            "Применение миграций базы данных (Alembic)",
        )
    else:
        print("⚠️ Файл alembic.ini не найден, пропускаем миграции.")

    print("\n🎉 Обновление успешно завершено! Теперь вы можете перезапустить бота.")


if __name__ == "__main__":
    main()
