import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import billing, plans, stripe_service
from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import BillingStatus, CheckoutRequest, PlanInfo, PortalRequest, UrlResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _plan_infos() -> list[PlanInfo]:
    result = []
    for tier in plans.TIERS:
        limits = plans.limits_for(tier)
        result.append(
            PlanInfo(
                tier=tier,
                price_label=plans.label(tier),
                analyze_per_day=limits.analyze,
                game_per_day=limits.game,
                scan_per_day=limits.scan,
                transcribe_per_day=limits.transcribe,
                saved_phrases=limits.saved_phrases,
            )
        )
    return result


@router.get("/status", response_model=BillingStatus)
def billing_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Does the user have access (trial or plan), and what can they buy."""
    return {**billing.status_for(db, user), "enforced": settings.billing_enforced, "plans": _plan_infos()}


@router.post("/checkout", response_model=UrlResponse)
def checkout(body: CheckoutRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns a Stripe Checkout page URL for the chosen plan. The app opens it in the browser."""
    sub = billing.status_for(db, user)
    if sub["state"] == "subscribed":
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a subscription. Use Manage subscription to change it.")
    return UrlResponse(url=stripe_service.create_checkout_url(db, user, body.tier, body.return_url))


@router.post("/portal", response_model=UrlResponse)
def portal(
    body: PortalRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stripe's hosted page for changing plan, updating the card, cancelling and seeing invoices."""
    return UrlResponse(url=stripe_service.create_portal_url(db, user, body.return_url if body else None))


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe calls this when a subscription changes. The signature proves the call is really from Stripe."""
    payload = await request.body()
    event = stripe_service.verify_event(payload, request.headers.get("stripe-signature"))
    handled = stripe_service.apply_event(db, event)
    log.info("Stripe event %s (%s) handled=%s", event["id"], event["type"], handled)
    return {"received": True}


_PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinguaEar</title><style>body{{font-family:-apple-system,system-ui,sans-serif;background:#0b0f19;color:#fff;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;text-align:center;padding:24px}}
h1{{font-size:24px;margin:0 0 8px}}p{{color:#8b93a7;margin:0}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p></div></body></html>"""


def _back_to_app(app_url: str | None, result: str, title: str, text: str):
    """Sends the browser back into the app when there is a valid app link, otherwise shows a plain page."""
    target = stripe_service.safe_app_url(app_url)
    if target:
        separator = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{separator}result={result}", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(_PAGE.format(title=title, text=text))


@router.get("/success", include_in_schema=False)
def success(r: str | None = None):
    return _back_to_app(r, "success", "All set", "You can close this page and go back to LinguaEar.")


@router.get("/cancel", include_in_schema=False)
def cancel(r: str | None = None):
    return _back_to_app(r, "cancel", "No payment made", "You can close this page and go back to LinguaEar.")
