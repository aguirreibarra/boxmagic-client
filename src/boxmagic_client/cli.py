"""Command line interface for the unofficial Boxmagic client."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .client import BoxmagicClient


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `boxmagic` command line interface."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    with BoxmagicClient.from_env() as client:
        if args.command == "app-info":
            _print_json(client.get_app_info())
        elif args.command == "profile":
            _print_json(client.get_profile(gym_id=args.gym_id))
        elif args.command == "instances":
            _print_json(client.get_instances_by_ids(args.instance_id, gym_id=args.gym_id))
        elif args.command == "book":
            if not args.confirm:
                _print_json(
                    {"dryRun": True, "message": "Pass --confirm to create the reservation."}
                )
                return 0
            _print_json(
                client.book_reservation(
                    gym_id=args.gym_id,
                    instance=args.instance_id,
                    membresia_id=args.membresia_id,
                    pago_id=args.pago_id,
                    lugar_id=args.lugar_id,
                    acepta_lista_de_espera=args.accept_waitlist,
                    acepta_cualquier_lugar=args.accept_any_place,
                )
            )
        elif args.command == "cancel":
            if not args.confirm:
                _print_json(
                    {"dryRun": True, "message": "Pass --confirm to cancel the reservation."}
                )
                return 0
            _print_json(
                client.cancel_reservation(
                    gym_id=args.gym_id,
                    instance_id=args.instance_id,
                    reserva_id=args.reservation_id,
                    soft_delete=not args.hard_delete,
                )
            )
        else:
            parser.error("No command supplied.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for all supported CLI commands."""

    parser = argparse.ArgumentParser(prog="boxmagic")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("app-info", help="Fetch public app metadata.")

    profile = subparsers.add_parser("profile", help="Fetch your profile for a gym.")
    profile.add_argument("--gym-id", help="Gym ID; defaults to BOXMAGIC_GYM_ID.")

    instances = subparsers.add_parser("instances", help="Fetch one or more instance IDs.")
    instances.add_argument("instance_id", nargs="+", help="IDs like iYYYY-MM-DD>claseID>horarioID.")
    instances.add_argument("--gym-id", help="Gym ID; defaults to BOXMAGIC_GYM_ID.")

    book = subparsers.add_parser("book", help="Book an instance ID.")
    book.add_argument("instance_id", help="ID like iYYYY-MM-DD>claseID>horarioID.")
    book.add_argument("--gym-id", help="Gym ID; defaults to BOXMAGIC_GYM_ID.")
    book.add_argument("--membresia-id", help="Membership ID to spend for the reservation.")
    book.add_argument("--pago-id", help="Payment ID to spend for the reservation.")
    book.add_argument("--lugar-id", help="Place or seat ID when the class requires one.")
    book.add_argument("--accept-waitlist", action="store_true", help="Join the waitlist if full.")
    book.add_argument(
        "--accept-any-place",
        action="store_true",
        help="Accept any place if waitlisted.",
    )
    book.add_argument("--confirm", action="store_true", help="Actually create the reservation.")

    cancel = subparsers.add_parser("cancel", help="Cancel a reservation.")
    cancel.add_argument("instance_id", help="ID like iYYYY-MM-DD>claseID>horarioID.")
    cancel.add_argument("reservation_id", help="Reservation ID to cancel.")
    cancel.add_argument("--gym-id", help="Gym ID; defaults to BOXMAGIC_GYM_ID.")
    cancel.add_argument("--hard-delete", action="store_true", help="Send softDelete=false.")
    cancel.add_argument("--confirm", action="store_true", help="Actually cancel the reservation.")

    return parser


def _print_json(data: object) -> None:
    """Print a JSON value in a stable, human-readable format."""

    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
