# Agent

The voice agent itself — STT, LLM, TTS, and the ordering tools. See the [root README](../README.md)
for the system as a whole.

```bash
uv sync
uv run python src/agent.py console   # talk to it in the terminal
uv run pytest                        # behavior evals
```

`.env.local` needs `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (written by
`lk agent init`, or `lk app env -w -d .env.local`) and `ANTHROPIC_API_KEY`.

To serve a frontend or phone calls, use `lk agent dev` — it hot-reloads on file changes. The
Python CLI's own `dev` subcommand is deprecated and no longer auto-reloads. In production the
Dockerfile runs `start`.

## Architecture

```
phone (SIP) ─┐
             ├─→ LiveKit Cloud ─→ agent process ─→ STT ─→ LLM ─→ TTS
web (WebRTC) ┘                         │
                                   tools ─→ Order (in memory, per call)
                                            └─ menu.py (prices, tool enums)
```

The agent process is a long-lived worker. LiveKit Cloud routes each caller into a room and
dispatches a session; the agent joins that room, and the media pipeline runs per session.

| Stage | Choice | Why |
|---|---|---|
| STT | `assemblyai/universal-3-5-pro` | Via LiveKit Inference — no separate key |
| LLM | `anthropic.LLM("claude-sonnet-4-6")` | BYO Anthropic key; see the model pin note below |
| TTS | `fishaudio/s2.1-pro` | Renders the inline delivery markup that expressive mode emits |
| Turn detection | `inference.TurnDetector()` | Reads the audio directly — intonation and rhythm, not just a silence timer |
| Interruptions | `adaptive` | Distinguishes a real interruption from a backchannel ("mhm", "right") |
| Noise cancellation | `ai_coustics` QUAIL_VF_S | Callers are in kitchens, cars, and on speakerphone |

Preemptive generation is on: the LLM starts drafting before end-of-turn is confirmed, which is
most of the perceived latency win on a phone call.

## Order flow

Ordering is ten `@function_tool`s over an `Order` — `get_menu`, `add_pizza`, `add_drink`,
`add_sauce`, `remove_item`, `set_quantity`, `order_summary`, `set_fulfillment`, `collect_contact`,
`confirm_order`.

Three conventions do most of the work:

**The menu is the schema.** Tool parameter enums are generated from the menu tables at import
time, so `add_pizza`'s `name` is constrained to the three real pizzas and `toppings` to the six
real toppings. A caller asking for a calzone can't produce a valid tool call — "never invent menu
items" is enforced by the schema, not just requested in the prompt.

**Status directives.** Every mutating tool ends its return with the next expected step —
`"Added a large pepperoni. Total is twenty-two fifty. | next: ask if they'd like anything else"`.
Tool-heavy voice flows drift without this; the directive keeps a multi-step order deterministic
without a long system prompt enumerating every branch.

**Structured capture.** Name, phone, and delivery address use the built-in
`livekit.agents.beta.workflows` tasks (`GetNameTask`, `GetPhoneNumberTask`, `GetAddressTask`)
rather than free-form prompting. They handle read-back and correction — the parts callers
actually get wrong.

Unknown items still fail loudly at the tool layer as a second line of defence — `ToolError` names
the real options rather than silently accepting an order the kitchen can't make.

Not modeled, deliberately: half-and-half toppings, coupons, and payment (you pay at pickup or to
the driver). Delivery is a flat $3.99 and a fixed ETA. The menu is three pizzas, three drinks,
and four dipping sauces — there are no sides.

## Notes

Three things here are load-bearing and non-obvious.

**The model pin.** `livekit-plugins-anthropic` suppresses the trailing assistant-turn prefill only
for models matching `_NO_PREFILL_PATTERNS = ("claude-sonnet-4-6", "claude-opus-4-6")`. Claude
4.6-and-later models reject prefills with a 400, so a newer model id falls through and fails at
runtime. `claude-sonnet-4-6` is the newest model this plugin actually supports. Check before
changing it:

```bash
uv run python -c "from livekit.plugins.anthropic import llm; print(llm._NO_PREFILL_PATTERNS)"
```

**Explicit VAD.** `AgentSession` bundles a default VAD, but this project passes
`vad=inference.VAD(model="silero")` anyway. Without an explicit one the speaking anchor falls back
to the STT stream clock, which drifts across long calls and nested-task switches — turn-commit
then sleeps for roughly the elapsed call time before replying. Nested tasks and multi-minute phone
calls are exactly this project's shape.

**`uv.lock` is committed.** The Dockerfile does `COPY pyproject.toml uv.lock ./`, so the cloud
build fails at that line without it. The template ships without a lockfile and with a CI check
that *fails if you commit one* — both are template-repo machinery and were removed here.

## Tests

Two layers. `tests/test_order.py` is 18 plain unit tests over pricing and order state — no LLM, no
cost. `tests/test_agent.py` is seven behavior evals that drive the real agent:

| Eval | Asserts |
|---|---|
| Prompts for size | Asks instead of guessing, and calls no tool |
| Adds once size is known | `add_pizza(name="cheese", size="large")` fires immediately |
| Quantity correction | `set_quantity(qty=2)`, one line not two, total $34 |
| Never invents menu items | Declines a calzone, names real items, order stays empty |
| Refuses unknown topping | Won't claim pineapple was added |
| Delivery needs an address | Won't confirm while the address is missing |
| Surfaces tool failure | With `add_pizza` mocked to raise, won't fabricate success |

Assertions are deterministic where possible (`is_function_call`, `is_function_call_output`, direct
order state); the LLM judge is reserved for genuinely semantic requirements.

```bash
uv run pytest
LIVEKIT_EVALS_VERBOSE=1 uv run pytest -s -o log_cli=true   # see the judge's reasoning
```

These run text-only — `session.run()` drives the LLM directly, so STT and TTS never execute. The
judge is Anthropic rather than LiveKit Inference, so the suite costs **zero LiveKit credits**,
leaving the free tier's ~50 inference minutes for actual calls.
