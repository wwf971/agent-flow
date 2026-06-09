from __future__ import annotations

import time
from threading import Lock

_ms48_id_lock = Lock()
_ms48_last_timestamp_ms = 0
_ms48_offset = -1


def create_ms48_id():
    global _ms48_last_timestamp_ms
    global _ms48_offset
    with _ms48_id_lock:
        timestamp_ms = int(time.time() * 1000)
        if timestamp_ms != _ms48_last_timestamp_ms:
            _ms48_last_timestamp_ms = timestamp_ms
            _ms48_offset = 0
        else:
            _ms48_offset = _ms48_offset + 1
            if _ms48_offset > 0xFFFF:
                while timestamp_ms <= _ms48_last_timestamp_ms:
                    time.sleep(0.001)
                    timestamp_ms = int(time.time() * 1000)
                _ms48_last_timestamp_ms = timestamp_ms
                _ms48_offset = 0
        return (_ms48_last_timestamp_ms << 16) | (_ms48_offset & 0xFFFF)
