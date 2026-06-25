"""Synchronous HTTP client for the Boxmagic Members private web API."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

import httpx

from .crypto import (
    ClientLlavero,
    FileLlaveroStore,
    JsonValue,
    LlaveroStore,
    default_llavero_path,
)
from .models import InstanceKey, ReservationRequest, coerce_ymd

JsonObject = dict[str, Any]
DEFAULT_API_BASE_URL = "https://api-ce.boxmagic.app"
DEFAULT_APP_VERSION = "5.77.4"


@runtime_checkable
class BoxmagicClientProtocol(Protocol):
    """Structural interface for the Boxmagic Members API client.

    Defines every public endpoint method so that test doubles and alternative
    implementations can be type-checked without subclassing ``BoxmagicClient``.
    """

    def get_app_info(self) -> JsonObject:
        """Return public app metadata from ``/boxmagic/app/info``."""
        ...

    def refresh_account(self) -> JsonObject:
        """Refresh the current account and return the updated payload."""
        ...

    def get_profile(self, gym_id: str | None = None) -> JsonObject:
        """Return the authenticated user's profile in a gym."""
        ...

    def get_instances_by_ids(
        self,
        instances: Sequence[InstanceKey | Mapping[str, Any] | str],
        *,
        gym_id: str | None = None,
    ) -> JsonObject:
        """Fetch class instances by Boxmagic instance IDs."""
        ...

    def book_reservation(
        self,
        *,
        gym_id: str | None = None,
        instance: InstanceKey | Mapping[str, Any] | str | None = None,
        fecha_ymd: str | date | None = None,
        clase_id: str | None = None,
        horario_id: str | None = None,
        membresia_id: str | None = None,
        pago_id: str | None = None,
        lugar_id: str | None = None,
        acepta_lista_de_espera: bool = False,
        acepta_cualquier_lugar: bool = False,
        fecha_limite_espera: datetime | None = None,
    ) -> JsonObject:
        """Book a class instance with a membership, payment, or waitlist preference."""
        ...

    def book_with_priority(
        self,
        *,
        solicitud_id: str,
        gym_id: str | None = None,
        instance: InstanceKey | Mapping[str, Any] | str | None = None,
        fecha_ymd: str | date | None = None,
        clase_id: str | None = None,
        horario_id: str | None = None,
        lugar_id: str | None = None,
    ) -> JsonObject:
        """Book from a waitlist priority request."""
        ...

    def leave_waitlist(
        self,
        *,
        solicitud_id: str,
        gym_id: str | None = None,
        instance: InstanceKey | Mapping[str, Any] | str | None = None,
        fecha_ymd: str | date | None = None,
        clase_id: str | None = None,
        horario_id: str | None = None,
    ) -> JsonObject:
        """Leave an instance waitlist by ``solicitudID``."""
        ...

    def cancel_reservation(
        self,
        *,
        reserva_id: str,
        instance_id: str,
        gym_id: str | None = None,
        soft_delete: bool = True,
    ) -> JsonObject:
        """Cancel a reservation by reservation ID and compact instance ID."""
        ...

    def request(
        self,
        method: str,
        path: str,
        *,
        json: JsonObject | None = None,
        auth: bool = True,
        gym_id: str | None = None,
        raise_api_errors: bool = True,
    ) -> JsonObject:
        """Send a raw signed request and return the decoded JSON object."""
        ...


