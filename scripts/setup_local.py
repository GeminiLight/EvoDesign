#!/usr/bin/env python3
"""Create a loopback-only local configuration without replacing existing files."""
from pathlib import Path
import secrets


def setup(root: Path) -> list[Path]:
    backend = root / ".env"
    frontend = root / "frontend" / ".env"
    # Refuse a partial existing installation: don't accidentally rotate secrets
    # or pair a new frontend with someone else's backend guest token.
    if backend.exists() or frontend.exists():
        raise FileExistsError("A .env already exists. Keep it and configure the other file manually; no files were changed.")
    guest = secrets.token_urlsafe(32)
    backend_text = (root / ".env.example").read_text()
    for key, value in {"JWT_SECRET": secrets.token_urlsafe(48), "SESSION_SECRET": secrets.token_urlsafe(48), "GUEST_TOKEN": guest}.items():
        backend_text = backend_text.replace(f"\n{key}=\n", f"\n{key}={value}\n")
    frontend_text = (root / "frontend" / ".env.example").read_text().replace("VITE_GUEST_TOKEN=\n", f"VITE_GUEST_TOKEN={guest}\n")
    created = []
    try:
        for path, content in [(backend, backend_text), (frontend, frontend_text)]:
            with path.open("x") as stream:
                created.append(path)
                path.chmod(0o600)
                stream.write(content)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return created


if __name__ == "__main__":
    try:
        setup(Path(__file__).resolve().parents[1])
    except FileExistsError as exc:
        raise SystemExit(str(exc)) from None
    print("Created .env and frontend/.env with unique local secrets. Fill LLM_MODEL_NAME, LLM_ENDPOINT_URL and LLM_API_KEY in .env. Do not expose the guest-enabled servers to the internet.")
