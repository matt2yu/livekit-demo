# Lucky Slice

A voice agent that takes pizza orders — takeout or delivery — over an inbound phone number or a
web page. Built on [LiveKit Agents](https://docs.livekit.io/agents/) and deployed to LiveKit Cloud.

## Running it

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
                                   tools ─→ SQLite (menu, orders)
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

Ordering is a set of `@function_tool`s over an `OrderState` — `add_pizza`, `add_item`,
`remove_item`, `set_quantity`, `order_summary`, `set_fulfillment`, `confirm_order`, `cancel_order`.

Two conventions do most of the work:

**Status directives.** Every mutating tool ends its return with the next expected step —
`"Added a large pepperoni. Total is twenty-two fifty. | next: ask if they'd like anything else"`.
Tool-heavy voice flows drift without this; the directive keeps a multi-step order deterministic
without a long system prompt enumerating every branch.

**Structured capture.** Name, phone, and delivery address use the built-in
`livekit.agents.beta.workflows` tasks (`GetNameTask`, `GetPhoneNumberTask`, `GetAddressTask`)
rather than free-form prompting. They handle read-back and correction — the parts callers
actually get wrong.

Unknown items fail loudly: asking for a topping that doesn't exist raises a `ToolError` naming
the real options, so the agent offers alternatives instead of silently accepting an order the
kitchen can't make.

Not modeled, deliberately: half-and-half toppings, coupons, and payment (you pay at pickup or to
the driver). Delivery is a flat $3.99 and a fixed ETA.

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

The evals in `tests/` assert behavior, not output strings — an LLM judge scores each transcript
against a rubric. They cover: prompting for size instead of assuming one, refusing unknown
toppings while offering real ones, applying mid-order quantity corrections, reading the full order
and total back before confirming, requiring an address for delivery, and declining to invent menu
items.

```bash
uv run pytest
LIVEKIT_EVALS_VERBOSE=1 uv run pytest -s -o log_cli=true   # see the judge's reasoning
```

They run without a room or audio, so they're fast and cost a few cents per run.
