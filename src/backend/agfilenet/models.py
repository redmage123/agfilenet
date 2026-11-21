"""Where the local models live, and fetching them.

Nothing here runs a model. Files are downloaded once from the Hugging Face
hub into config.MODEL_DIR (the Docker image does it while building, so the
running container needs no network); after that every lookup is offline.
"""
from . import config


def path(repo, filename, fetch=False):
    """The local path of a model file, or None if it has not been fetched."""
    from huggingface_hub import hf_hub_download
    try:
        return hf_hub_download(repo, filename, cache_dir=str(config.MODEL_DIR), local_files_only=not fetch)
    except Exception:
        if fetch:
            raise
        return None


def present(repo):
    """Whether anything of this model has been fetched (a cheap check that loads nothing)."""
    return (config.MODEL_DIR / ("models--" + repo.replace("/", "--")) / "snapshots").is_dir()


def fetch_all(llm=True):
    """Download every model the application can use."""
    from fastembed import TextEmbedding
    TextEmbedding(config.EMBED_MODEL)
    for filename in config.RERANK_FILES:
        path(config.RERANK_MODEL, filename, fetch=True)
    for filename in config.NER_FILES:
        path(config.NER_MODEL, filename, fetch=True)
    if llm:
        path(config.LLM_REPO, config.LLM_FILE, fetch=True)
