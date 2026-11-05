#!/usr/bin/env bash
# Local payments: forwards Stripe's webhooks to your backend while you test.
#   scripts/dev_stripe.sh            (leave it running next to uvicorn)
# The first run saves the webhook secret to .env; restart the backend once after that.
set -euo pipefail
cd "$(dirname "$0")/.."

STRIPE="$(command -v stripe || true)"
[ -z "$STRIPE" ] && [ -x "$HOME/.local/bin/stripe" ] && STRIPE="$HOME/.local/bin/stripe"
[ -z "$STRIPE" ] && { echo "Stripe CLI not found. Install it from https://github.com/stripe/stripe-cli/releases"; exit 1; }

KEY="$(grep -E '^STRIPE_SECRET_KEY=' .env | cut -d= -f2-)"
[ -z "$KEY" ] && { echo "STRIPE_SECRET_KEY is missing from .env"; exit 1; }
PORT="${PORT:-8765}"

# --api-key means no browser login is needed.
SECRET="$("$STRIPE" listen --api-key "$KEY" --print-secret)"
CURRENT="$(grep -E '^STRIPE_WEBHOOK_SECRET=' .env | cut -d= -f2- || true)"
if [ "$SECRET" != "$CURRENT" ]; then
  if grep -q '^STRIPE_WEBHOOK_SECRET=' .env; then
    sed -i.bak "s|^STRIPE_WEBHOOK_SECRET=.*|STRIPE_WEBHOOK_SECRET=$SECRET|" .env && rm -f .env.bak
  else
    printf '\nSTRIPE_WEBHOOK_SECRET=%s\n' "$SECRET" >> .env
  fi
  echo "Saved the webhook secret to .env. Restart the backend so it picks it up."
fi

echo "Forwarding Stripe events to http://localhost:$PORT/billing/webhook"
exec "$STRIPE" listen --api-key "$KEY" --forward-to "localhost:$PORT/billing/webhook" \
  --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted
