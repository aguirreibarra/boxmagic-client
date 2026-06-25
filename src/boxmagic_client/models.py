"""Typed request models for the Boxmagic Members API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class InstanceKey:
    """Identifier fields used by Boxmagic to address a class or session instance."""

    fecha_ymd: str
    clase_id: str
    horario_id: str

    @classmethod
    def from_instance_id(cls, instance_id: str) -> InstanceKey:
        """Parse an instance ID in the `iYYYY-MM-DD>claseID>horarioID` format."""

        if not instance_id.startswith("i"):
            raise ValueError("Boxmagic instance IDs must start with 'i'.")
        try:
            fecha_ymd, clase_id, horario_id = instance_id[1:].split(">", 2)
        except ValueError as exc:
            raise ValueError(
                "Boxmagic instance IDs must look like 'iYYYY-MM-DD>claseID>horarioID'."
            ) from exc
        return cls(fecha_ymd=fecha_ymd, clase_id=clase_id, horario_id=horario_id)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> InstanceKey:
        """Build an instance key from API-style or Python-style field names."""

        fecha_ymd = data.get("fechaYMD", data.get("fecha_ymd"))
        clase_id = data.get("claseID", data.get("clase_id"))
        horario_id = data.get("horarioID", data.get("horario_id"))
        if not all(isinstance(value, str) and value for value in (fecha_ymd, clase_id, horario_id)):
            raise ValueError("Instance mappings require fechaYMD, claseID, and horarioID.")
        return cls(fecha_ymd=fecha_ymd, clase_id=clase_id, horario_id=horario_id)

    @classmethod
    def coerce(cls, value: InstanceKey | Mapping[str, Any] | str) -> InstanceKey:
        """Convert an instance key, mapping, or raw instance ID into `InstanceKey`."""

        if isinstance(value, InstanceKey):
            return value
        if isinstance(value, str):
            return cls.from_instance_id(value)
        return cls.from_mapping(value)

    @property
    def instance_id(self) -> str:
        """Return Boxmagic's compact instance ID for this key."""

        return f"i{self.fecha_ymd}>{self.clase_id}>{self.horario_id}"

    def to_api_payload(self) -> dict[str, str]:
        """Return the API field names expected by Boxmagic instance endpoints."""

        return {
            "fechaYMD": self.fecha_ymd,
            "claseID": self.clase_id,
            "horarioID": self.horario_id,
        }


@dataclass(frozen=True, slots=True)
class ReservationRequest:
    """Payload for reserving a Boxmagic class instance."""

    instance: InstanceKey
    membresia_id: str | None = None
    pago_id: str | None = None
    lugar_id: str | None = None
    acepta_lista_de_espera: bool = False
    acepta_cualquier_lugar: bool = False
    fecha_limite_espera: datetime | None = None

    def to_api_payload(self) -> dict[str, str]:
        """Return the request body used by `/reservas/agendar`."""

        payload: dict[str, str] = {
            **self.instance.to_api_payload(),
            "aceptaListaDeEspera": "si" if self.acepta_lista_de_espera else "no",
            "aceptaCualquierLugar": "si" if self.acepta_cualquier_lugar else "no",
        }
        _set_optional(payload, "membresiaID", self.membresia_id)
        _set_optional(payload, "pagoID", self.pago_id)
        _set_optional(payload, "lugarID", self.lugar_id)
        if self.fecha_limite_espera is not None:
            payload["fechaLimiteEspera"] = _to_iso_string(self.fecha_limite_espera)
        return payload


def coerce_ymd(value: str | date) -> str:
    """Normalize a date or `YYYY-MM-DD` string into the API's `fechaYMD` value."""

    if isinstance(value, date):
        return value.isoformat()
    return value


def _set_optional(payload: dict[str, str], key: str, value: str | None) -> None:
    """Set a payload key only when the web client would have sent a JSON value."""

    if value is not None:
        payload[key] = value


def _to_iso_string(value: datetime) -> str:
    """Serialize datetimes the same way browser `Date.toISOString()` does."""

    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
