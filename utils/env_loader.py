import os
from pathlib import Path


DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_MODEL = "doubao-seed-2-1-pro-260628"
DEFAULT_ARK_API_KEY = ""

DEPRECATED_ARK_BASE_URLS = {
    "https://ark.cn-beijing.volces.com/api/plan/v3",
}

DEPRECATED_ARK_MODELS = {
    "ark-code-latest",
}


def load_local_env(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_ark_env() -> tuple[str, str]:
    """Keep the Ark entry on the normal OpenAI-compatible API path."""
    if not os.environ.get("VOLCANO_API_KEY"):
        os.environ["VOLCANO_API_KEY"] = os.environ.get("ARK_API_KEY", DEFAULT_ARK_API_KEY)

    base_url = os.environ.get("ARK_BASE_URL", "").strip()
    model = os.environ.get("ARK_MODEL", "").strip()

    if not base_url or base_url.rstrip("/") in DEPRECATED_ARK_BASE_URLS:
        base_url = DEFAULT_ARK_BASE_URL
        os.environ["ARK_BASE_URL"] = base_url

    if not model or model in DEPRECATED_ARK_MODELS:
        model = DEFAULT_ARK_MODEL
        os.environ["ARK_MODEL"] = model

    return base_url, model
