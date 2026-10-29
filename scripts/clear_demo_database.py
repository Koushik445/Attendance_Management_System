"""
CLI wrapper around app.services.admin_service.clear_demo(). Kept thin so the
actual logic lives in one place, shared with POST /api/admin/clear-demo.

Run:
    python scripts/clear_demo_database.py           # asks for confirmation
    python scripts/clear_demo_database.py --yes     # no prompt
"""
import argparse

import _bootstrap  # noqa: F401

from app.services.admin_service import clear_demo


def main(confirmed: bool):
    if not confirmed:
        answer = input("This will DELETE all persons/vehicles/id_cards/embeddings/events. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Aborted.")
            return

    result = clear_demo()
    print("Deleted rows:")
    for table, n in result["deleted"].items():
        print(f"  {table}: {n}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()
    main(confirmed=args.yes)
