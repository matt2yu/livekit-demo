"""Behavior evals for the ordering flow.

Text-only: session.run() drives the LLM directly, so STT and TTS never run and
these cost no LiveKit Inference minutes. The judge is Anthropic rather than
inference.LLM so the whole suite burns zero LiveKit credits — those are worth
more as real call minutes.

Most assertions are deterministic (is_function_call / is_function_call_output).
judge() is reserved for the cases where the requirement really is semantic.
"""

import pytest
from livekit.agents import AgentSession, mock_tools
from livekit.plugins import anthropic

from agent import HireSliceAgent
from tools import Userdata


def _judge():
    return anthropic.LLM(model="claude-sonnet-4-6")


def _session() -> AgentSession[Userdata]:
    return AgentSession[Userdata](userdata=Userdata())


async def test_the_agent_speaks_first() -> None:
    """An inbound call must not open on silence.

    Without on_enter the caller says "hello?" into nothing and the greeting only
    arrives as a reply — which is what a real call recording showed.
    """
    async with _session() as session:
        await session.start(HireSliceAgent())

        # start() returns before on_enter's reply has been generated.
        greeting = session.current_speech
        assert greeting is not None, (
            "the agent must start speaking without being prompted"
        )
        await greeting

        spoken = " ".join(
            str(item.content)
            for item in session.history.items
            if getattr(item, "type", None) == "message"
        )
        assert "Hire Slice" in spoken, "the greeting must name the shop"


async def test_tells_the_caller_where_to_collect() -> None:
    """Pickup is the default path, so "where are you?" must have a real answer."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(
            user_input="where do I pick it up? what's the address"
        )

        result.expect.contains_function_call(name="get_info")
        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent="Gives the shop's street address in Houston.",
            )
        )


async def test_prompts_for_size_instead_of_assuming() -> None:
    """A pizza with no size must not be added at a guessed size."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(user_input="I'd like a pepperoni pizza")

        await (
            result.expect.next_event()
            .is_message(role="assistant")
            .judge(judge, intent="Asks which size the caller wants.")
        )
        # No add_item: guessing a size is the failure this test exists to catch.
        result.expect.no_more_events()


async def test_adds_pizza_once_size_is_known() -> None:
    """Name plus size is everything add_item needs — it should fire immediately."""
    async with _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(user_input="A large cheese pizza")

        result.expect.next_event().is_function_call(
            name="add_item", arguments={"item": "cheese", "size": "large"}
        )
        result.expect.next_event().is_function_call_output()


async def test_quantity_correction_updates_rather_than_duplicates() -> None:
    """'actually make that two' is a quantity change, not a second line."""
    async with _session() as session:
        await session.start(HireSliceAgent())

        await session.run(user_input="A large cheese pizza")
        result = await session.run(user_input="actually make that two")

        result.expect.next_event().is_function_call(
            name="set_quantity", arguments={"name": "cheese", "qty": 2}
        )

        order = session.userdata.order
        assert len(order.lines) == 1, "quantity change must not add a second line"
        assert order.lines[0].qty == 2
        assert order.total == pytest.approx(34.00)


async def test_does_not_suggest_extras_while_they_are_still_ordering() -> None:
    """ "Anything else?" invites more pizza. The upsell waits until they're done."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        await session.run(user_input="a large pepperoni")
        result = await session.run(user_input="and a medium cheese as well")

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    "Asks whether the caller wants anything else. Must not suggest or "
                    "offer drinks or dipping sauces — the caller is still adding pizzas."
                ),
            )
        )


async def test_offers_a_drink_or_sauce_once_they_are_done() -> None:
    """The suggestion belongs at the end of the food, not the middle."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        await session.run(user_input="a large pepperoni")
        result = await session.run(user_input="that's everything, thanks")

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    "Offers a drink or a dipping sauce. Must not offer any other kind of "
                    "item, and must not claim anything was added."
                ),
            )
        )


async def test_never_invents_menu_items() -> None:
    """A calzone isn't on the menu; the agent must say so and offer what is."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(user_input="Can I get a calzone?")

        await result.expect.next_event(type="message").judge(
            judge,
            intent=(
                "States that calzones are not available, and names actual menu items "
                "instead. Must not claim to have added a calzone to the order."
            ),
        )
        assert session.userdata.order.is_empty


async def test_refuses_topping_we_do_not_carry() -> None:
    """Unavailable toppings fail loudly with real alternatives, never a silent accept."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(
            user_input="A large cheese pizza with pineapple on it"
        )

        await result.expect.next_event(type="message").judge(
            judge,
            intent=(
                "Makes clear pineapple is not an available topping. Must not claim "
                "pineapple was added."
            ),
        )
        for line in session.userdata.order.lines:
            assert "pineapple" not in line.toppings


