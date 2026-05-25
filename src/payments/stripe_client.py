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
        success_url=settings.app_base_url.rstrip("/") + f"/payment/success?order_id={order_id}&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=settings.app_base_url.rstrip("/") + f"/payment/cancel?order_id={order_id}",
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


def _retrieve_checkout_session(session_id: str, settings: Any) -> stripe.checkout.Session:
    stripe.api_key = settings.stripe_secret_key
    return stripe.checkout.Session.retrieve(session_id)


async def retrieve_checkout_session(session_id: str) -> stripe.checkout.Session:
    """Fetch a Checkout Session directly from Stripe — used to verify payment on the success page."""
    settings = get_settings()
    return await asyncio.to_thread(_retrieve_checkout_session, session_id, settings)


def _build_payment_intent(
    customer_email: str,
    customer_name: str,
    amount_dkk: int,
    order_id: str,
    settings: Any,
) -> stripe.PaymentIntent:
    stripe.api_key = settings.stripe_secret_key
    return stripe.PaymentIntent.create(
        amount=amount_dkk * 100,  # øre
        currency="dkk",
        receipt_email=customer_email,
        description=f"AIScore Rapport — {customer_name}",
        metadata={"order_id": order_id},
        payment_method_types=["card"],
    )


async def create_payment_intent(
    customer_email: str,
    customer_name: str,
    amount_dkk: int,
    application_id: uuid.UUID,
) -> stripe.PaymentIntent:
    """Create a Stripe Payment Intent for a customer application payment."""
    settings = get_settings()
    return await asyncio.to_thread(
        _build_payment_intent,
        customer_email,
        customer_name,
        amount_dkk,
        str(application_id),
        settings,
    )


def _retrieve_payment_intent(pi_id: str, settings: Any) -> stripe.PaymentIntent:
    stripe.api_key = settings.stripe_secret_key
    return stripe.PaymentIntent.retrieve(pi_id)


async def retrieve_payment_intent(pi_id: str) -> stripe.PaymentIntent:
    """Fetch a Payment Intent from Stripe — used to get client_secret for the checkout page."""
    settings = get_settings()
    return await asyncio.to_thread(_retrieve_payment_intent, pi_id, settings)


def construct_stripe_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify Stripe webhook signature and return the parsed event."""
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
