"""2026-11-14: jobs in separate loops can write the same cache entry at once; one shared ".tmp" name made the second
rename fail."""
from __future__ import annotations

import threading


def test_concurrent_writes_of_one_entry_all_succeed(tmp_path, caplog):
    from forliosa.marketdata.http import DiskCache

    cache = DiskCache(tmp_path)
    barrier = threading.Barrier(8)

    def write(i: int) -> None:
        barrier.wait()
        for _ in range(20):
            cache.write("shioaji-data", "meta/manifest", f"{i}".encode())

    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert "cache write failed" not in caplog.text
    assert not list(tmp_path.rglob("*.tmp"))
