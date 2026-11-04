import subprocess


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
