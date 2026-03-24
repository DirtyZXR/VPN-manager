"""Script to reset database with new schema."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import init_db, engine, async_session_factory
from app.database.models.base import Base


async def reset_database():
    """Reset database with new schema."""
    # Delete existing database file
    db_path = Path("data/vpn_manager.db")
    if db_path.exists():
        db_path.unlink()
        print(f"Deleted existing database: {db_path}")

    # Create new database with new schema
    print("Creating new database with updated schema...")
    await init_db()
    print("Database created successfully!")


def main():
    """Run reset script."""
    try:
        asyncio.run(reset_database())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()