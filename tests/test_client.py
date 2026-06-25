"""Tests for the synchronous Boxmagic HTTP client."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from boxmagic_client import AppHeaders, BoxmagicAPIError, BoxmagicClient, MemoryLlaveroStore
from boxmagic_client.crypto import ClientLlavero, canonical_json_hash


def test_client_posts_instance_lookup_payload() -> None:
    """Instance lookup should POST the body shape used by the Members web client."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "instancias": {}, "participantes": {}})

    client = BoxmagicClient(
        "token",
        gym_id="gym-1",
        sign_requests=False,
        transport=httpx.MockTransport(handler),
    )

    response = client.get_instances_by_ids(["i2026-04-22>class-1>schedule-2"])

    assert response["ok"] is True
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/boxmagic/gimnasio/gym-1/instancias/porIDs"
    assert requests[0].headers["authorization"] == "Bearer token"
    assert requests[0].headers["gots-gimnasio"] == "gym-1"
    assert json.loads(requests[0].content) == {
        "instancias": [{"fechaYMD": "2026-04-22", "claseID": "class-1", "horarioID": "schedule-2"}]
    }


def test_client_posts_booking_payload() -> None:
    """Booking should call `/reservas/agendar` with membership and waitlist fields."""

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "solicitud": {"resultado": "agendada"}})

    client = BoxmagicClient(
        "token",
        gym_id="gym-1",
        sign_requests=False,
        transport=httpx.MockTransport(handler),
    )

    response = client.book_reservation(
        instance="i2026-04-22>class-1>schedule-2",
        membresia_id="membership-1",
        acepta_lista_de_espera=True,
    )

    request = captured["request"]
    assert response["ok"] is True
    assert request.url.path == "/boxmagic/gimnasio/gym-1/reservas/agendar"
    assert captured["body"] == {
        "fechaYMD": "2026-04-22",
        "claseID": "class-1",
        "horarioID": "schedule-2",
        "membresiaID": "membership-1",
        "aceptaListaDeEspera": "si",
        "aceptaCualquierLugar": "no",
    }


def test_client_can_send_mobile_metadata_headers() -> None:
    """Mobile metadata headers should be available without forcing web referers."""

    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"ok": True, "perfil": {}})

    client = BoxmagicClient(
        "token",
        gym_id="gym-1",
        sign_requests=False,
        headers=AppHeaders(
            device="ios",
            language="en, es",
            origin="capacitor://members.boxmagic.app",
            referer=None,
            mdt_gim="2026-04-21T02:50:00.884Z",
            mdt_usr="2026-04-21T02:49:49.246Z",
            mdt_peg="2026-04-21T02:50:02.182Z",
        ),
        transport=httpx.MockTransport(handler),
    )

    assert client.get_profile()["ok"] is True
    request = captured["request"]
    assert request.headers["gots-dispositivo"] == "ios"
    assert request.headers["origin"] == "capacitor://members.boxmagic.app"
    assert "referer" not in request.headers
    assert request.headers["mdt-gim"] == "2026-04-21T02:50:00.884Z"
    assert request.headers["mdt-usr"] == "2026-04-21T02:49:49.246Z"
    assert request.headers["mdt-peg"] == "2026-04-21T02:50:02.182Z"


def test_client_raises_boxmagic_api_errors() -> None:
    """`{ok: false}` responses should become structured exceptions by default."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "tokenExpirado"})

    client = BoxmagicClient(
        "token",
        gym_id="gym-1",
        sign_requests=False,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(BoxmagicAPIError) as exc_info:
        client.get_profile()

    assert exc_info.value.error_code == "tokenExpirado"
    assert exc_info.value.status_code == 200


def test_signed_requests_register_llavero_and_send_signatura() -> None:
    """Signed requests should perform llavero registration before the API call."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/llaveros/registrarLlavero":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "firma": "SERVER_SIGNING_PUBLIC",
                    "encriptacion": "SERVER_ENCRYPTION_PUBLIC",
                    "registroID": "registry-1",
                    "desafioAFirmar": "challenge",
                },
            )
        if request.url.path == "/llaveros/validarLlavero":
            return httpx.Response(
                200,
                json={"ok": True, "llaveroID": "server", "registroID": "registry-1"},
            )
        return httpx.Response(200, json={"ok": True, "name": "Members"})

    client = BoxmagicClient(
        "token",
        llavero_store=MemoryLlaveroStore(),
        transport=httpx.MockTransport(handler),
    )

    assert client.get_app_info()["ok"] is True
    assert [request.url.path for request in requests] == [
        "/llaveros/registrarLlavero",
        "/llaveros/validarLlavero",
        "/boxmagic/app/info",
    ]
    assert all("signatura" in request.headers for request in requests)
    api_payload = _decode_jwt_payload(requests[-1].headers["signatura"])
    assert api_payload["rid"] == "registry-1"
    assert api_payload["hash"] == canonical_json_hash({})


def test_signed_requests_can_emulate_shifted_client_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clock offsets should be reflected in the request `signatura` JWT `iat`."""

    llavero = ClientLlavero.generate()
    llavero.registro_id = "registry-1"
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["signatura"] = request.headers["signatura"]
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("boxmagic_client.crypto.time.time", lambda: 1_800_000_000)
    client = BoxmagicClient(
        "token",
        llavero_store=MemoryLlaveroStore(llavero),
        clock_offset_seconds=86_400,
        transport=httpx.MockTransport(handler),
    )

    assert client.get_app_info()["ok"] is True
    payload = _decode_jwt_payload(captured["signatura"])
    assert payload["iat"] == 1_800_000_000 + 86_400 - 10


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode an unsigned JWT payload for request-shape assertions."""

    payload_segment = token.split(".")[1]
    padded = payload_segment + ("=" * (-len(payload_segment) % 4))
    payload = base64.urlsafe_b64decode(padded.encode("ascii"))
    decoded = json.loads(payload)
    assert isinstance(decoded, dict)
    return decoded
