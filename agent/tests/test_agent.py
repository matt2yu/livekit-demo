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
        # No add_pizza: guessing a size is the failure this test exists to catch.
        result.expect.no_more_events()


async def test_adds_pizza_once_size_is_known() -> None:
    """Name plus size is everything add_pizza needs — it should fire immediately."""
    async with _session() as session:
        await session.start(HireSliceAgent())

        result = await session.run(user_input="A large cheese pizza")

        result.expect.next_event().is_function_call(
            name="add_pizza", arguments={"name": "cheese", "size": "large"}
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


async def test_surfaces_a_tool_failure_instead_of_inventing_success() -> None:
    """If the order system errors, say so — don't fabricate a confirmation."""
    async with _judge() as judge, _session() as session:
        await session.start(HireSliceAgent())

        with mock_tools(
            HireSliceAgent,
            {"add_pizza": lambda: RuntimeError("order system unavailable")},
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
