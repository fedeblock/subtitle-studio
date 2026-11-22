import subprocess


def test_collect_multiple_videos_and_folder_preserves_sources(tmp_path):
    from local_files import collect_media_sources

    folder = tmp_path / "season"
    folder.mkdir()
    nested = folder / "disc"
    nested.mkdir()
    first = folder / "show.s01e01.mkv"
    second = nested / "show.s01e02.mp4"
    other = folder / "notes.txt"
    for path in (first, second, other):
        path.write_text("original")
    found = collect_media_sources([folder, first])
    assert set(found) == {first.resolve(), second.resolve()}
    assert all(path.read_text() == "original" for path in (first, second, other))


def test_audio_envelope_is_measured_without_copying_source(tmp_path):
    from local_files import audio_envelope

    source = tmp_path / "audio.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            str(source),
        ],
        check=True,
    )
    before = source.read_bytes()
    values = audio_envelope(source, 0, 0, 1, 10)
    assert len(values) == 10
    assert all(0 < value <= 1 for value in values)
    assert source.read_bytes() == before and list(tmp_path.iterdir()) == [source]


def test_audio_envelope_accepts_silence_from_ffmpeg(tmp_path):
    from local_files import audio_envelope

    source = tmp_path / "silence.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "1", "-c:a", "pcm_s16le", str(source)],
        check=True,
    )
    assert audio_envelope(source, 0, 0, 1, 10) == [0] * 10


def test_episode_sources_hide_other_episodes_and_recommend_matching_language(tmp_path):
    from local_files import discover_subtitles

    video = tmp_path / "Show.S01E02.mkv"
    video.touch()
    (tmp_path / "Show.S01E02.en.srt").write_text("a")
    (tmp_path / "Show.S01E03.en.srt").write_text("b")
    (tmp_path / "Subs").mkdir()
    (tmp_path / "Subs" / "Show.1x02.es.srt").write_text("c")
    items, _ = discover_subtitles(
        video,
        probe=lambda _: {
            "streams": [
                {"codec_type": "audio", "index": 1, "tags": {"language": "eng"}}
            ]
        },
    )
    files = {item["label"]: item for item in items}
    assert files["Show.S01E02.en.srt"]["match"] is True
    assert files["Show.S01E03.en.srt"]["match"] is False
    assert files["Subs/Show.1x02.es.srt"]["match"] is True
    assert files["Show.S01E02.en.srt"]["recommended"] is True


def test_discover_srt_next_to_video_and_in_subs(tmp_path):
    from local_files import discover_subtitles

    video = tmp_path / "movie.mkv"
    video.write_bytes(b"video")
    (tmp_path / "movie.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    (tmp_path / "Subs").mkdir()
    (tmp_path / "Subs" / "Spanish.srt").write_text("subtitles")
    result, warnings = discover_subtitles(
        video,
        probe=lambda path: {
            "streams": [
                {
                    "index": 2,
                    "codec_type": "subtitle",
                    "codec_name": "subrip",
                    "tags": {"language": "eng", "title": "English"},
                },
                {
                    "index": 3,
                    "codec_type": "subtitle",
                    "codec_name": "hdmv_pgs_subtitle",
                    "tags": {"language": "spa"},
                },
            ]
        },
    )
    assert len(result) == 4
    assert {x["label"] for x in result if x["kind"] == "file"} == {
        "movie.en.srt",
        "Subs/Spanish.srt",
    }
    embedded = [x for x in result if x["kind"] == "embedded"]
    assert embedded[0]["supported"] is True
    assert embedded[1]["supported"] is False
    assert "OCR" in embedded[1]["reason"]


def test_discovery_does_not_follow_external_symlinks(tmp_path):
    from local_files import discover_subtitles

    folder = tmp_path / "video"
    folder.mkdir()
    video = folder / "movie.mp4"
    video.touch()
    secret = tmp_path / "private.srt"
    secret.write_text("private")
    (folder / "linked.srt").symlink_to(secret)
    candidates, _ = discover_subtitles(video, probe=lambda p: {"streams": []})
    assert candidates == []


def test_extract_embedded_text_with_real_ffmpeg(tmp_path):
    from local_files import discover_subtitles, read_subtitle

    srt = tmp_path / "source.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello locally\n")
    video = tmp_path / "movie.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=16x16:duration=1",
            "-i",
            str(srt),
            "-c:v",
            "libx264",
            "-c:s",
            "srt",
            str(video),
        ],
        check=True,
    )
    items, _ = discover_subtitles(video)
    embedded = next(x for x in items if x["kind"] == "embedded")
    text = read_subtitle(video, embedded)
    assert "Hello locally" in text and "00:00:00,000 --> 00:00:01,000" in text


