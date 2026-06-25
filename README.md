# boxmagic-client

Unofficial Python client for the private HTTP API used by [members.boxmagic.app](https://members.boxmagic.app).

This project mirrors the current Members web client behavior:

- Bearer token authentication.
- App headers such as `gots-app`, `gots-dispositivo`, and `gots-version`.
- The Boxmagic `llavero` registration and per-request `signatura` header.
- Booking payloads for `/reservas/agendar`.

The API is private and can change without notice. Use your own account token and avoid committing tokens or generated llavero files.

## Install

```bash
pip install boxmagic-client
```

Or from source:

```bash
git clone https://github.com/aguirreibarra/boxmagic-client.git
cd boxmagic-client
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Environment

```bash
export BOXMAGIC_TOKEN="your bearer token"
export BOXMAGIC_GYM_ID="YOUR_GYM_ID"
```

By default the client stores its local signing keys at `~/.boxmagic-client/llavero.json` with file mode `0600`. Override that with `BOXMAGIC_LLAVERO_PATH` if needed.

Set `BOXMAGIC_CLOCK_OFFSET_SECONDS` to emulate a shifted device clock in the per-request `signatura` timestamp.

## Python Usage

```python
from boxmagic_client import AppHeaders, BoxmagicClient

with BoxmagicClient.from_env() as client:
    profile = client.get_profile()
    instances = client.get_instances_by_ids([
        "i2026-04-22>CLASS_ID>HORARIO_ID",
    ])
    booking = client.book_reservation(
        instance="i2026-04-22>CLASS_ID>HORARIO_ID",
        membresia_id="MEMBERSHIP_ID",
        acepta_lista_de_espera=True,
    )
```

## CLI

```bash
boxmagic profile
boxmagic instances 'i2026-04-22>CLASS_ID>HORARIO_ID'
boxmagic book 'i2026-04-22>CLASS_ID>HORARIO_ID' --membresia-id MEMBERSHIP_ID --confirm
```

Booking and cancellation commands are dry-run by default. Pass `--confirm` to perform the mutation.

## Development

```bash
make validate
```

## License

MIT
