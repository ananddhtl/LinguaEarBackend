"""One-time Stripe setup: creates the Standard and Pro plans, the customer portal, and (optionally) a webhook.

    .venv/bin/python scripts/stripe_setup.py                      # plans + portal; price ids go into .env
    .venv/bin/python scripts/stripe_setup.py --webhook-url https://your-api.example.com/billing/webhook

Safe to run again: plans are found by their lookup key instead of being created twice. Only test keys are
accepted unless you pass --live.
"""
import argparse
import re
import sys
from pathlib import Path

import stripe

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
EVENTS = [
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
]
PLANS = {
    "standard": {"name": "LinguaEar Standard", "amount": 499, "lookup": "linguaear_standard_monthly", "env": "STRIPE_PRICE_STANDARD"},
    "pro": {"name": "LinguaEar Pro", "amount": 999, "lookup": "linguaear_pro_monthly", "env": "STRIPE_PRICE_PRO"},
}


def set_env(name: str, value: str) -> None:
    """Sets NAME=value in .env, replacing an existing line."""
    text = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    line = f"{name}={value}"
    if re.search(rf"^{name}=.*$", text, flags=re.M):
        text = re.sub(rf"^{name}=.*$", line, text, flags=re.M)
    else:
        text += ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    ENV_FILE.write_text(text)


def ensure_price(tier: str) -> str:
    plan = PLANS[tier]
    found = stripe.Price.list(lookup_keys=[plan["lookup"]], active=True, limit=1)["data"]
    if found:
        return found[0]["id"]
    product = stripe.Product.create(name=plan["name"], metadata={"tier": tier})
    price = stripe.Price.create(
        product=product["id"],
        unit_amount=plan["amount"],
        currency="eur",
        recurring={"interval": "month"},
        lookup_key=plan["lookup"],
        metadata={"tier": tier},
    )
    return price["id"]


def ensure_portal() -> None:
    """Without a portal configuration, "Manage subscription" fails. This adds a plain one if none exists."""
    if stripe.billing_portal.Configuration.list(limit=1, is_default=True)["data"]:
        return
    stripe.billing_portal.Configuration.create(
        business_profile={"headline": "Manage your LinguaEar subscription"},
        features={
            "payment_method_update": {"enabled": True},
            "invoice_history": {"enabled": True},
            "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
        },
    )
    print("Created the customer portal configuration.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook-url", help="Public https://.../billing/webhook address of a deployed backend")
    parser.add_argument("--live", action="store_true", help="Allow a live-mode key")
    args = parser.parse_args()

    key = settings.stripe_secret_key
    if not key:
        sys.exit("STRIPE_SECRET_KEY is not set in .env")
    if not key.startswith("sk_test_") and not args.live:
        sys.exit("This is not a test key. Use a test-mode key, or pass --live if you really mean it.")
    stripe.api_key = key

    print(f"Account: {stripe.Account.retrieve()['id']} ({'test' if key.startswith('sk_test_') else 'LIVE'} mode)")
    for tier, plan in PLANS.items():
        price_id = ensure_price(tier)
        set_env(plan["env"], price_id)
        print(f"{tier:9} {plan['amount'] / 100:.2f} EUR/month  {plan['env']}={price_id}  (saved to .env)")
    ensure_portal()

    if args.webhook_url:
        existing = [e for e in stripe.WebhookEndpoint.list(limit=100)["data"] if e["url"] == args.webhook_url]
        if existing:
            print(
                f"\nA webhook for {args.webhook_url} already exists ({existing[0]['id']}). Stripe shows its secret only "
                "once, when it is created. Delete it in the dashboard and run this again to get a new secret."
            )
        else:
            endpoint = stripe.WebhookEndpoint.create(url=args.webhook_url, enabled_events=EVENTS)
            print(f"\nCreated webhook {endpoint['id']} for {args.webhook_url}")
            print("Put this on the server (e.g. Render environment). It is shown only now:")
            print(f"  STRIPE_WEBHOOK_SECRET={endpoint['secret']}")
    print("\nFor a deployed backend, also set STRIPE_SECRET_KEY, STRIPE_PRICE_STANDARD, STRIPE_PRICE_PRO and PUBLIC_BASE_URL there.")


if __name__ == "__main__":
    main()
