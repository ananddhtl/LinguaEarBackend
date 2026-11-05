"""Checks a Brevo API key from your own computer, step by step.

    .venv/bin/python scripts/test_brevo.py
    .venv/bin/python scripts/test_brevo.py --from you@yourdomain.com --to you@gmail.com

The key is read from the BREVO_API_KEY environment variable, or typed in (hidden). It is never printed.
"""
import argparse
import getpass
import os
import sys

import httpx

API = "https://api.brevo.com/v3"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="sender", help="verified sender address to send the test from")
    parser.add_argument("--to", help="where to send the test email")
    args = parser.parse_args()

    key = os.environ.get("BREVO_API_KEY") or getpass.getpass("Brevo API key (xkeysib-...): ").strip()
    headers = {"api-key": key, "accept": "application/json"}

    print("1) Is the key accepted?")
    r = httpx.get(f"{API}/account", headers=headers, timeout=20)
    if r.status_code != 200:
        print(f"   NO ({r.status_code}): {r.text[:200]}")
        print("   Use the API key (starts with xkeysib-), not the SMTP key (xsmtpsib-).")
        return 1
    account = r.json()
    plan = ", ".join(f"{p.get('type')}: {p.get('credits')} credits" for p in account.get("plan", [])) or "n/a"
    print(f"   yes. account: {account.get('email')} | plan: {plan}")

    print("2) Verified senders (mail can only be sent from an ACTIVE one):")
    r = httpx.get(f"{API}/senders", headers=headers, timeout=20)
    senders = r.json().get("senders", []) if r.status_code == 200 else []
    for s in senders:
        print(f"   {'active  ' if s.get('active') else 'INACTIVE'} {s.get('email')}")
    if not senders:
        print(f"   none found ({r.status_code}). Add and verify one in Brevo: Senders, Domains & Dedicated IPs.")

    if args.sender and args.to:
        active = {s["email"].lower() for s in senders if s.get("active")}
        if args.sender.lower() not in active:
            print(f"   note: {args.sender} is not an active sender, so Brevo will probably refuse it.")
        print(f"3) Sending a test email {args.sender} -> {args.to}")
        r = httpx.post(
            f"{API}/smtp/email",
            headers=headers,
            json={
                "sender": {"email": args.sender, "name": "LinguaEar test"},
                "to": [{"email": args.to}],
                "subject": "LinguaEar Brevo test",
                "textContent": "If you can read this, Brevo accepted the message.",
            },
            timeout=20,
        )
        print(f"   Brevo answered {r.status_code}: {r.text[:300]}")
        if r.status_code >= 300:
            return 1
        print("   Accepted. Now check the inbox AND the spam folder.")
        print("   Brevo shows what happened to it under Transactional > Logs.")
    else:
        print("3) Skipped sending. To send a test, add:  --from <verified sender> --to <your inbox>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
