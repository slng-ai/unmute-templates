# dispute-intake

A billing desk that takes an invoice dispute over the phone. It finds the
invoice, writes down exactly what is wrong with it, and opens a case routed to
the team that owns that kind of problem.

This is the small package for one question: **how do I make a call happen in a
fixed order?** The two steps run as a task group, so the dispute is always taken
against an invoice somebody looked up. No prompt asks for that order. It cannot
happen any other way.

It is also the package to read for **one tool with several actions**. There is
one tool file here, `dispute_desk`, and it does three things picked by an
`action` argument. See [One tool, three actions](#one-tool-three-actions) for
what that buys and what it costs.

No phone route and no carrier account. Browser audio on both code targets. It
needs `GOOGLE_API_KEY` and `SLNG_API_KEY`, and nothing else.

On this page:

- [Quickstart](#quickstart) - validate, run, check
- [The call](#the-call) - what it sounds like
- [What it collects](#what-it-collects) - every field, and where it goes
- [The two steps](#the-two-steps) - the task group
- [One tool, three actions](#one-tool-three-actions) - the shape and its cost
- [Files](#files) - what each file holds
- [Wiring it to a real system](#wiring-it-to-a-real-system) - the one file to change
- [What it does not do](#what-it-does-not-do) - and where to look
- [Troubleshooting](#troubleshooting) - when something goes wrong
- [Where to go next](#where-to-go-next) - packages and pages

## Quickstart

```sh
unmute validate dispute-intake
unmute compile dispute-intake
cp dispute-intake/build/pipecat/.env.example .env   # then fill it in
unmute dev dispute-intake --target pipecat
```

Both keys are required and the agent will not start while one is empty.

The ledger is fake and lives in `tools/dispute_desk.py`. Three invoices, and
these are the numbers to say out loud when you test it:

| Invoice | Account | Amount | State |
|---|---|---|---|
| `INV-10428` | Harbour Foods | 4,300 EUR | overdue |
| `INV-10517` | Harbour Foods | 1,180.50 EUR | open |
| `INV-10386` | Kestrel Logistics | 960 EUR | paid |

Run the tool's own check on its own, without compiling anything:

```sh
uv run --with pydantic python dispute-intake/tools/dispute_desk.py
```

## The call

Roughly how it goes. The agent speaks first.

> **Agent:** Hi, you're through to the billing desk at Northwind Supply. What's
> the trouble with your invoice?
>
> **Caller:** You've billed us twice for the same delivery.
>
> **Agent:** Ah, right. Have you got the invoice number in front of you?
>
> **Caller:** Yeah, it's I N V one zero four two eight.
>
> **Agent:** Okay, so that's invoice I N V dash one zero four two eight, 4,300
> euros, due on the 13th of September. Is that the one?
>
> **Caller:** That's it.
>
> **Agent:** Right, let me take the details down. Is the whole 4,300 in dispute,
> or part of it?

From there it takes the amount, whether the rest of the invoice still gets paid,
who is calling, and what they can send. Then it logs the case and reads the
reference back once.

## What it collects

Every value has a declared type, so a value the model gets wrong is refused
where it enters and never reaches the case.

| Value | Type | Where it comes from |
|---|---|---|
| `invoice` | the `Invoice` shape | the lookup, once the caller agrees it is the right one |
| `invoice_number` | `Id` | picked off `invoice` with a dotted assign |
| `dispute_case` | the `DisputeCase` shape | the tool's own return, saved with no model turn in between |
| `today_date` | `Date` | read once from the clock before the greeting |

`DisputeCase` is what an AR team gets back from the call:

| Field | Type | Why it is there |
|---|---|---|
| `case_id` | `Id` | the reference read back to the caller |
| `invoice_number` | `Id` | which invoice, taken from the lookup and not from the model |
| `reason` | `Literal[...]`, eight values | the dispute category, and what the routing is decided from |
| `disputed_amount` | `float` | how much is held, capped at the invoice total |
| `rest_will_be_paid` | `bool` | the question collections cares about most |
| `raised_by` | `str` | who to ring back |
| `evidence` | `list[str]` | what the caller offered to send |
| `routed_to` | `Literal[...]`, four teams | worked out from `reason` by the tool |
| `opened_on` | `Date` | stamped by the tool in the desk's own timezone |

The routing is the only real decision in this package, and it is a dictionary:

| Reason | Goes to |
|---|---|
| `pricing`, `service_quality` | sales |
| `quantity`, `goods_not_received` | logistics |
| `tax_or_vat` | tax |
| `duplicate_invoice`, `wrong_po_number`, `other` | billing |

## The two steps

```yaml
task_groups:
  intake:
    when: The caller says something is wrong with an invoice ...
    steps:
      - confirm_invoice
      - record_dispute
    context_scope: shared
    then: return
```

Neither step has a `when:` of its own. The group is their only trigger, so the
order is not something the model chooses.

`context_scope: shared` means the second step can see what the caller already
said in the first one. That is the point: a caller who opens with "you've billed
me twice" has already given the reason, and the second step's prompt says to use
it rather than asking again.

`record_dispute` ends on its tool:

```yaml
finish:
  - tool: dispute_desk
    success:
      - status: recorded
```

A result carrying `status: recorded` saves the case and ends the step with no
model request in between. Without it, the model would spend a whole turn
deciding something the tool had already decided. It is also why the step does
not read the reference back: it is over the moment the case is written, so the
agent reads the reference out after the group returns. Both prompts say which
one of them speaks, because that is the usual way a caller hears the same thing
twice.

## One tool, three actions

`dispute_desk` takes an `action` argument with three values:

| Action | What it does |
|---|---|
| `look_up_invoice` | one invoice by number |
| `list_open_invoices` | what is open on an account, for a caller with no number |
| `log_dispute` | writes the case and picks the team |

**What it buys.** One file, one description, one argument list to keep true. The
model reads one tool instead of three and is far less likely to pick the wrong
one, because there is only one to pick. Adding a fourth action is one `enum`
value and one branch.

**What it costs, and it is worth knowing before you copy this.** A tool list is
Unmute's access control: a step holds the tools it may call, so a tool that is
not on the step cannot be called at all. With one tool doing everything, both
steps hold it, and nothing stops the first step from calling `log_dispute`
except the prompt asking it not to. Three separate tools would make that
impossible rather than discouraged.

So the rule of thumb: one tool with actions when the actions belong to the same
job and the same people, separate tools when a step must be unable to reach one
of them. Here the whole call is one job, so one tool is right. If this desk also
issued credit notes, that would be a separate tool on a separate step.

The same thing decides the `inject:` question. Nothing is injected here, and
that is deliberate: an injected value is guarded, so injecting the confirmed
invoice number would make the lookup refuse itself before there was anything to
confirm. One tool that runs both before and after a value exists cannot inject
that value. [`tasks`](../tasks/) shows the other case, where a tool runs only
after and injects four values the model never sees.

## Pydantic, and nothing else

`tools/dispute_desk.py` checks its arguments with a plain `BaseModel`:

```python
class DisputeArgs(BaseModel):
    action: Literal["look_up_invoice", "list_open_invoices", "log_dispute"]
    invoice_number: str = ""
    reason: Literal["pricing", "quantity", ...] = "other"
    disputed_amount: float = 0.0
    rest_will_be_paid: bool = False
    ...
```

No validators, no config, no custom types. Fields, `Literal`s, lists and
defaults do all of it, and pydantic turns the strings a model sends into the
float and the bool the case needs. A value outside a `Literal` comes back to the
model as a sentence it can correct itself from, in a result rather than an
exception, so a wrong word costs one turn instead of a broken call.

Two details that bite if you write your own:

- **An optional input property is always passed, as an empty string.** A Python
  default in the handler signature is dead code. This handler drops the empty
  ones and lets each pydantic field's own default apply.
- **`output:` on the tool file has to spell out a nested object property by
  property** when a step assigns it with `finish:`. The compiler checks the tool
  and the shape agree before it compiles, and a bare `type: object` fails with
  the field it could not match.

## Files

| File | What is in it |
|---|---|
| `agent.yaml` | one agent, two steps, the task group, the shapes and the variables |
| `targets.yaml` | both code targets, no `connection:`, which is what makes it browser only |
| `instructions.md` | the agent's prompt; it reads the case reference back and nothing else does |
| `tasks/confirm-invoice.md` | find the invoice and get the caller to agree to it |
| `tasks/record-dispute.md` | take the five things and log the case |
| `tools/dispute_desk.yaml` | one tool, three actions, the full output contract |
| `tools/dispute_desk.py` | the fake ledger, the routing rule and a `_demo()` self-check |
| `tools/end_call.yaml` | the prebuilt hang-up |

## Wiring it to a real system

One file changes: `tools/dispute_desk.py`. Replace `_LEDGER` with a read against
your ERP and `_state.cases` with a write to your CRM. Keep the return shapes as
they are and nothing else in the package moves, because the call flow, the types
and the prompts all sit above that file.

If your ERP already has an HTTP API, a `webhook:` tool is less code than a
handler. You would then need one tool per endpoint, since a webhook tool posts
to one path, which is the trade-off the section above describes from the other
side.

## What it does not do

No phone number, no transfer, no second agent, no knowledge base and no tracing.
For a phone route and two agents, read
[`multi-agent-handoff`](../multi-agent-handoff/). For the same typed collection
without a task group, read [`tasks`](../tasks/). For no structure at all, read
[`single-prompt`](../single-prompt/).

It also does not verify who is calling. A real AR line would, and the shape for
that is a third step in front of these two, or the `confirm:` guard
[`tasks`](../tasks/) uses on the caller's phone number.

Task groups and declared types are both refused on the `slng` target, which runs
no code of yours and so has nowhere to check one. That is why this package names
only the two code targets.

## Troubleshooting

### It stops at startup and says an environment variable is missing

Both names under `secrets:` have to hold a value before the first turn. The
check runs before the agent answers rather than at the first tool call, so a
missing one is a session that never starts.

**Fix:** fill in every line of the generated `.env.example`.

```sh
unmute compile dispute-intake
cp dispute-intake/build/pipecat/.env.example .env
```

### The agent cannot find my invoice

The ledger is three fixed invoices. Anything else comes back as not found, and
after two goes the agent stops rather than guessing at a near match.

**Fix:** use one of the numbers in [Quickstart](#quickstart), or add your own to
`_LEDGER` in `tools/dispute_desk.py`.

### The agent asked for the invoice number twice

The first step asks for it, and it is meant to use a number the caller has
already said. If it asks again, check that the caller's number actually reached
the transcript: on a noisy line a spelled-out number often arrives half heard,
and the step is reading a blank rather than ignoring you.

**Fix:** none in the package. Read the transcript before editing the prompt.

### `status: rejected` came back and the turn went round again

That is the pydantic model doing its job. `action` takes one of three words and
`reason` one of eight, and anything else is refused with the reason as a tool
result.

**Fix:** read the refusal. The model corrects itself on the next turn. To change
what is accepted, change the `Literal` in `tools/dispute_desk.py` **and** the
`enum` in `tools/dispute_desk.yaml` **and** the shape field in `agent.yaml`. All
three describe the same set and the compiler checks they agree.

### A compile fails saying the tool has to return an object with a property per field

A step that ends on its tool saves the tool's result straight into a shape, so
the tool's `output:` has to describe that object in full, including an `enum`
wherever the shape has a `Literal`.

**Fix:** write out the nested properties in `tools/dispute_desk.yaml`. The error
names the field it could not match.

### The case went to the wrong team

Routing is a dictionary in `tools/dispute_desk.py`, not something the model
decides. If a dispute lands in the wrong place, the model picked the wrong
`reason`.

**Fix:** sharpen the eight descriptions in `tools/dispute_desk.yaml`, which is
what the model reads when it chooses. Do not add routing rules to the prompt.

## Where to go next

- [`tasks`](../tasks/) - the same typed collection, without a task group
- [`multi-agent-handoff`](../multi-agent-handoff/) - a task group inside a full package
- [All templates](../README.md) - what each one is for
- [Orchestration](https://unmute.ai/build/orchestration) - tasks, groups and handoffs
- [Python tools](https://unmute.ai/build/tools/python) - the `local:` block this package uses
