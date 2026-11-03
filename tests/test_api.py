"""HTTP surface: tenancy at the edge, idempotent ingest, customer status, shop list."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.dispatch import CollectingDispatcher
from app.extraction.schema import ServicePick
from tests.conftest import date_expr, make_extraction
from tests.helpers import KEYS, make_pipeline, set_cap

pytestmark = pytest.mark.db


@pytest.fixture
async def client(db, settings):
    dispatcher = CollectingDispatcher()
    app = create_app(settings, db=db, dispatcher=dispatcher)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.dispatcher = dispatcher
            yield c


def h(shop_id):
    return {"X-API-Key": KEYS[shop_id]}


MSG = {"message_id": "m-1027", "channel": "web", "received_at": "2026-09-22T10:50:00", "body": "Brakes squeal."}


async def test_auth_missing_wrong_and_cross_shop_keys(client):
    assert (await client.post("/shops/rb-downtown/messages", json=MSG)).status_code == 401
    assert (
        await client.post("/shops/rb-downtown/messages", json=MSG, headers={"X-API-Key": "nope"})
    ).status_code == 404
    r = await client.post("/shops/rb-lakeshore/messages", json=MSG, headers=h("rb-downtown"))
    assert r.status_code == 404  # a valid key for another shop looks exactly like a missing shop


async def test_ingest_is_202_then_200_duplicate(client):
    r1 = await client.post("/shops/rb-downtown/messages", json=MSG, headers=h("rb-downtown"))
    r2 = await client.post("/shops/rb-downtown/messages", json=MSG, headers=h("rb-downtown"))
    assert r1.status_code == 202 and r1.json()["duplicate"] is False
    assert r2.status_code == 200 and r2.json()["duplicate"] is True
    assert r1.json()["status_url"] == r2.json()["status_url"]
    assert len(client.dispatcher.published) == 1


async def test_reply_to_unknown_or_foreign_message_is_422(client):
    await client.post("/shops/rb-downtown/messages", json=MSG, headers=h("rb-downtown"))
    reply = {"message_id": "r-1", "channel": "web", "body": "Saturday", "in_reply_to": "m-1027"}
    assert (await client.post("/shops/rb-lakeshore/messages", json=reply, headers=h("rb-lakeshore"))).status_code == 422
    assert (await client.post("/shops/rb-downtown/messages", json=reply, headers=h("rb-downtown"))).status_code == 202


async def test_customer_status_and_shop_list_through_the_follow_up_loop(client, db, settings, provider):
    pipeline = make_pipeline(db, settings, provider)
    await client.post("/shops/rb-downtown/messages", json=MSG, headers=h("rb-downtown"))
    s = (await client.get("/shops/rb-downtown/messages/m-1027", headers=h("rb-downtown"))).json()
    assert s["status"] == "received"

    provider.scripted["rb-downtown/m-1027"] = make_extraction(
        outcome="ask_customer", question="Rim or hydraulic, and which day?", date=date_expr(kind="none")
    )
    await pipeline.run_job(client.dispatcher.published[0].job_id)
    s = (await client.get("/shops/rb-downtown/messages/m-1027", headers=h("rb-downtown"))).json()
    assert s["status"] == "awaiting_your_reply" and "Rim or hydraulic" in s["question"]

    lst = (await client.get("/shops/rb-downtown/work-orders", headers=h("rb-downtown"))).json()
    assert lst["count"] == 0 and lst["order_counts"] == {"awaiting_customer": 1}
    assert lst["budget"]["exhausted"] is False and lst["ai"]["degraded"] is False

    reply = {"message_id": "r-1", "channel": "web", "body": "Rim. Saturday.", "in_reply_to": "m-1027"}
    await client.post("/shops/rb-downtown/messages", json=reply, headers=h("rb-downtown"))
    provider.scripted["rb-downtown/m-1027/resume"] = make_extraction(
        services=[ServicePick(code="BRAKE_ADJUST", quantity=2, evidence="brakes squeal")]
    )
    await pipeline.run_job(client.dispatcher.published[1].job_id)

    for mid in ("m-1027", "r-1"):  # the reply reports on the order it belongs to
        s = (await client.get(f"/shops/rb-downtown/messages/{mid}", headers=h("rb-downtown"))).json()
        assert s["status"] == "confirmed" and s["estimate"]["total"] == "36.00" and s["requested_date"] == "2026-09-26"

    lst = (await client.get("/shops/rb-downtown/work-orders", headers=h("rb-downtown"))).json()
    assert lst["count"] == 1 and lst["estimated_total"] == "36.00"
    assert lst["work_orders"][0]["estimate"]["line_items"][0]["code"] == "BRAKE_ADJUST"
    # The other shop sees nothing.
    other = (await client.get("/shops/rb-lakeshore/work-orders?status=all", headers=h("rb-lakeshore"))).json()
    assert other["count"] == 0 and other["order_counts"] == {}


async def test_cap_hit_is_visible_to_shop_and_neutral_to_customer(client, db, settings, provider):
    set_cap("rb-northside", 0.000001)
    pipeline = make_pipeline(db, settings, provider)
    await client.post("/shops/rb-northside/messages", json={**MSG, "message_id": "m-1"}, headers=h("rb-northside"))
    await pipeline.run_job(client.dispatcher.published[0].job_id)
    s = (await client.get("/shops/rb-northside/messages/m-1", headers=h("rb-northside"))).json()
    assert s["status"] == "received"  # the customer never sees "budget"
    lst = (await client.get("/shops/rb-northside/work-orders", headers=h("rb-northside"))).json()
    assert lst["ai"]["parked_budget_cap"] == 1 and lst["ai"]["waiting"] == 1
