import pytest

from menu import DELIVERY_FEE, serves, speak_price
from order import AmbiguousItemError, Line, Order


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


# --- two sizes of the same item -------------------------------------------
#
# The order can legitimately hold a small cheese and a large cheese. Matching on
# the item name alone silently picks whichever came first, so the caller hears
# "removed the cheese pizza" and loses the wrong one.


def two_sizes_of_cheese():
    order = Order()
    order.add(pizza(size="small"))
    order.add(pizza(size="large"))
    return order


def test_ambiguous_item_refuses_rather_than_guessing():
    order = two_sizes_of_cheese()
    with pytest.raises(AmbiguousItemError) as excinfo:
        order.find("cheese")
    assert excinfo.value.sizes == ["small", "large"]


def test_size_picks_the_intended_line():
    order = two_sizes_of_cheese()
    assert order.find("cheese", size="large").size == "large"


def test_set_quantity_with_a_size_leaves_the_other_line_alone():
    order = two_sizes_of_cheese()
    order.set_quantity("cheese", 2, size="large")
    by_size = {line.size: line.qty for line in order.lines}
    assert by_size == {"small": 1, "large": 2}


def test_remove_with_a_size_takes_only_that_line():
    order = two_sizes_of_cheese()
    removed = order.remove("cheese", size="small")
    assert removed.size == "small"
    assert [line.size for line in order.lines] == ["large"]


def test_ambiguity_needs_two_lines_not_just_a_size():
    """One line is unambiguous even when the caller omits the size."""
    order = Order()
    order.add(pizza(size="large"))
    assert order.find("cheese").size == "large"


def test_a_size_that_is_not_on_the_order_finds_nothing():
    order = two_sizes_of_cheese()
    assert order.find("cheese", size="medium") is None


# --- clearing --------------------------------------------------------------


def test_clear_empties_the_items_but_keeps_who_they_are():
    order = Order()
    order.add(pizza())
    order.customer_name = "Dana"
    order.phone_number = "5551234567"
    order.fulfillment = "delivery"
    order.address = "4200 Westheimer Road"

    order.clear()

    assert order.is_empty
    assert order.total == 0
    # Starting the food over is not the same as forgetting the caller.
    assert order.customer_name == "Dana"
    assert order.fulfillment == "delivery"
    assert order.address == "4200 Westheimer Road"


def test_an_empty_order_is_not_charged_a_delivery_fee():
    """Clearing the food must not leave the caller owing the delivery fee."""
    order = Order()
    order.fulfillment = "delivery"
    assert order.is_empty
    assert order.delivery_fee == 0
    assert order.total == 0


# --- the total the caller actually heard --------------------------------------


def test_a_fresh_order_has_never_been_read_back():
    order = Order()
    order.add(pizza())
    assert order.readback_is_stale


def test_reading_back_marks_the_priced_state_as_spoken():
    order = Order()
    order.add(pizza())
    order.summarized_state = order.priced_state
    assert not order.readback_is_stale


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("another item", lambda o: o.add(pizza(item="pepperoni"))),
        ("a quantity change", lambda o: o.set_quantity("cheese", 3)),
        ("a removal", lambda o: o.remove("cheese")),
        ("switching to delivery", lambda o: setattr(o, "fulfillment", "delivery")),
    ],
)
def test_anything_that_moves_the_total_makes_the_readback_stale(label, change):
    order = Order()
    order.add(pizza())
    order.fulfillment = "pickup"
    order.summarized_state = order.priced_state

    change(order)

    assert order.readback_is_stale, f"{label} must invalidate the spoken total"


def test_a_change_that_does_not_move_the_total_is_not_stale():
    """The caller's name isn't priced, so it doesn't need a fresh readback."""
    order = Order()
    order.add(pizza())
    order.summarized_state = order.priced_state
    order.customer_name = "Ines"
    assert not order.readback_is_stale


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


# --- catering ----------------------------------------------------------------


def catering_order(qty=40):
    order = Order()
    order.add(pizza(qty=qty))
    order.fulfillment = "pickup"
    order.customer_name = "Nadia"
    order.phone_number = "5551230244"
    return order


@pytest.mark.parametrize(
    ("count", "catering"), [(1, False), (24, False), (25, True), (200, True)]
)
def test_catering_starts_at_the_kitchen_threshold(count, catering):
    order = Order()
    order.add(pizza(qty=count))
    assert order.is_catering is catering


def test_capacity_counts_the_whole_order_not_one_line():
    """Twenty cheese and twenty pepperoni is still forty pizzas."""
    order = Order()
    order.add(pizza(item="cheese", qty=20))
    assert not order.is_catering
    order.add(pizza(item="pepperoni", qty=20))
    assert order.item_count == 40
    assert order.is_catering


@pytest.mark.parametrize(
    ("count", "lead"),
    [(30, "about three hours"), (60, "about six hours"), (200, "a full day's notice")],
)
def test_lead_time_grows_with_the_order(count, lead):
    order = Order()
    order.add(pizza(qty=count))
    assert order.lead_time == lead


def test_a_catering_order_cannot_be_placed_without_a_time_or_a_deposit():
    order = catering_order()
    missing = order.missing_for_confirm()
    assert "a time to have it ready" in missing
    assert "a deposit" in missing


def test_a_booked_and_deposited_catering_order_is_ready_to_place():
    order = catering_order()
    order.scheduled_for = "tomorrow at six"
    order.deposit_link_sent = True
    assert order.missing_for_confirm() == []


def test_a_normal_order_needs_neither_a_time_nor_a_deposit():
    order = catering_order(qty=2)
    assert order.missing_for_confirm() == []


def test_growing_past_the_threshold_reopens_the_requirements():
    """An order that becomes catering mid-call must not stay confirmable."""
    order = catering_order(qty=2)
    assert order.missing_for_confirm() == []
    order.set_quantity("cheese", 40)
    assert "a deposit" in order.missing_for_confirm()


# --- where we deliver ---------------------------------------------------------
#
# The delivery area is data, the same way the menu is. A ZIP is not a radius —
# that trade is recorded in menu.py — but an unserviceable address can't be
# accepted by accident.


@pytest.mark.parametrize(
    ("address", "served"),
    [
        ("1234 Chimney Rock, Houston, TX 77096", True),
        ("5150 Braeswood Boulevard, Houston Texas 77035", True),
        ("3300 Chimney Rock Road, Houston Texas 77081", True),
        # ZIP+4 must not be read as a different ZIP
        ("5000 Beechnut St, Houston TX 77096-1234", True),
        ("1500 Louisiana Street, Houston Texas 77002", False),
        ("4200 Westheimer Road, Houston TX 77027", False),
        # A five-digit house number is not the ZIP
        ("12345 Braeswood Blvd, Houston TX 77035", True),
        # The trailing group is the ZIP: a served number appearing earlier in the
        # line must not smuggle an unserved address through.
        ("77096 Apartments, 1500 Louisiana Street, Houston Texas 77002", False),
        ("no zip at all, Houston", False),
        ("", False),
    ],
)
def test_delivery_area_is_decided_by_the_zip(address, served):
    assert serves(address) is served
