# =============================================================================
# Billing Reconciliation — comparación usage vs invoices vs payments
# =============================================================================
# Uso: python src/scripts/billing_reconcile.py [--days 30] [--org UUID]
# Report-only: nunca muta datos.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from src.platform.billing.reconciliation import reconcile


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile usage vs invoices vs payments"
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--org", type=UUID, default=None)
    args = parser.parse_args()

    report = asyncio.run(reconcile(args.org, days=args.days))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
