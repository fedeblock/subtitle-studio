import importlib.util
from pathlib import Path


def test_gateway_agent_is_activated_on_demand(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts" / "install-mac-service.py"
    spec = importlib.util.spec_from_file_location("mac_service", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "Subtitle Studio"
    config = module.agent_config(root, tmp_path / "logs", "/opt/homebrew/bin", 8765)
    assert not config.get("RunAtLoad", False)
    assert not config.get("KeepAlive", False)
    assert config["Sockets"]["Listeners"]["SockServiceName"] == "8765"
    assert config["EnvironmentVariables"]["STUDIO_LAUNCHD_SOCKET"] == "1"
    assert config["WorkingDirectory"] == str(root)
    assert config["ProgramArguments"] == [
        "/bin/bash",
        str(root / "scripts/start-mac.sh"),
    ]
    assert "/opt/homebrew/bin" in config["EnvironmentVariables"]["PATH"].split(":")


def test_idle_tracker_does_not_expire_active_operations():
    from idle_lifecycle import IdleTracker

    now = [0.0]
    tracker = IdleTracker(600, clock=lambda: now[0])
    tracker.begin()
    now[0] = 700
    assert not tracker.expired()
    tracker.end()
    now[0] = 1299
    assert not tracker.expired()
    now[0] = 1300
    assert tracker.expired()


def test_activity_remains_tracked_until_stream_finishes():
    import asyncio
    from idle_lifecycle import IdleTracker, TrackActivity

    async def exercise():
        now = [0.0]
        tracker = IdleTracker(600, clock=lambda: now[0])
        started = asyncio.Event()
        release = asyncio.Event()

        async def stream(scope, receive, send):
            started.set()
            await release.wait()

        task = asyncio.create_task(
            TrackActivity(stream, tracker)({"type": "http"}, None, None)
        )
        await started.wait()
        now[0] = 700
        assert not tracker.expired()
        release.set()
        await task
        now[0] = 1300
        assert tracker.expired()

    asyncio.run(exercise())