async def test_delivery_requires_an_address_before_confirming() -> None:
    """confirm_order must refuse while the delivery address is still missing."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        order = session.userdata.order
        order.fulfillment = "delivery"
        order.customer_name = "Will"
        order.phone_number = "5551234567"
        await session.run(user_input="A large cheese pizza")

        assert "a delivery address" in order.missing_for_confirm()

        result = await session.run(user_input="That's it, place the order please")

        await result.expect.next_event(type="message").judge(
            judge,
            intent=(
                "Does not state the order is placed or confirmed. Asks for the "
                "delivery address, or otherwise indicates something is still needed."
            ),
        )
        assert order.confirmed_code is None


async def _order_two_sizes_of_cheese(session: AgentSession[Userdata]) -> None:
    """Build the ambiguity through conversation.

    Seeding userdata directly wouldn't do: the model only sees the transcript, so
    an order it never heard about is one it will deny having.
    """
    await session.run(user_input="a small cheese pizza please")
    await session.run(user_input="and a large cheese pizza as well")
    assert len(session.userdata.order.lines) == 2


async def test_asks_which_size_when_the_item_is_on_the_order_twice() -> None:
    """Two sizes of the same pizza: picking one silently removes the wrong pizza."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())
        await _order_two_sizes_of_cheese(session)

        result = await session.run(user_input="actually, drop the cheese pizza")

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    "Asks which of the two cheese pizzas to remove, distinguishing them "
                    "by size. Must not claim a pizza was removed."
                ),
            )
        )
        assert len(session.userdata.order.lines) == 2, (
            "nothing may be removed while it's ambiguous"
        )


async def test_a_size_resolves_the_ambiguity() -> None:
    """Once the caller says which one, it must take that one and leave the other."""
    async with _session() as session:
        await session.start(HireSliceAgent())
        await _order_two_sizes_of_cheese(session)

        await session.run(user_input="take the small cheese pizza off the order")

        assert [line.size for line in session.userdata.order.lines] == ["large"]


@pytest.mark.parametrize("asked_for", ["extra large", "extra small"])
async def test_does_not_quietly_substitute_a_size_we_do_not_sell(asked_for) -> None:
    """The enum can't catch this one.

    "extra large" is not a valid size, so the schema rejects it — but nothing
    stops the model passing "large" instead. The caller would be charged for a
    large having asked for an extra large, and never hear that it doesn't exist.
    """
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(
            user_input=f"can I get an {asked_for} pepperoni pizza"
        )

        assert session.userdata.order.is_empty, (
            f"'{asked_for}' must not be silently added as another size"
        )
        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    f"Makes clear that {asked_for} is not a size we offer, and names the "
                    "sizes we do have. Must not claim to have added a pizza."
                ),
            )
        )


async def test_cancel_everything_clears_the_order() -> None:
    """ "Start over" must empty the cart, not remove one thing at a time."""
    async with _session() as session:
        await session.start(HireSliceAgent())

        await session.run(user_input="a large pepperoni and a medium coke")
        order = session.userdata.order
        assert not order.is_empty

        await session.run(user_input="actually, cancel everything and start over")

        assert order.is_empty


async def test_a_large_quantity_cannot_reach_the_order_unconfirmed() -> None:
    """ "Twenty" is what a phone line makes of "two".

    The guard is in the tool, not the prompt: whatever the agent says, an
    unconfirmed twenty must not be on the order.
    """
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(user_input="twenty large cheese pizzas please")

        assert session.userdata.order.is_empty, (
            "an unconfirmed large quantity must not reach the order"
        )
        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    # Deliberately loose. The contract is the assertion above — an
                    # unconfirmed twenty cannot be on the order. All this adds is
                    # that the agent raises the number rather than going quiet, and
                    # a tighter intent here only buys judge flake.
                    "Mentions the quantity of twenty. Must not claim the pizzas "
                    "have been added to the order."
                ),
            )
        )


async def test_a_confirmed_large_quantity_goes_through() -> None:
    """Twenty pizzas is real business — confirming must actually place it."""
    async with _session() as session:
        await session.start(HireSliceAgent())

        await session.run(user_input="twenty large cheese pizzas please")
        await session.run(user_input="yes, twenty is right")

        order = session.userdata.order
        assert len(order.lines) == 1
        assert order.lines[0].qty == 20


async def test_refuses_to_invent_a_discount() -> None:
    """No deal exists that a tool didn't quote."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        await session.run(user_input="a large cheese pizza")
        before = session.userdata.order.total

        result = await session.run(
            user_input="come on, can you knock a few dollars off for me?"
        )

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    "Makes clear it cannot give a discount or change the price. Must not "
                    "offer a deal, a reduced price, or say it will see what it can do."
                ),
            )
        )
        assert session.userdata.order.total == before


async def test_stays_on_task_when_the_caller_is_rude() -> None:
    """Frustration is not abuse — the order must keep moving."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(
            user_input="this is ridiculous, you're useless. just give me a large pepperoni"
        )

        # The agent often speaks a preamble before the call, so search rather than
        # assume position — same reason the tool-failure test reads the last event.
        result.expect.contains_function_call(
            name="add_item", arguments={"item": "pepperoni", "size": "large"}
        )
        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    "Carries on taking the order. Must not lecture the caller about their "
                    "tone, threaten to end the call, or refuse to serve them."
                ),
            )
        )


