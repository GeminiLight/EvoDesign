"""OAuth provider profile fetching and normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class OAuthProfileError(ValueError):
    """Raised when an OAuth provider returns an unusable profile payload."""


@dataclass(frozen=True)
class OAuthUserProfile:
    """Normalized OAuth user identity used by AuthService."""

    email: str
    email_verified: bool
    username: str
    avatar_url: str | None
    provider_id: str


def _require_text(payload: Mapping[str, Any], key: str, provider: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise OAuthProfileError(f"{provider} profile missing required field: {key}")
    return value


def normalize_google_profile(profile: Mapping[str, Any]) -> OAuthUserProfile:
    """Normalize a Google userinfo payload."""
    email = _require_text(profile, "email", "Google")
    email_verified = profile.get("verified_email")
    if email_verified is None:
        email_verified = profile.get("email_verified")
    if email_verified is not True:
        raise OAuthProfileError("Google profile email is not verified")
    username = _require_text(profile, "name", "Google")
    provider_id = _require_text(profile, "id", "Google")
    avatar_url = profile.get("picture")

    return OAuthUserProfile(
        email=email,
        email_verified=True,
        username=username,
        avatar_url=avatar_url if isinstance(avatar_url, str) and avatar_url else None,
        provider_id=provider_id,
    )


def normalize_github_profile(
    profile: Mapping[str, Any],
    emails: Sequence[Mapping[str, Any]],
) -> OAuthUserProfile:
    """Normalize GitHub user and email payloads."""
    login = _require_text(profile, "login", "GitHub")
    provider_id_raw = profile.get("id")
    if provider_id_raw is None:
        raise OAuthProfileError("GitHub profile missing required field: id")

    primary_verified_email = next(
        (
            item.get("email")
            for item in emails
            if item.get("primary")
            and item.get("verified") is True
            and isinstance(item.get("email"), str)
            and item.get("email")
        ),
        None,
    )
    email = primary_verified_email or next(
        (
            item.get("email")
            for item in emails
            if item.get("verified") is True
            and isinstance(item.get("email"), str)
            and item.get("email")
        ),
        None,
    )

    if not isinstance(email, str) or not email:
        raise OAuthProfileError("GitHub verified email required")

    name = profile.get("name")
    avatar_url = profile.get("avatar_url")
    return OAuthUserProfile(
        email=email,
        email_verified=True,
        username=name if isinstance(name, str) and name else login,
        avatar_url=avatar_url if isinstance(avatar_url, str) and avatar_url else None,
        provider_id=str(provider_id_raw),
    )


class OAuthProfileService:
    """Fetch normalized user profiles from configured OAuth providers."""

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    async def fetch_google_profile(self, access_token: str) -> OAuthUserProfile:
        """Fetch and normalize the Google user profile for an access token."""
        if not access_token:
            raise OAuthProfileError("Google access_token missing")

        import httpx

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise OAuthProfileError("Google profile fetch failed") from exc
        except ValueError as exc:
            raise OAuthProfileError("Invalid Google profile payload") from exc

        if not isinstance(payload, Mapping):
            raise OAuthProfileError("Invalid Google profile payload")
        return normalize_google_profile(payload)

    async def fetch_github_profile(self, access_token: str) -> OAuthUserProfile:
        """Fetch and normalize the GitHub user profile for an access token."""
        if not access_token:
            raise OAuthProfileError("GitHub access_token missing")

        import httpx

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                profile_response = await client.get(
                    "https://api.github.com/user",
                    headers=headers,
                )
                profile_response.raise_for_status()
                profile = profile_response.json()

                emails_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers=headers,
                )
                emails_response.raise_for_status()
                emails = emails_response.json()
        except httpx.HTTPError as exc:
            raise OAuthProfileError("GitHub profile fetch failed") from exc
        except ValueError as exc:
            raise OAuthProfileError("Invalid GitHub profile payload") from exc

        if not isinstance(profile, Mapping):
            raise OAuthProfileError("Invalid GitHub profile payload")
        if not isinstance(emails, list) or not all(isinstance(item, Mapping) for item in emails):
            raise OAuthProfileError("Invalid GitHub emails payload")
        return normalize_github_profile(profile, emails)