def test_audio_tracks_are_discovered_and_selected_without_media_copy(tmp_path):
    import subprocess
    from array import array
    from local_files import discover_audio, decode_audio, stream_audio

    video = tmp_path / "two-tracks.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1",
            "-map",
            "0:a",
            "-map",
            "1:a",
            "-metadata:s:a:0",
            "language=eng",
            "-metadata:s:a:1",
            "language=spa",
            "-c:a",
            "pcm_s16le",
            str(video),
        ],
        check=True,
    )
    before = video.stat().st_size
    tracks = discover_audio(video)
    assert (
        len(tracks) == 2 and "eng" in tracks[0]["label"] and "spa" in tracks[1]["label"]
    )
    audio1 = array("h", decode_audio(video, tracks[0]["index"]))
    audio2 = array("h", decode_audio(video, tracks[1]["index"]))

    def crosses(samples):
        return sum(a <= 0 < b for a, b in zip(samples, samples[1:]))

    assert 400 < crosses(audio1) < 480 and 800 < crosses(audio2) < 950
    import asyncio

    async def collect():
        return b"".join(
            [chunk async for chunk in stream_audio(video, tracks[1]["index"], 0)]
        )

    encoded = asyncio.run(collect())
    pcm = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "pipe:1",
        ],
        input=encoded,
        capture_output=True,
        check=True,
    ).stdout
    streamed = array("h", pcm)
    assert 800 < crosses(streamed) < 950
    assert video.stat().st_size == before and list(tmp_path.iterdir()) == [video]


def test_decoding_a_subtitle_chunk_uses_requested_audio_and_time(tmp_path):
    from array import array
    from local_files import decode_audio_chunk

    source = tmp_path / "two-tracks.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=2",
            "-map",
            "0:a",
            "-map",
            "1:a",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    before = source.stat().st_size
    pcm = array("h", decode_audio_chunk(source, 1, 1, duration=1))
    crossings = sum(a <= 0 < b for a, b in zip(pcm, pcm[1:]))
    assert 15000 <= len(pcm) <= 16000
    assert 800 < crossings < 950
    assert source.stat().st_size == before and list(tmp_path.iterdir()) == [source]


def test_audio_preview_is_audible_and_uses_requested_track(tmp_path):
    import subprocess
    from array import array
    from local_files import audio_preview, discover_audio

    video = tmp_path / "sound.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=2",
            "-map",
            "0:a",
            "-map",
            "1:a",
            "-c:a",
            "pcm_s16le",
            str(video),
        ],
        check=True,
    )
    tracks = discover_audio(video)

    def crossings(index):
        mp3 = audio_preview(video, index, 0)
        pcm = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "pipe:1",
            ],
            input=mp3,
            capture_output=True,
            check=True,
        ).stdout
        samples = array("h", pcm)
        return sum(a <= 0 < b for a, b in zip(samples, samples[1:]))

    a, b = (crossings(t["index"]) for t in tracks)
    assert 750 < a < 1000 and 1500 < b < 1950
    assert list(tmp_path.iterdir()) == [video]


def test_audio_envelope_handles_silence_and_scientific_notation(monkeypatch):
    import local_files
    from types import SimpleNamespace
    local_files._cached_envelope.cache_clear()
    monkeypatch.setattr(local_files.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stderr='lavfi.astats.Overall.RMS_level=-inf\nlavfi.astats.Overall.RMS_level=-6.0206\nlavfi.astats.Overall.RMS_level=-1e1\n'))
    values=local_files._cached_envelope('/not-used', 1, 1, 0, 0, 1, 3)
    assert values[0] == 0
    assert abs(values[1] - 0.5) < .001
    assert abs(values[2] - 10**(-0.5)) < .001
