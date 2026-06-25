"""Request-signing helpers that mirror the Members web client's llavero flow."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


def base64url(data: bytes) -> str:
    """Encode bytes with URL-safe base64 and no padding, matching browser code."""

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical_json_hash(data: JsonValue) -> str:
    """Return the SHA-256 base64url hash used in Boxmagic `signatura` payloads."""

    canonical = json.dumps(
        data if data is not None else {},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64url(hashlib.sha256(canonical).digest())


def _json_bytes(data: dict[str, Any]) -> bytes:
    """Serialize JWT header and payload objects in the compact form expected by JWS."""

    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@dataclass(slots=True)
class ClientLlavero:
    """Local RSA key material registered with Boxmagic for request signatures."""

    llavero_id: str
    signing_private_pem: str
    signing_public_pem: str
    encryption_private_pem: str
    encryption_public_pem: str
    registro_id: str = "nuevo"
    server_signing_public_pem: str | None = None
    server_encryption_public_pem: str | None = None

    @classmethod
    def generate(cls) -> ClientLlavero:
        """Generate signing and encryption key pairs equivalent to the web client."""

        signing_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        encryption_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signing_private_pem = _private_pem(signing_private)
        encryption_private_pem = _private_pem(encryption_private)
        signing_public_pem = _public_pem(signing_private.public_key())
        encryption_public_pem = _public_pem(encryption_private.public_key())
        llavero_id = base64url(
            hashlib.sha256((signing_public_pem + encryption_public_pem).encode("utf-8")).digest()
        )
        return cls(
            llavero_id=llavero_id,
            signing_private_pem=signing_private_pem,
            signing_public_pem=signing_public_pem,
            encryption_private_pem=encryption_private_pem,
            encryption_public_pem=encryption_public_pem,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClientLlavero:
        """Restore llavero key material from a JSON-compatible mapping."""

        return cls(
            llavero_id=str(data["llavero_id"]),
            signing_private_pem=str(data["signing_private_pem"]),
            signing_public_pem=str(data["signing_public_pem"]),
            encryption_private_pem=str(data["encryption_private_pem"]),
            encryption_public_pem=str(data["encryption_public_pem"]),
            registro_id=str(data.get("registro_id") or "nuevo"),
            server_signing_public_pem=data.get("server_signing_public_pem"),
            server_encryption_public_pem=data.get("server_encryption_public_pem"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the llavero to a JSON-compatible mapping for persistence."""

        return asdict(self)

    def public_registration_payload(self) -> dict[str, str]:
        """Return the public keys sent to `/llaveros/registrarLlavero`."""

        return {
            "firma": self.signing_public_pem,
            "encriptacion": self.encryption_public_pem,
        }

    def sign_payload(self, payload: dict[str, Any], *, iat_offset_seconds: int = 0) -> str:
        """Create an RS256 compact JWS with the llavero ID as issuer."""

        private_key = serialization.load_pem_private_key(
            self.signing_private_pem.encode("ascii"),
            password=None,
        )
        jwt_payload = {
            **payload,
            "iat": int(time.time()) + iat_offset_seconds - 10,
            "iss": payload.get("iss") or self.llavero_id,
        }
        header = {"alg": "RS256"}
        signing_input = b".".join(
            [
                base64url(_json_bytes(header)).encode("ascii"),
                base64url(_json_bytes(jwt_payload)).encode("ascii"),
            ]
        )
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input.decode('ascii')}.{base64url(signature)}"

    def sign_body_hash(self, body: JsonValue, *, iat_offset_seconds: int = 0) -> str:
        """Sign the canonical body hash and current registration ID for an API request."""

        return self.sign_payload(
            {"hash": canonical_json_hash(body), "rid": self.registro_id},
            iat_offset_seconds=iat_offset_seconds,
        )


class LlaveroStore(Protocol):
    """Persistence boundary for Boxmagic llavero key material."""

    def load(self) -> ClientLlavero | None:
        """Return previously saved key material, or `None` when no llavero exists."""

    def save(self, llavero: ClientLlavero) -> None:
        """Persist key material after registration or rotation."""


class MemoryLlaveroStore:
    """In-memory llavero store for tests and short-lived scripts."""

    def __init__(self, llavero: ClientLlavero | None = None) -> None:
        """Initialize the store with optional pre-existing key material."""

        self._llavero = llavero

    def load(self) -> ClientLlavero | None:
        """Return the current in-memory llavero, if one has been saved."""

        return self._llavero

    def save(self, llavero: ClientLlavero) -> None:
        """Replace the in-memory llavero with the supplied key material."""

        self._llavero = llavero


class FileLlaveroStore:
    """JSON file store for llavero material, similar to browser local persistence."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        """Create a store backed by `path`; parent directories are created on save."""

        self.path = Path(path).expanduser()

    def load(self) -> ClientLlavero | None:
        """Load a llavero from disk when the configured file exists."""

        if not self.path.exists():
            return None
        return ClientLlavero.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, llavero: ClientLlavero) -> None:
        """Persist a llavero as mode 0600 JSON to avoid casual secret exposure."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(llavero.to_dict(), indent=2, sort_keys=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.write("\n")


def default_llavero_path() -> Path:
    """Return the default llavero cache path used by `BoxmagicClient.from_env`."""

    return Path(
        os.environ.get("BOXMAGIC_LLAVERO_PATH", "~/.boxmagic-client/llavero.json")
    ).expanduser()


def _private_pem(private_key: rsa.RSAPrivateKey) -> str:
    """Serialize an RSA private key in PKCS8 PEM format."""

    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _public_pem(public_key: rsa.RSAPublicKey) -> str:
    """Serialize an RSA public key in SubjectPublicKeyInfo PEM format."""

    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