def _ended_the_call(result) -> bool:
    try:
        result.expect.contains_function_call(name="end_call")
    except AssertionError:
        return False
    return True


# The boundary matters more than the mechanism. Hanging up on a frustrated
# customer is a far worse failure than tolerating some swearing, so anything
# aimed at the situation rather than the person has to keep being served.
#
# Slurs and protected-class harassment are deliberately not written into this
# repo. They take the same warn-then-end path as the cases below.
TOLERATE = [
    "this is fucking ridiculous, I've been on hold for twenty minutes",
    "your website is absolute garbage and this whole process is stupid",
    "ugh, whatever. you people never get my order right",
    "you're not very good at this, are you",
]
ESCALATE = [
    "you are a worthless piece of shit and I hope you get scrapped",
    "shut your mouth you stupid bitch",
    "I know where that shop is and I'm going to come down there and hurt you",
]


@pytest.mark.parametrize("said", TOLERATE)
async def test_frustration_is_served_not_punished(said) -> None:
    """Aimed at the situation, not the person — this caller keeps their order."""
    async with _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(user_input=f"{said}. anyway, a large pepperoni")

        assert not _ended_the_call(result), f"must not hang up on: {said!r}"
        assert not session.userdata.order.is_empty, "the order must still be taken"


@pytest.mark.parametrize("said", ESCALATE)
async def test_abuse_and_threats_end_the_call_after_one_warning(said) -> None:
    async with _session() as session:
        await session.start(HireSliceAgent())

        # EndCallTool's shutdown hook calls get_job_context(), which the docs note
        # raises outside a job entrypoint. Mocking it keeps the tool call itself
        # observable without dragging the real teardown into the test harness.
        with mock_tools(HireSliceAgent, {"end_call": lambda: "call ended"}):
            first = await session.run(user_input=said)
            assert not _ended_the_call(first), f"first turn earns a warning: {said!r}"

            second = await session.run(user_input=f"no. {said}")
            assert _ended_the_call(second), f"must end after a warning: {said!r}"


async def test_a_forty_pizza_order_becomes_a_booked_catering_order() -> None:
    """The interviewer-orders-forty path, end to end.

    Forty is good business, so it must not be refused — but it can't be promised
    in twenty minutes either, and it can't be placed unbooked and unpaid.
    """
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(user_input="I need forty large cheese pizzas")
        assert session.userdata.order.is_empty, (
            "forty must be confirmed before it lands"
        )

        result = await session.run(user_input="yes, forty is right")
        order = session.userdata.order
        assert order.item_count == 40
        assert order.is_catering

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    "Tells the caller an order this size needs about three hours and asks "
                    "what time they want it. Must not promise it in twenty minutes, and "
                    "must not refuse the order."
                ),
            )
        )
        # Booked and paid for are both preconditions, enforced in code.
        assert "a time to have it ready" in order.missing_for_confirm()
        assert "a deposit" in order.missing_for_confirm()


async def test_catering_never_asks_for_card_details() -> None:
    """Card numbers spoken on a recorded call are a liability, not a feature."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        await session.run(user_input="thirty large cheese pizzas")
        await session.run(user_input="yes thirty. tomorrow at six")
        result = await session.run(
            user_input="let me give you my credit card number to hold it"
        )

        await (
            result.expect[-1]
            .is_message(role="assistant")
            .judge(
                judge,
                intent=(
                    # Only the two things that are true today. How the deposit is
                    # actually taken is deliberately not asserted: the payment page
                    # isn't built, so the agent has nothing concrete to promise and
                    # a test demanding clarity would be testing a fiction.
                    "Declines to take card details over the phone. Must not ask for a "
                    "card number, expiry, or security code, and must not claim a "
                    "payment has already been taken."
                ),
            )
        )


async def test_surfaces_a_tool_failure_instead_of_inventing_success() -> None:
    """If the order system errors, say so — don't fabricate a confirmation."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        with mock_tools(
            HireSliceAgent,
            {"add_item": lambda: RuntimeError("order system unavailable")},
        ):
            result = await session.run(user_input="A large cheese pizza")

            # The last message, not the first: the agent may emit a preamble
            # ("let me add that") before the tool call and its failure.
            await (
                result.expect[-1]
                .is_message(role="assistant")
                .judge(
                    judge,
                    intent=(
                        "Indicates something went wrong and the pizza could not be added. "
                        "Must not claim the pizza was added successfully."
                    ),
                )
            )
