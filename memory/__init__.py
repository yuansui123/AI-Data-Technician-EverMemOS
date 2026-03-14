from memory.backend import FileMemoryBackend, MemoryBackend, get_memory_backend

__all__ = ["MemoryBackend", "FileMemoryBackend", "EverMemOSBackend", "get_memory_backend"]


def __getattr__(name: str):
    """Lazy import EverMemOSBackend so httpx isn't required when using file backend."""
    if name == "EverMemOSBackend":
        from memory.evermemos import EverMemOSBackend
        return EverMemOSBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
