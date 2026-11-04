"""Read-only regression test: consecutive RQ children must not reuse a DB socket.

Run from the checkout against a running Compose database:
    docker compose run --rm --no-deps -T --entrypoint python worker - < scripts/test-fork-postgres.py
"""
import os
from sqlalchemy import text
from app.worker import ForkSafeWorker, Worker, engine

# Initialize a real pool connection in the parent, exactly as worker startup does.
with engine.begin() as connection:
    parent_backend = connection.execute(text("select pg_backend_pid()")).scalar_one()


def fake_job(self, number, write_fd):
    # The same repeated, committed queries that trigger psycopg preparation.
    for index in range(10):
        with engine.begin() as connection:
            backend = connection.execute(text("select pg_backend_pid()")).scalar_one()
            connection.execute(
                text(f"select cast(:value as integer) + {number + 1}"),
                {"value": index},
            ).scalar_one()
    os.write(write_fd, str(backend).encode())


Worker.main_work_horse = fake_job
backends = []
for number in range(2):
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            object.__new__(ForkSafeWorker).main_work_horse(number, write_fd)
        except Exception as error:
            print(f"Job {number} failed: {type(error).__name__}: {error}", flush=True)
            os._exit(1)
        os._exit(0)
    os.close(write_fd)
    value = os.read(read_fd, 64)
    os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise SystemExit(f"Job {number} failed")
    backends.append(int(value))

# The parent must keep its own usable connection after both children have exited.
with engine.begin() as connection:
    assert connection.execute(text("select pg_backend_pid()")).scalar_one() == parent_backend
assert len(set([parent_backend, *backends])) == 3, (parent_backend, backends)
print("Two consecutive forked jobs passed; parent and children used independent PostgreSQL connections.")
