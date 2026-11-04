"""Check this container's RQ heartbeat, including while a work horse runs."""

import os
import socket
from datetime import datetime, timezone
from redis import Redis
from rq import Worker


def main():
    redis = Redis.from_url(os.environ["REDIS_URL"])
    worker = Worker.find_by_key(f"rq:worker:{socket.gethostname()}", connection=redis)
    if worker is None or worker.last_heartbeat is None:
        raise SystemExit(1)
    age = (datetime.now(timezone.utc) - worker.last_heartbeat).total_seconds()
    raise SystemExit(0 if age < 120 else 1)


if __name__ == "__main__":
    main()
