from dataclasses import dataclass
from types import SimpleNamespace
import pytest


def test_catalog_only_targets_the_selected_model(tmp_path):
    from model_catalog import model_entries, deletion_strategies

    @dataclass(frozen=True)
    class Repo:
        repo_id: str
        size_on_disk: int
        repo_path: object
        repo_type: str = "model"
        revisions: tuple = (SimpleNamespace(commit_hash="abc"),)

        def __hash__(self):
            return hash(self.repo_id)

    @dataclass
    class Cache:
        repos: frozenset
        cache_dir: object

        def delete_revisions(self, *ids):
            return (next(iter(self.repos)).repo_id, ids)

    cache = Cache(
        frozenset(
            {
                Repo("Qwen/asr", 10, tmp_path / "qwen-asr"),
                Repo("Qwen/aligner", 20, tmp_path / "qwen-aligner"),
                Repo("mlx-community/whisper-large-v3-mlx", 30, tmp_path / "whisper"),
                Repo("Other/private", 99, tmp_path / "other"),
            }
        ),
        tmp_path,
    )
    models = model_entries(cache, "Qwen/asr", "Qwen/aligner")
    assert models[0]["bytes"] == 30 and models[0]["cached"]
    assert models[0]["locations"] == [
        {"repo": "Qwen/asr", "path": str(tmp_path / "qwen-asr")},
        {"repo": "Qwen/aligner", "path": str(tmp_path / "qwen-aligner")},
    ]
    assert models[1]["locations"][0]["path"] == str(tmp_path / "whisper")
    assert [
        item[0]
        for item in deletion_strategies(cache, "whisper", "Qwen/asr", "Qwen/aligner")
    ] == ["mlx-community/whisper-large-v3-mlx"]
    with pytest.raises(ValueError):
        deletion_strategies(cache, "anything", "Qwen/asr", "Qwen/aligner")
    with pytest.raises(ValueError):
        deletion_strategies(cache, "qwen", "/outside/path", "Qwen/aligner")
    unsafe = Cache(
        frozenset({Repo("Qwen/asr", 10, tmp_path.parent / "outside")}), tmp_path
    )
    with pytest.raises(ValueError, match="no es segura"):
        deletion_strategies(unsafe, "qwen", "Qwen/asr", "Qwen/aligner")
