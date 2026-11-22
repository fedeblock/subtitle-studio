"""Whitelisted ASR models and their shared Hugging Face cache entries."""

from dataclasses import replace
import re


WHISPER_REPO = "mlx-community/whisper-large-v3-mlx"


def is_hub_repo(repo):
    return (
        isinstance(repo, str)
        and bool(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo)
        )
        and ".." not in repo
    )


def catalog(asr_repo, aligner_repo):
    return {
        "qwen": {"label": "Qwen3-ASR 1.7B", "repos": [asr_repo, aligner_repo]},
        "whisper": {"label": "Whisper large-v3", "repos": [WHISPER_REPO]},
    }


def model_entries(cache, asr_repo, aligner_repo):
    repos = {item.repo_id: item for item in cache.repos if item.repo_type == "model"}
    return [
        {
            "id": key,
            "label": item["label"],
            "repos": item["repos"],
            "cached": all(repo in repos for repo in item["repos"]),
            "bytes": sum(
                repos[repo].size_on_disk for repo in item["repos"] if repo in repos
            ),
        }
        for key, item in catalog(asr_repo, aligner_repo).items()
    ]


def deletion_strategies(cache, model, asr_repo, aligner_repo):
    allowed = catalog(asr_repo, aligner_repo)
    if model not in allowed:
        raise ValueError("Modelo no disponible")
    targets = set(allowed[model]["repos"])
    # A custom path or unexpected identifier is never interpreted as a cache repo.
    if any(not is_hub_repo(repo) for repo in targets):
        raise ValueError(
            "La configuración contiene una ruta local; no se borrará automáticamente"
        )
    strategies = []
    for repo in cache.repos:
        if repo.repo_type != "model" or repo.repo_id not in targets:
            continue
        if (
            cache.cache_dir is None
            or repo.repo_path.is_symlink()
            or repo.repo_path.resolve().parent != cache.cache_dir.resolve()
        ):
            raise ValueError("La ruta de caché del modelo no es segura para borrar")
        only = replace(cache, repos=frozenset({repo}))
        strategies.append(
            only.delete_revisions(
                *(revision.commit_hash for revision in repo.revisions)
            )
        )
    return strategies
