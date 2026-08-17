"""Unit tests for the order write path. No network — the row shape is the contract."""

import pytest

import orders_db
from order import Line, Order
from tools import Userdata


def _confirmed_order() -> Order:
    order = Order()
    order.add(Line("pizza", "cheese", size="large", toppings=("mushrooms",)))
    order.add(Line("drink", "coke", size="medium", qty=2))
    order.fulfillment = "pickup"
    order.customer_name = "Will"
    order.phone_number = "5555550123"
    order.confirmed_code = "AB12"
    # confirm_order refuses to place an order whose total the caller hasn't heard,
    # so a ready-to-confirm order is one that has just been read back.
    order.summarized_state = order.priced_state
    return order


def test_row_carries_every_column_the_schema_requires():
    row = orders_db._row(_confirmed_order(), channel="phone", room="call-abc")
    for column in (
        "code",
        "channel",
        "room",
        "customer_name",
        "phone_number",
        "fulfillment",
        "items",
        "subtotal",
        "delivery_fee",
        "total",
    ):
        assert row[column] is not None, f"{column} would violate a NOT NULL constraint"


def test_row_copies_unit_price_rather_than_referencing_the_menu():
    """An order records what was quoted; repricing the menu must not rewrite history."""
    order = _confirmed_order()
    row = orders_db._row(order, channel="web", room=None)

    pizza = next(i for i in row["items"] if i["item"] == "cheese")
    assert pizza["unit_price"] == pytest.approx(18.50)
    assert pizza["toppings"] == ["mushrooms"]
    assert pizza["size"] == "large"


def test_row_totals_match_the_order():
    order = _confirmed_order()
    row = orders_db._row(order, channel="web", room=None)
    assert row["subtotal"] == pytest.approx(order.subtotal)
    assert row["total"] == pytest.approx(order.total)
    assert row["delivery_fee"] == pytest.approx(0.0)


def test_delivery_row_carries_the_address():
    order = _confirmed_order()
    order.fulfillment = "delivery"
    order.address = "742 Evergreen Terrace"
    row = orders_db._row(order, channel="phone", room="call-x")

    assert row["address"] == "742 Evergreen Terrace"
    assert row["delivery_fee"] == pytest.approx(3.99)


async def test_save_is_a_no_op_when_supabase_is_not_configured(monkeypatch):
    """A missing config must not raise mid-call."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    assert orders_db.is_configured() is False
    assert await orders_db.save_order(_confirmed_order(), channel="web") is False


@pytest.mark.parametrize(
    ("room", "expected"),
    [
        ("call-_abc123", "phone"),
        ("playground-xyz", "web"),
        (None, "web"),
    ],
)
def test_channel_is_derived_from_the_room_prefix(room, expected):
    """The SIP dispatch rule prefixes phone rooms with 'call-'."""
    assert Userdata(room=room).channel == expected


class _Ctx:
    """Minimal RunContext stand-in: confirm_order only needs userdata and the
    interruption guard."""

    def __init__(self, userdata: Userdata):
        self.userdata = userdata
        self.interruptions_disallowed = False

    def disallow_interruptions(self) -> None:
        self.interruptions_disallowed = True


async def _confirm(userdata: Userdata):
    from livekit.agents import ToolError

    from tools import OrderingTools

    ctx = _Ctx(userdata)
    try:
        return (
            await OrderingTools.confirm_order._func(
                OrderingTools(), ctx, read_back=True
            ),
            None,
            ctx,
        )
    except ToolError as exc:
        return None, exc, ctx


async def test_confirm_disallows_interruptions_before_writing(monkeypatch):
    """Placing an order can't be rolled back, so speech must not interrupt it."""
    monkeypatch.setattr(orders_db, "is_configured", lambda: False)

    userdata = Userdata(order=_confirmed_order(), room="call-abc")
    userdata.order.confirmed_code = None
    _, err, ctx = await _confirm(userdata)

    assert err is None
    assert ctx.interruptions_disallowed


async def test_failed_write_leaves_no_confirmation(monkeypatch):
    """A caller must never be told an order is coming when the kitchen never got it."""

    async def failing_save(*args, **kwargs):
        return False

    monkeypatch.setattr(orders_db, "is_configured", lambda: True)
    monkeypatch.setattr(orders_db, "save_order", failing_save)

    userdata = Userdata(order=_confirmed_order(), room="call-abc")
    userdata.order.confirmed_code = None
    _, err, _ = await _confirm(userdata)

    assert err is not None, "a failed write must raise so the agent tells the caller"
    assert userdata.order.confirmed_code is None, "no code may survive a failed write"


async def test_successful_write_issues_a_code(monkeypatch):
    saved: dict = {}

    async def ok_save(order, *, channel, room=None, caller_id=None):
        saved.update(channel=channel, room=room, code=order.confirmed_code)
        return True

    monkeypatch.setattr(orders_db, "is_configured", lambda: True)
    monkeypatch.setattr(orders_db, "save_order", ok_save)

    userdata = Userdata(order=_confirmed_order(), room="call-abc")
    userdata.order.confirmed_code = None
    _, err, _ = await _confirm(userdata)

    assert err is None
    assert userdata.order.confirmed_code is not None
    assert saved["channel"] == "phone"
    assert saved["code"] == userdata.order.confirmed_code
