"""Nationex public tracking API client."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from .const import MAX_RESPONSE_BYTES, TRACKING_API_URL
from .parcels import NEW_ISSUE_URL, warn_once

_LOGGER = logging.getLogger(__name__)

_CHALLENGE = re.compile(
    r"_cf_chl_opt|cf-turnstile|<title>\s*(?:Just a moment|Attention Required)",
    re.IGNORECASE,
)
_NOT_FOUND_CODE = 404


class NationexApiError(Exception):
    """Raised when a Nationex API call returns an unexpected response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"Nationex API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


async def _read_capped(response: aiohttp.ClientResponse) -> bytes:
    """Read the body, refusing anything larger than a tracking reply can be."""
    body = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise NationexApiError("response too large")
    return bytes(body)


class NationexShipmentMismatchError(NationexApiError):
    """Raised when the reply is for another shipment than the number asked for."""


def _is_challenge(text: str) -> bool:
    return _CHALLENGE.search(text) is not None


def _warn_challenge() -> None:
    warn_once(
        "challenge",
        "Nationex answered with a bot-protection page instead of tracking "
        "data. If this persists, open an issue: %s",
        NEW_ISSUE_URL,
    )


def _matches(payload: dict[str, Any], tracking_code: str) -> bool:
    """Whether the shipment is the one asked for, not a lookalike match."""
    if str(payload.get("ShipmentId")) == tracking_code:
        return True
    parcels = payload.get("Parcels")
    if not isinstance(parcels, list):
        return False
    return any(
        isinstance(parcel, dict) and str(parcel.get("ParcelId")) == tracking_code
        for parcel in parcels
    )


class NationexApiClient:
    """Client for the public Nationex tracking endpoint.

    No authentication: the endpoint is keyed on the tracking number alone and
    answers HTTP 200 for both a shipment and an unknown number, so replies are
    sorted by body.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one shipment's tracking details.

        Returns the shipment dict, or ``None`` when the service reports the
        number as unknown. Anything inconclusive raises
        :class:`NationexApiError` so the last good data is kept, with
        :class:`NationexShipmentMismatchError` for a reply about another
        shipment; network
        errors propagate as ``aiohttp.ClientError``.
        """
        url = TRACKING_API_URL.format(tracking_code=tracking_code)
        async with self._session.get(
            url, headers={"Accept": "application/json"}, allow_redirects=False
        ) as response:
            if response.status == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = (
                        float(retry_after_header) if retry_after_header else None
                    )
                except ValueError:
                    retry_after = None  # an HTTP-date, not seconds
                raise NationexApiError(
                    "HTTP 429", status_code=429, retry_after=retry_after
                )
            if response.status == 403:
                if _is_challenge(
                    (await _read_capped(response)).decode(errors="replace")
                ):
                    _warn_challenge()
            if response.status != 200:
                raise NationexApiError(
                    f"HTTP {response.status}", status_code=response.status
                )
            text = (await _read_capped(response)).decode(errors="replace")

        try:
            payload = json.loads(text)
        except ValueError as err:
            if _is_challenge(text):
                _warn_challenge()
                raise NationexApiError("bot-protection challenge") from err
            raise NationexApiError("unparseable body") from err

        if not isinstance(payload, dict):
            raise NationexApiError("unexpected body (not a JSON object)")

        if payload.get("ShipmentId") is not None:
            if _matches(payload, tracking_code):
                return payload
            warn_once(
                "id-mismatch",
                "Nationex answered with a shipment that does not carry the "
                "number asked for, so it is ignored. Delivery-notice numbers "
                "and sender references are not supported. Open an issue if "
                "this is a real tracking number: %s",
                NEW_ISSUE_URL,
            )
            raise NationexShipmentMismatchError("reply is for a different shipment")

        code = payload.get("code")
        if code == _NOT_FOUND_CODE:
            return None
        if code is not None or "message" in payload:
            warn_once(
                f"error-code:{code}",
                "Nationex returned an error object with code %s; keeping the "
                "last data. Open an issue: %s",
                code,
                NEW_ISSUE_URL,
            )
            raise NationexApiError(f"error object (code {code})")
        raise NationexApiError("unexpected body (no shipment)")
