"""UUIDv7 identifiers following RFC 9562 section 5.7."""
import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """Use Unix milliseconds and secure randomness; ordering within a millisecond is unspecified."""
    native = getattr(uuid, 'uuid7', None)
    if native is not None:
        return native()
    timestamp = (time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    random = secrets.randbits(74)
    return uuid.UUID(int=(timestamp << 80) | (7 << 76) | ((random >> 62) << 64)
                     | (2 << 62) | (random & ((1 << 62) - 1)))
