"""Tests for the Nationex API client."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.nationex.api import NationexApiClient, NationexApiError
from custom_components.nationex.const import MAX_RESPONSE_BYTES

from .payloads import UNKNOWN_BODY, delivered_sample

CODE = "900000001"
PARCEL_CODE = "90000000101"


def _session(status: int = 200, body: object = None, headers: dict | None = None):
    text = body if isinstance(body, (str, bytes)) else json.dumps(body)
    data = text.encode() if isinstance(text, str) else text

    async def chunks(size):
        for start in range(0, len(data), size):
            yield data[start : start + size]

    response = MagicMock()
    response.status = status
    response.headers = headers or {}
    response.content.iter_chunked = chunks
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


async def test_returns_shipment_and_sends_plain_get():
    session = _session(200, delivered_sample())
    shipment = await NationexApiClient(session).async_get_parcel(CODE)

    assert shipment["ShipmentId"] == 900000001
    assert session.get.call_args[0][0].endswith(f"/get-shipment/{CODE}")
    kwargs = session.get.call_args.kwargs
    assert kwargs["headers"] == {"Accept": "application/json"}
    assert kwargs["allow_redirects"] is False


async def test_parcel_number_matches_a_parcel_id():
    shipment = await NationexApiClient(
        _session(200, delivered_sample())
    ).async_get_parcel(PARCEL_CODE)
    assert shipment is not None


async def test_verbatim_not_found_object_is_none():
    assert (
        await NationexApiClient(_session(200, UNKNOWN_BODY)).async_get_parcel(CODE)
        is None
    )


async def test_other_error_object_is_inconclusive(caplog):
    client = NationexApiClient(_session(200, {"code": 500, "message": "backend down"}))
    with caplog.at_level(logging.WARNING), pytest.raises(NationexApiError):
        await client.async_get_parcel(CODE)
    assert "code 500" in caplog.text
    assert "unrecognised_status.yml" in caplog.text


async def test_message_only_object_is_inconclusive():
    with pytest.raises(NationexApiError):
        await NationexApiClient(_session(200, {"message": "hm"})).async_get_parcel(CODE)


async def test_unrecognised_object_is_schema_error():
    with pytest.raises(NationexApiError):
        await NationexApiClient(_session(200, {"foo": 1})).async_get_parcel(CODE)


async def test_shipment_for_another_number_is_inconclusive(caplog):
    client = NationexApiClient(_session(200, delivered_sample("900000009")))
    with caplog.at_level(logging.WARNING), pytest.raises(NationexApiError):
        await client.async_get_parcel(CODE)
    assert "does not carry the number" in caplog.text
    assert "900000009" not in caplog.text


async def test_shipment_without_parcel_list_is_inconclusive():
    body = delivered_sample("900000009")
    body["Parcels"] = None
    with pytest.raises(NationexApiError):
        await NationexApiClient(_session(200, body)).async_get_parcel(CODE)


async def test_challenge_page_is_transport_error(caplog):
    html = "<html><head><title>Just a moment...</title></head></html>"
    with caplog.at_level(logging.WARNING), pytest.raises(NationexApiError):
        await NationexApiClient(_session(200, html)).async_get_parcel(CODE)
    assert "bot-protection" in caplog.text


async def test_challenge_403_is_transport_error(caplog):
    html = "<script>window._cf_chl_opt = {}</script>"
    with caplog.at_level(logging.WARNING), pytest.raises(NationexApiError) as err:
        await NationexApiClient(_session(403, html)).async_get_parcel(CODE)
    assert err.value.status_code == 403
    assert "bot-protection" in caplog.text


async def test_plain_403_is_transport_error_without_warning(caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(NationexApiError):
        await NationexApiClient(_session(403, "denied")).async_get_parcel(CODE)
    assert "bot-protection" not in caplog.text


@pytest.mark.parametrize("status", [301, 302, 404, 410, 500, 503])
async def test_moved_or_down_is_transport_error(status):
    with pytest.raises(NationexApiError) as err:
        await NationexApiClient(_session(status, "")).async_get_parcel(CODE)
    assert err.value.status_code == status


async def test_rate_limit_carries_retry_after():
    client = NationexApiClient(_session(429, "", {"Retry-After": "30"}))
    with pytest.raises(NationexApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == 429
    assert err.value.retry_after == 30.0


@pytest.mark.parametrize("header", [None, "Wed, 21 Oct 2026 07:28:00 GMT"])
async def test_rate_limit_without_seconds(header):
    client = NationexApiClient(
        _session(429, "", {"Retry-After": header} if header else {})
    )
    with pytest.raises(NationexApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.retry_after is None


async def test_non_json_body_is_schema_error():
    with pytest.raises(NationexApiError, match="unparseable"):
        await NationexApiClient(_session(200, "<html>oops</html>")).async_get_parcel(
            CODE
        )


async def test_non_object_body_is_schema_error():
    with pytest.raises(NationexApiError, match="not a JSON object"):
        await NationexApiClient(_session(200, [1, 2])).async_get_parcel(CODE)


async def test_oversized_body_is_refused():
    body = b"x" * (MAX_RESPONSE_BYTES + 1)
    with pytest.raises(NationexApiError, match="too large"):
        await NationexApiClient(_session(200, body)).async_get_parcel(CODE)


async def test_network_error_propagates():
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    with pytest.raises(aiohttp.ClientError):
        await NationexApiClient(session).async_get_parcel(CODE)
