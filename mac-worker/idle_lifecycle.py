"""Track actual in-flight ASGI requests, including streaming responses."""

import time


class IdleTracker:
    def __init__(self, idle_seconds, clock=time.monotonic):
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.active = 0
        self.last_activity = clock()

    def begin(self):
        self.active += 1

    def end(self):
        self.active -= 1
        self.last_activity = self.clock()

    def expired(self):
        return (
            self.active == 0 and self.clock() - self.last_activity >= self.idle_seconds
        )


class TrackActivity:
    def __init__(self, app, tracker):
        self.app = app
        self.tracker = tracker

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        self.tracker.begin()
        try:
            await self.app(scope, receive, send)
        finally:
            self.tracker.end()
