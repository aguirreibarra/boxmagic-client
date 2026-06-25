"""Tests for Boxmagic API request models."""

from __future__ import annotations

from datetime import UTC, datetime

from boxmagic_client import InstanceKey, ReservationRequest


def test_instance_key_round_trips_compact_id() -> None:
    """Instance IDs should parse into fields and serialize back unchanged."""

    instance = InstanceKey.from_instance_id("i2026-04-22>class-1>schedule-2")

    assert instance.fecha_ymd == "2026-04-22"
    assert instance.clase_id == "class-1"
    assert instance.horario_id == "schedule-2"
    assert instance.instance_id == "i2026-04-22>class-1>schedule-2"
    assert instance.to_api_payload() == {
        "fechaYMD": "2026-04-22",
        "claseID": "class-1",
        "horarioID": "schedule-2",
    }


def test_reservation_request_matches_web_payload_shape() -> None:
    """Reservation payloads should use the same field names and si/no flags as the web app."""

    request = ReservationRequest(
        instance=InstanceKey("2026-04-22", "class-1", "schedule-2"),
        membresia_id="membership-1",
        lugar_id="seat-1",
        acepta_lista_de_espera=True,
        acepta_cualquier_lugar=True,
        fecha_limite_espera=datetime(2026, 4, 22, 13, 30, tzinfo=UTC),
    )

    assert request.to_api_payload() == {
        "fechaYMD": "2026-04-22",
        "claseID": "class-1",
        "horarioID": "schedule-2",
        "membresiaID": "membership-1",
        "lugarID": "seat-1",
        "aceptaListaDeEspera": "si",
        "aceptaCualquierLugar": "si",
        "fechaLimiteEspera": "2026-04-22T13:30:00Z",
    }
