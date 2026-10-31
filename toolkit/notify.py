"""Minimal ntfy publisher. Publishes as JSON to the server root so any UTF-8 text survives."""

import httpx


class NotifyError(Exception):
    """The notification could not be delivered to ntfy."""


class NtfyClient:
    def __init__(self, server_url: str, http: httpx.AsyncClient):
        self._server_url = server_url
        self._http = http

    async def publish(self, *, topic: str, title: str, message: str, links: dict[str, str]) -> dict:
        """Tapping the notification opens the first link; every link is also a button."""
        payload: dict = {
            "topic": topic,
            "title": title,
            "message": message,
            "tags": ["video_game"],
            "actions": [{"action": "view", "label": k, "url": v} for k, v in links.items()],
        }
        if links:
            payload["click"] = next(iter(links.values()))
        try:
            resp = await self._http.post(self._server_url, json=payload)
        except httpx.HTTPError as exc:
            raise NotifyError(
                f"The notification service is unreachable ({type(exc).__name__}). Nothing was sent."
            ) from exc
        if resp.status_code == 429:
            raise NotifyError("The notification service is rate-limiting us. Nothing was sent.")
        if not resp.is_success:
            raise NotifyError(
                f"The notification service rejected the message (HTTP {resp.status_code}). "
                "Nothing was sent."
            )
        return resp.json()
