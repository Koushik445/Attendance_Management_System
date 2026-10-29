"""
CLI wrapper around app.services.admin_service.seed_demo(). Kept thin so the
actual logic lives in one place, shared with POST /api/admin/seed-demo.

Run:
    python scripts/seed_demo_database.py
    python scripts/seed_demo_database.py --dry-run
"""
import argparse

import _bootstrap  # noqa: F401  (sets up sys.path + loads .env)

from app.services.admin_service import seed_demo


def main(dry_run: bool = False):
    result = seed_demo(dry_run=dry_run)
    for line in result["log"]:
        print(line)

    if not result["ok"]:
        return

    c = result["counts"]
    print("\n--- Summary ---")
    print(f"Persons:  created={c['persons_created']} skipped={c['persons_skipped']}")
    print(f"Vehicles: created={c['vehicles_created']} skipped={c['vehicles_skipped']}")
    print(f"ID cards: created={c['id_cards_created']} skipped={c['id_cards_skipped']}")
    if dry_run:
        print("(dry run - nothing was written to the database)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
