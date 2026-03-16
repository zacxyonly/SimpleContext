from .base import BaseStorage
from .sqlite import SQLiteStorage


def create_storage(config) -> BaseStorage:
    """
    Factory: buat storage backend berdasarkan config.
    Backend baru bisa ditambah di sini tanpa ubah core.
    """
    backend = config.get("storage.backend", "sqlite")

    if backend in ("sqlite", "memory"):
        path = ":memory:" if backend == "memory" else config.get("storage.path", "./simplecontext.db")
        return SQLiteStorage(db_path=path)

    if backend == "redis":
        from .redis import RedisStorage
        return RedisStorage(
            url=config.get("storage.url", "redis://localhost:6379/0"),
            prefix=config.get("storage.prefix", "sc"),
        )

    if backend in ("postgresql", "postgres"):
        from .postgres import PostgreSQLStorage
        return PostgreSQLStorage(dsn=config.get("storage.dsn", ""))

    raise ValueError(
        f"Storage backend '{backend}' tidak dikenal. "
        f"Tersedia: sqlite, memory, redis, postgresql"
    )