class BoxmagicAPIError(RuntimeError):
    """Raised when Boxmagic returns an HTTP error or `{ok: false}` response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        payload: JsonObject | None = None,
    ) -> None:
        """Create an API error with structured response context."""

        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.payload = payload or {}


@dataclass(frozen=True, slots=True)
class AppHeaders:
    """Header values copied from the Members web and mobile clients."""

    app_id: str = "members"
    environment: str = "produccion"
    device: str = "web"
    version: str = DEFAULT_APP_VERSION
    language: str = "es"
    origin: str | None = "https://members.boxmagic.app"
    referer: str | None = "https://members.boxmagic.app/"
    mdt_gim: str | None = None
    mdt_usr: str | None = None
    mdt_peg: str | None = None


class BoxmagicClient:
    """Client for the same HTTP API used by `members.boxmagic.app`."""

    def __init__(
        self,
        token: str,
        *,
        gym_id: str | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
        headers: AppHeaders | None = None,
        llavero_store: LlaveroStore | None = None,
        sign_requests: bool = True,
        clock_offset_seconds: int = 0,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a client with a Bearer token and optional default gym ID."""

        if not token:
            raise ValueError("A Boxmagic Bearer token is required.")
        root_url = api_base_url.rstrip("/")
        if root_url.endswith("/boxmagic"):
            root_url = root_url[: -len("/boxmagic")]
        self.token = token
        self.gym_id = gym_id
        self.headers = headers or AppHeaders()
        self.sign_requests = sign_requests
        self.clock_offset_seconds = clock_offset_seconds
        self._llavero_store = llavero_store or FileLlaveroStore(default_llavero_path())
        self._llavero: ClientLlavero | None = None
        self._client = httpx.Client(base_url=root_url, timeout=timeout, transport=transport)

    @classmethod
    def from_env(cls) -> BoxmagicClient:
        """Build a client from `BOXMAGIC_TOKEN` and optional environment settings."""

        token = os.environ.get("BOXMAGIC_TOKEN")
        if not token:
            raise ValueError("Set BOXMAGIC_TOKEN before calling BoxmagicClient.from_env().")
        return cls(
            token=token,
            gym_id=os.environ.get("BOXMAGIC_GYM_ID"),
            api_base_url=os.environ.get("BOXMAGIC_API_BASE_URL", DEFAULT_API_BASE_URL),
            clock_offset_seconds=_env_int("BOXMAGIC_CLOCK_OFFSET_SECONDS", default=0),
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""

        self._client.close()

    def __enter__(self) -> BoxmagicClient:
        """Return this client for use as a context manager."""

        return self

    def __exit__(self, *_exc: object) -> None:
        """Close network resources when leaving a context manager block."""

        self.close()

    def get_app_info(self) -> JsonObject:
        """Return public app metadata from `/boxmagic/app/info`."""

        return self.request("GET", "/boxmagic/app/info", auth=False)

    def refresh_account(self) -> JsonObject:
        """Refresh the current account and update the token when the API returns one."""

        data = self.request("GET", "/boxmagic/cuentas/refrescar")
        new_token = data.get("token")
        if isinstance(new_token, str) and new_token:
            self.token = new_token
        return data

    def get_profile(self, gym_id: str | None = None) -> JsonObject:
        """Return the authenticated user's profile in a gym."""

        resolved_gym_id = self._resolve_gym_id(gym_id)
        return self.request(
            "GET",
            f"/boxmagic/gimnasio/{_path(resolved_gym_id)}/perfilEnGimnasio",
            gym_id=resolved_gym_id,
        )

    def get_instances_by_ids(
        self,
        instances: Sequence[InstanceKey | Mapping[str, Any] | str],
        *,
        gym_id: str | None = None,
    ) -> JsonObject:
        """Fetch class instances by Boxmagic instance IDs or their component fields."""

        resolved_gym_id = self._resolve_gym_id(gym_id)
        payload = {
            "instancias": [InstanceKey.coerce(instance).to_api_payload() for instance in instances]
        }
        return self.request(
            "POST",
            f"/boxmagic/gimnasio/{_path(resolved_gym_id)}/instancias/porIDs",
            json=payload,
            gym_id=resolved_gym_id,
        )

    def book_reservation(
        self,
        *,
        gym_id: str | None = None,
        instance: InstanceKey | Mapping[str, Any] | str | None = None,
        fecha_ymd: str | date | None = None,
        clase_id: str | None = None,
        horario_id: str | None = None,
        membresia_id: str | None = None,
        pago_id: str | None = None,
        lugar_id: str | None = None,
        acepta_lista_de_espera: bool = False,
        acepta_cualquier_lugar: bool = False,
        fecha_limite_espera: datetime | None = None,
    ) -> JsonObject:
        """Book a class instance with a membership, payment, or waitlist preference."""

        resolved_gym_id = self._resolve_gym_id(gym_id)
        reservation = ReservationRequest(
            instance=_coerce_instance(instance, fecha_ymd, clase_id, horario_id),
            membresia_id=membresia_id,
            pago_id=pago_id,
            lugar_id=lugar_id,
            acepta_lista_de_espera=acepta_lista_de_espera,
            acepta_cualquier_lugar=acepta_cualquier_lugar,
            fecha_limite_espera=fecha_limite_espera,
        )
        return self.request(
            "POST",
            f"/boxmagic/gimnasio/{_path(resolved_gym_id)}/reservas/agendar",
            json=reservation.to_api_payload(),
            gym_id=resolved_gym_id,
        )

    def book_with_priority(
        self,
        *,
        solicitud_id: str,
        gym_id: str | None = None,
        instance: InstanceKey | Mapping[str, Any] | str | None = None,
        fecha_ymd: str | date | None = None,
        clase_id: str | None = None,
        horario_id: str | None = None,
        lugar_id: str | None = None,
    ) -> JsonObject:
        """Book from a waitlist priority request using `/reservas/agendarConPrioridad`."""

        resolved_gym_id = self._resolve_gym_id(gym_id)
        instance_key = _coerce_instance(instance, fecha_ymd, clase_id, horario_id)
        payload = {**instance_key.to_api_payload(), "solicitudID": solicitud_id}
        if lugar_id is not None:
            payload["lugarID"] = lugar_id
        return self.request(
            "POST",
            f"/boxmagic/gimnasio/{_path(resolved_gym_id)}/reservas/agendarConPrioridad",
            json=payload,
            gym_id=resolved_gym_id,
        )

    def leave_waitlist(
        self,
        *,
        solicitud_id: str,
        gym_id: str | None = None,
        instance: InstanceKey | Mapping[str, Any] | str | None = None,
        fecha_ymd: str | date | None = None,
        clase_id: str | None = None,
        horario_id: str | None = None,
    ) -> JsonObject:
        """Leave an instance waitlist by `solicitudID`."""

        resolved_gym_id = self._resolve_gym_id(gym_id)
        instance_key = _coerce_instance(instance, fecha_ymd, clase_id, horario_id)
        return self.request(
            "POST",
            f"/boxmagic/gimnasio/{_path(resolved_gym_id)}/reservas/abandonarListaDeEspera",
            json={**instance_key.to_api_payload(), "solicitudID": solicitud_id},
            gym_id=resolved_gym_id,
        )

    def cancel_reservation(
        self,
        *,
        reserva_id: str,
        instance_id: str,
        gym_id: str | None = None,
        soft_delete: bool = True,
    ) -> JsonObject:
        """Cancel a reservation by reservation ID and compact instance ID."""

        resolved_gym_id = self._resolve_gym_id(gym_id)
        return self.request(
            "POST",
            (
                f"/boxmagic/gimnasio/{_path(resolved_gym_id)}"
                f"/instancia/{_path(instance_id)}/reservas/cancelarPorID"
            ),
            json={"reservaID": reserva_id, "softDelete": soft_delete},
            gym_id=resolved_gym_id,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json: JsonObject | None = None,
        auth: bool = True,
        gym_id: str | None = None,
        raise_api_errors: bool = True,
    ) -> JsonObject:
        """Send a raw signed request and return the decoded JSON object."""

        body_for_signature: JsonValue = json if json is not None else {}
        request_headers = self._base_headers(gym_id=gym_id)
        if auth:
            request_headers["Authorization"] = f"Bearer {self.token}"
        if self.sign_requests:
            request_headers["signatura"] = self._sign_body(body_for_signature)
        response = self._client.request(method, path, json=json, headers=request_headers)
        data = _decode_json_object(response)
        if response.is_error:
            raise BoxmagicAPIError(
                f"Boxmagic HTTP {response.status_code}",
                status_code=response.status_code,
                error_code=_extract_error_code(data),
                payload=data,
            )
        if raise_api_errors and data.get("ok") is False:
            error_code = _extract_error_code(data)
            raise BoxmagicAPIError(
                f"Boxmagic API error: {error_code or 'unknown'}",
                status_code=response.status_code,
                error_code=error_code,
                payload=data,
            )
        return data

    def _base_headers(self, *, gym_id: str | None = None) -> dict[str, str]:
        """Return common headers expected by the Members API."""

        headers = {
            "Accept": "application/json",
            "idioma": self.headers.language,
            "gots-app": self.headers.app_id,
            "gots-ambiente": self.headers.environment,
            "gots-dispositivo": self.headers.device,
            "gots-version": self.headers.version,
        }
        if self.headers.origin:
            headers["Origin"] = self.headers.origin
        if self.headers.referer:
            headers["Referer"] = self.headers.referer
        if gym_id:
            headers["gots-gimnasio"] = gym_id
        if self.headers.mdt_gim:
            headers["mdt-gim"] = self.headers.mdt_gim
        if self.headers.mdt_usr:
            headers["mdt-usr"] = self.headers.mdt_usr
        if self.headers.mdt_peg:
            headers["mdt-peg"] = self.headers.mdt_peg
        return headers

    def _sign_body(self, body: JsonValue, *, clock_offset_seconds: int | None = None) -> str:
        """Sign a request body using the configured emulated client clock."""

        offset = self.clock_offset_seconds if clock_offset_seconds is None else clock_offset_seconds
        return self._get_llavero().sign_body_hash(body, iat_offset_seconds=offset)

    def _get_llavero(self) -> ClientLlavero:
        """Return a registered llavero, registering local keys when needed."""

        if self._llavero is not None:
            return self._llavero
        llavero = self._llavero_store.load()
        if llavero is None or llavero.registro_id == "nuevo":
            llavero = self._register_llavero(llavero or ClientLlavero.generate())
        self._llavero = llavero
        return llavero

    def _register_llavero(self, llavero: ClientLlavero) -> ClientLlavero:
        """Register and validate local signing keys with the Boxmagic API."""

        registration_body = llavero.public_registration_payload()
        registration_headers = self._base_headers()
        registration_headers["signatura"] = llavero.sign_body_hash(registration_body)
        registration_response = self._client.post(
            "/llaveros/registrarLlavero",
            json=registration_body,
            headers=registration_headers,
        )
        registration_data = _decode_json_object(registration_response)
        if registration_response.is_error or not registration_data.get("ok"):
            raise BoxmagicAPIError(
                "Unable to register Boxmagic llavero.",
                status_code=registration_response.status_code,
                error_code=_extract_error_code(registration_data),
                payload=registration_data,
            )

        llavero.registro_id = str(registration_data["registroID"])
        llavero.server_signing_public_pem = str(registration_data["firma"])
        llavero.server_encryption_public_pem = str(registration_data["encriptacion"])

        validation_body = {"desafioFirmado": registration_data["desafioAFirmar"]}
        validation_headers = self._base_headers()
        validation_headers["signatura"] = llavero.sign_body_hash(validation_body)
        validation_response = self._client.post(
            "/llaveros/validarLlavero",
            json=validation_body,
            headers=validation_headers,
        )
        validation_data = _decode_json_object(validation_response)
        if validation_response.is_error or not validation_data.get("ok"):
            raise BoxmagicAPIError(
                "Unable to validate Boxmagic llavero.",
                status_code=validation_response.status_code,
                error_code=_extract_error_code(validation_data),
                payload=validation_data,
            )

        llavero.registro_id = str(validation_data.get("registroID") or llavero.registro_id)
        self._llavero_store.save(llavero)
        return llavero

    def _resolve_gym_id(self, gym_id: str | None) -> str:
        """Return an explicit gym ID or the client's configured default."""

        resolved = gym_id or self.gym_id
        if not resolved:
            raise ValueError("A gym ID is required. Pass gym_id=... or set BOXMAGIC_GYM_ID.")
        return resolved


def _path(value: str) -> str:
    """Percent-encode path segments while preserving no reserved characters."""

    return quote(value, safe="")


def _decode_json_object(response: httpx.Response) -> JsonObject:
    """Decode an HTTP response as a JSON object or raise a structured API error."""

    try:
        data = response.json()
    except ValueError as exc:
        raise BoxmagicAPIError(
            "Boxmagic returned a non-JSON response.",
            status_code=response.status_code,
            payload={},
        ) from exc
    if not isinstance(data, dict):
        raise BoxmagicAPIError(
            "Boxmagic returned a JSON value that is not an object.",
            status_code=response.status_code,
            payload={},
        )
    return data


def _extract_error_code(data: JsonObject) -> str | None:
    """Extract the Boxmagic error code when a response includes one."""

    error = data.get("error")
    return error if isinstance(error, str) else None


def _coerce_instance(
    instance: InstanceKey | Mapping[str, Any] | str | None,
    fecha_ymd: str | date | None,
    clase_id: str | None,
    horario_id: str | None,
) -> InstanceKey:
    """Normalize the supported ways to identify a Boxmagic instance."""

    if instance is not None:
        return InstanceKey.coerce(instance)
    if fecha_ymd is None or clase_id is None or horario_id is None:
        raise ValueError("Provide instance=... or fecha_ymd=..., clase_id=..., horario_id=....")
    return InstanceKey(coerce_ymd(fecha_ymd), clase_id, horario_id)


def _env_int(name: str, *, default: int) -> int:
    """Read an integer environment variable with a clear failure for bad values."""

    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer number of seconds.") from exc


def decode_token_subject(token: str) -> str:
    """Extract the ``sub`` claim from a Boxmagic JWT without verifying the signature.

    The token payload is the second base64url-encoded segment. This is safe for
    local configuration since the API server validates the token independently.
    """

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Token is not a valid JWT (expected 3 dot-separated segments).")
    payload_b64 = parts[1]
    # Base64url may omit padding; restore it.
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to decode JWT payload.") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ValueError("JWT payload does not contain a 'sub' claim.")
    return subject
