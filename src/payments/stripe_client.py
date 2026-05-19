"""
Stripe checkout session creation and webhook verification.

Uses asyncio.to_thread() because the Stripe SDK is synchronous.
"""

import asyncio
import uuid
import stripe
from typing import Any

from src.config import get_settings


def _build_checkout_session(
    customer_email: str,
    customer_name: str,
    amount_dkk: int,
    order_id: str,
    settings: Any,
) -> stripe.checkout.Session:
    stripe.api_key = settings.stripe_secret_key
    return stripe.checkout.Session.create(
        customer_email=customer_email,
        payment_method_types=["card"],  # explicit list disables Stripe Link
        line_items=[
            {
                "price_data": {
                    "currency": "dkk",
                    "product_data": {"name": f"AIScore Rapport — {customer_name}"},
                    "unit_amount": amount_dkk * 100,  # øre
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        success_url=settings.payment_success_url + f"?order_id={order_id}",
        cancel_url=settings.payment_cancel_url + f"?order_id={order_id}",
        metadata={"order_id": order_id},
        expires_at=int(__import__("time").time()) + 3600,  # 1 hour window
    )


async def create_checkout_session(
    customer_email: str,
    customer_name: str,
    amount_dkk: int,
    application_id: uuid.UUID,
) -> stripe.checkout.Session:
    """Create a Stripe Checkout session for a customer application payment."""
    settings = get_settings()
    session = await asyncio.to_thread(
        _build_checkout_session,
        customer_email,
        customer_name,
        amount_dkk,
        str(application_id),
        settings,
    )
    return session


def construct_stripe_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify Stripe webhook signature and return the parsed event."""
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
