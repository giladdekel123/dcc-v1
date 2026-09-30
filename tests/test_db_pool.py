import threading

from app import db


def test_concurrent_first_requests_share_one_pool(monkeypatch):
    # Nothing listens here; the pool connects lazily, so only pool creation is exercised.
    monkeypatch.setenv("DATABASE_URL", "postgresql://dcc@127.0.0.1:1/dcc")
    barrier = threading.Barrier(8)
    pools = []

    def first_request():
        barrier.wait()
        pools.append(db.get_pool())

    threads = [threading.Thread(target=first_request) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(pools) == 8 and len({id(p) for p in pools}) == 1
