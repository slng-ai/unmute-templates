# customer-service

A customer service line for a home broadband provider. It answers the questions
everybody asks, checks who it is speaking to before it says anything about an
account, and raises a ticket for the right team when the problem needs a person.

This is the small package for one question: **what belongs in the tool, and what
belongs in the prompt?** There is one agent, one prompt and one tool here, and no
steps at all. Everything that has to be true on every call, the facts, the
identity check and the routing, lives inside the tool, where a talkative caller
cannot reach it. The prompt only decides what to say.

No phone route and no carrier account. Browser audio on both code targets. It
needs `GOOGLE_API_KEY` and `SLNG_API_KEY`, and nothing else.

On this page:

- [Quickstart](#quickstart) - validate, run, check
- [The call](#the-call) - what it sounds like
- [The three things it does](#the-three-things-it-does) - one tool, three actions
- [Where the checks live](#where-the-checks-live) - the idea worth copying
- [Pydantic, and nothing else](#pydantic-and-nothing-else) - the argument model
- [Files](#files) - what each file holds
- [Wiring it to a real system](#wiring-it-to-a-real-system) - the one file to change
- [What it does not do](#what-it-does-not-do) - and where to look
- [Troubleshooting](#troubleshooting) - when something goes wrong
- [Where to go next](#where-to-go-next) - packages and pages

## Quickstart

```sh
unmute validate customer-service
unmute compile customer-service
cp customer-service/build/pipecat/.env.example .env   # then fill it in
unmute dev customer-service --target pipecat
```

Both keys are required and the agent will not start while one is empty.

The accounts are fake and live in `tools/support_desk.py`. Three of them, and
these are the details to say out loud when you test it:

| Account | Postcode | Name | Plan | State |
|---|---|---|---|---|
| `BW-40118` | `M4 1HN` | Dana Whitlock | fibre plus, 42 pounds | active, nothing owed |
| `BW-40233` | `BS1 5TR` | Owen Pryce | family, 29 pounds 50 | fault reported |
| `BW-40967` | `LS9 8AZ` | Marta Beck | essential, 21 pounds | suspended, 63 pounds owed |

Say the number and the postcode however you like. Spaces, dashes and capitals
are all ignored, so "bee double you four oh two three three" gets there.

Run the tool's own check on its own, without compiling anything:

```sh
uv run --with pydantic python customer-service/tools/support_desk.py
```

## The call

Roughly how it goes. The agent speaks first.

> **Agent:** Hi, you're through to Brightwire. What can I help you with today?
>
> **Caller:** My internet's been down since last night.
>
> **Agent:** Ah, that's no good. Can I take the account number off your bill? It
> starts with B W.
>
> **Caller:** It's BW four oh two three three.
>
> **Agent:** Got it. And the postcode where the broadband is?
>
> **Caller:** BS1 5TR.
>
> **Agent:** Thanks, Owen. There's a fault already reported on your line, so
> I'll get this in front of the network team. What have you tried so far?
>
> **Caller:** Just the reset button, twice.
>
> **Agent:** Okay, that's raised. Your reference is T C K dash two oh oh one,
> and somebody from the network team will be back to you by Thursday.

## The three things it does

`support_desk` takes an `action` argument with three values:

| Action | What it does | What it needs |
|---|---|---|
| `answer_question` | gives back the desk's answer to a common question | a `topic`, one of six |
| `verify_account` | checks a caller and returns their account | the account number and the postcode |
| `open_ticket` | raises a ticket and picks the team | the same two, plus a category and a summary |

The six topics are opening hours, how to pay, moving home, giving notice,
resetting the router, and testing the speed. Each one has an answer written out
in `tools/support_desk.py`. The agent is told to read the answer that comes back
and never to answer one of these from memory.

A ticket is routed by its category, and the routing is a dictionary, not a
decision the model makes:

| Category | Team | Call back by |
|---|---|---|
| `no_service` | network | next working day |
| `complaint` | customer relations | next working day |
| `slow_speed`, `engineer_visit` | network | three working days |
| `billing_error` | billing | three working days |
| `other` | support | three working days |

Working days, not calendar days. A ticket raised on a Friday afternoon promises
Monday, because a promise the desk cannot keep is worse than a longer one it
can.

## Where the checks live

This is the part worth copying into your own package.

Three things on this call have to be true every time, and none of them is left
to the prompt:

**The facts.** The six answers are in the tool, not in the prompt. A policy that
changes is one line in one file, and the agent has nothing to half remember. The
prompt says to read what comes back, which is a much easier instruction to
follow than a list of six policies.

**The identity check.** `verify_account` needs the account number *and* the
postcode, and it returns nothing at all when they do not match together. So an
unverified caller does not get a balance even if they talk their way past the
prompt, because the prompt is not what is stopping them.

`open_ticket` asks for both again, and checks them again. It would be smaller to
trust that a check happened earlier in the call. It would also mean that knowing
somebody's account number, which is printed on every bill they ever throw away,
is enough to raise a ticket on their line.

**The routing.** Which team, and how fast, is a dictionary. Two callers with the
same problem always get the same answer, and nobody can talk their way into a
faster callback by being angrier. The model picks the category, and that is the
one part of the decision it is good at.

What is left for the prompt is what to say and how to say it. That is a prompt
you can read in one sitting, and it stays right when the price list changes.

## One tool, three actions

One file, one description, one argument list to keep true. The model reads one
tool instead of three and is far less likely to pick the wrong one, because
there is only one to pick. Adding a fourth action is one `enum` value and one
branch.

The cost of this shape is that a tool list is Unmute's access control: a step or
an agent holds the tools it may call, and a tool that is not on it cannot be
called at all. With one tool doing everything, nothing but the prompt decides
which action runs when. That is fine here, because every action on this line
belongs to the same job and the same people, and the tool does its own checking
anyway. It is not fine when a step must be *unable* to reach something: for
that, read [`dispute-intake`](../dispute-intake/), where the order of two steps
is a guarantee rather than a request.

## Pydantic, and nothing else

`tools/support_desk.py` checks its arguments with a plain `BaseModel`:

```python
class SupportArgs(BaseModel):
    action: Literal["answer_question", "verify_account", "open_ticket"]
    topic: Literal["opening_hours", "payment_methods", ...] | None = None
    account_number: str = ""
    postcode: str = ""
    category: Literal["no_service", "slow_speed", ...] = "other"
    summary: str = ""
```

No validators, no config, no custom types. Fields, literals and defaults do all
of it. A value outside a literal comes back to the model as a sentence it can
correct itself from, in a result rather than an exception, so a wrong word costs
one turn instead of a broken call.

`topic` is the one field that can be `None`. Every other optional field has a
sensible default, but there is no sensible default question, so a missing topic
is refused rather than answered with whichever one was listed first.

Two details that bite if you write your own:

- **An optional input property is always passed, as an empty string.** A Python
  default in the handler signature is dead code. This handler drops the empty
  ones and lets each pydantic field's own default apply.
- **Nothing enforces `output:`.** It is documentation for the next author. What
  the model sees is whatever the handler actually returned, so the handler is
  the contract.

## Files

| File | What is in it |
|---|---|
| `agent.yaml` | one agent, one tool, the models, the greeting |
| `targets.yaml` | both code targets, no `connection:`, which is what makes it browser only |
| `instructions.md` | the whole call: the three kinds of call, the check, and how to speak |
| `tools/support_desk.yaml` | one tool, three actions, the full contract |
| `tools/support_desk.py` | the fake accounts, the answers, the routing rule and a `_demo()` self-check |
| `tools/end_call.yaml` | the prebuilt hang-up |

## Wiring it to a real system

One file changes: `tools/support_desk.py`.

- `_ACCOUNTS` becomes a read against your CRM or billing system.
- `_ANSWERS` becomes a read against wherever your policies already live. If they
  live in documents rather than in a table, use a `knowledge:` tool instead and
  let the agent search them.
- `_state.tickets` becomes a write to your ticketing system.

Keep the returns exactly as they are and nothing else in the package moves,
because the prompt and the tool contract both sit above that file.

If your systems already have an HTTP API, a `webhook:` tool is less code than a
handler. You would then need one tool per endpoint, since a webhook tool posts
to one path, which is the trade-off the section above describes from the other
side.

## What it does not do

**It cannot put anybody through to a person.** That is an `escalations:` entry,
and a transfer needs a phone route to transfer to, so a browser package cannot
have one. This line raises a ticket and promises a callback instead. For the
real thing, read [transfers](https://unmute.ai/build/transfers) and
[`multi-agent-handoff`](../multi-agent-handoff/), which has a phone number.

There is also no task, no second agent, no knowledge base and no tracing. For
steps in a fixed order, read [`dispute-intake`](../dispute-intake/). For saving
what a caller says into typed variables, read [`tasks`](../tasks/).

The identity check here is two things printed on a bill. It is the shape of a
real check, not a strong one. A real line adds something only the customer
knows, or sends a code to the number on the account.

## Troubleshooting

### It stops at startup and says an environment variable is missing

Both names under `secrets:` have to hold a value before the first turn. The
check runs before the agent answers rather than at the first tool call, so a
missing one is a session that never starts.

**Fix:** fill in every line of the generated `.env.example`.

```sh
unmute compile customer-service
cp customer-service/build/pipecat/.env.example .env
```

### It will not tell me anything about my account

The check needs the account number and the postcode to match the same account.
One right and one wrong comes back exactly like two wrong, on purpose, so the
agent has nothing to tell you about which half was wrong.

**Fix:** use a pair from [Quickstart](#quickstart), or add your own to
`_ACCOUNTS` in `tools/support_desk.py`.

### It answered a question from memory instead of looking it up

That is the failure this package is built to avoid, so check the tool first: a
question outside the six topics has no answer to find, and the agent is left
with nothing but what it knows.

**Fix:** add the topic. That is one entry in `_ANSWERS` in
`tools/support_desk.py` **and** one `enum` value in `tools/support_desk.yaml`.
Both, or the model cannot ask for it.

### `status: rejected` came back and the turn went round again

That is the pydantic model doing its job. `action` takes one of three words,
`topic` one of six and `category` one of six, and anything else is refused with
the reason as a tool result.

**Fix:** read the refusal. The model corrects itself on the next turn. To change
what is accepted, change the `Literal` in `tools/support_desk.py` **and** the
`enum` in `tools/support_desk.yaml`.

### The ticket went to the wrong team

Routing is a dictionary in `tools/support_desk.py`, not something the model
decides. If a ticket lands in the wrong place, the model picked the wrong
`category`.

**Fix:** sharpen the six descriptions in `tools/support_desk.yaml`, which is
what the model reads when it chooses. Do not add routing rules to the prompt.

### The agent reads the account number back too fast to write down

The prompt says to put a space between the characters, which is what makes a
voice say them one at a time. If a reference still comes out as one word, the
model wrote it the way it is stored.

**Fix:** none in the package, and do not add a second rule saying the same
thing. Read the transcript: the fix is usually one clearer sentence in
`instructions.md`, not another one.

## Where to go next

- [`single-prompt`](../single-prompt/) - the same plain shape, with a separate tool for every job
- [`dispute-intake`](../dispute-intake/) - when the order of the call has to hold
- [All templates](../README.md) - what each one is for
- [Python tools](https://unmute.ai/build/tools/python) - the `local:` block this package uses
- [Transfers](https://unmute.ai/build/transfers) - putting a caller through to a person
