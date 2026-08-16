import pytest

from menu import DELIVERY_FEE, speak_price
from order import Line, Order


def pizza(item="cheese", size="large", toppings=(), qty=1):
    return Line(category="pizza", item=item, size=size, toppings=toppings, qty=qty)


def test_pizza_price_includes_toppings():
    plain = pizza(toppings=())
    loaded = pizza(toppings=("mushrooms", "olives"))
    assert loaded.unit_price == plain.unit_price + 3.00


def test_identical_lines_dedupe_by_bumping_quantity():
    order = Order()
    order.add(pizza())
    order.add(pizza())
    assert len(order.lines) == 1
    assert order.lines[0].qty == 2


def test_lines_differing_by_size_do_not_merge():
    order = Order()
    order.add(pizza(size="large"))
    order.add(pizza(size="small"))
    assert len(order.lines) == 2


def test_toppings_merge_regardless_of_order():
    order = Order()
    order.add(pizza(toppings=("olives", "mushrooms")))
    order.add(pizza(toppings=("mushrooms", "olives")))
    assert len(order.lines) == 1
    assert order.lines[0].qty == 2


def test_set_quantity_replaces_rather_than_adds():
    order = Order()
    order.add(pizza())
    order.set_quantity("cheese", 2)
    assert order.lines[0].qty == 2


def test_set_quantity_to_zero_removes_the_line():
    order = Order()
    order.add(pizza())
    order.set_quantity("cheese", 0)
    assert order.is_empty


def test_remove_returns_the_line_and_empties_the_order():
    order = Order()
    order.add(pizza())
    removed = order.remove("cheese")
    assert removed is not None
    assert order.is_empty


def test_delivery_fee_applies_only_to_delivery():
    order = Order()
    order.add(pizza())
    subtotal = order.subtotal

    order.fulfillment = "pickup"
    assert order.total == pytest.approx(subtotal)

    order.fulfillment = "delivery"
    assert order.total == pytest.approx(subtotal + DELIVERY_FEE)


def test_missing_for_confirm_lists_every_gap():
    order = Order()
    missing = order.missing_for_confirm()
    assert "at least one item" in missing
    assert "pickup or delivery" in missing
    assert "a name" in missing
    assert "a phone number" in missing


def test_delivery_requires_an_address_but_pickup_does_not():
    order = Order()
    order.add(pizza())
    order.customer_name = "Matt"
    order.phone_number = "5551234567"

    order.fulfillment = "delivery"
    assert "a delivery address" in order.missing_for_confirm()

    order.fulfillment = "pickup"
    assert order.missing_for_confirm() == []


def test_switching_to_delivery_after_items_updates_the_total():
    order = Order()
    order.add(pizza())
    order.fulfillment = "pickup"
    before = order.total
    order.fulfillment = "delivery"
    assert order.total == pytest.approx(before + DELIVERY_FEE)


@pytest.mark.parametrize(
    ("amount", "spoken"),
    [
        (17.00, "seventeen dollars"),
        (12.50, "twelve fifty"),
        (1.00, "one dollar"),
        (0.75, "seventy-five cents"),
        # "twenty-two five" would be heard as $22.50
        (22.05, "twenty-two oh five"),
        (3.99, "three ninety-nine"),
    ],
)
def test_prices_are_spoken_naturally(amount, spoken):
    assert speak_price(amount) == spoken


def test_readback_mentions_items_delivery_and_total():
    order = Order()
    order.add(pizza(toppings=("mushrooms",)))
    order.fulfillment = "delivery"
    text = order.readback()
    assert "cheese" in text
    assert "mushrooms" in text
    assert "delivery" in text
    assert speak_price(order.total) in text
