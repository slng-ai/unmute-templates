# order-to-cash

An accounts receivable line. The agent rings the customer's accounts payable
desk, confirms it is through to the right company, says what is open, gets a date
for the money, and hands over to billing when the caller queries a charge.

Order to cash teams make the same call all day: the invoice is coming up, the
invoice is late, what is this line for, when is it going out. Every one of them
ends in the same two things, a date or a dispute, and both have to land in the
ledger the same way every time. So this is the package to read when the work is
high volume and the value is in the structured record at the end, not in the
conversation.

Everything here is fictional. The sales ledger is three made-up customers and six
made-up invoices in memory, and no money moves.

On this page:

- [Quickstart](#quickstart) - validate, compile, talk
- [What you need](#what-you-need) - the values in `.env`
- [Structure](#structure) - what each path holds
- [The two agents and their tasks](#the-two-agents-and-their-tasks) - who does what
- [The chase flow](#the-chase-flow) - one group, two steps
- [Four tools, not fourteen](#four-tools-not-fourteen) - one action argument each
- [Which call is this](#which-call-is-this) - pre-due and overdue, from the data
- [Knowing who you are talking to](#knowing-who-you-are-talking-to) - the confirm gate
- [Rules that live in the backend](#rules-that-live-in-the-backend) - what a prompt cannot hold
- [What the call writes back](#what-the-call-writes-back) - the record you keep
- [Try it](#try-it) - six conversations worth having
- [Troubleshooting](#troubleshooting) - what goes wrong
- [Where to go next](#where-to-go-next)

## Quickstart

```sh
unmute validate order-to-cash
unmute compile order-to-cash
```

The generated projects land in `build/livekit/` and `build/pipecat/`. Each one
carries its own `README.md`, which is the deployment runbook. Do not commit
`build/`, it is disposable.

Talk to it in the browser:

```sh
cp order-to-cash/build/pipecat/.env.example order-to-cash/.env
unmute dev order-to-cash --target pipecat
```

Use `--target livekit` for the same conversation on the other target. Use
headphones, or the agent hears its own voice and interrupts itself.

To get past verification, use one of the three fictional customers. The second
number is the check: say any invoice on that account.

| Customer | Company | Invoices | Open | Past due |
|---|---|---|---|---|
| `CU-4821` | Harborline Foods | `INV-88120`, `INV-88604`, `INV-89011` | 4530 pounds | 2220 pounds, oldest 27 days |
| `CU-5390` | Delta Print Works | `INV-87744`, `INV-89250` | 5115 pounds | 4500 pounds, oldest 78 days |
| `CU-6107` | Calder Logistics | `INV-89402` | 3120 pounds | nothing yet |

Say the numbers however you like. "C U four eight two one", "cu 4821" and just
"4821" all reach the same account, and the same goes for invoices.

Due dates move with the calendar rather than being fixed, so `CU-6107` is still
the courtesy call next year and `INV-87744` is still the old one.

## What you need

Keep every value in `.env`. No credential belongs in the package.

| Name | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini 3.5 Flash-Lite through Google's EU Vertex endpoint; needs `aiplatform.endpoints.predict` access |
| `SLNG_API_KEY` | the voice and the transcription. One key for both |

Two keys, and that is the whole list. There is no tracing provider and no
carrier here: this package is browser audio only. Add
[`tracing:`](https://unmute.ai/build/package) and a
[telephony channel](https://unmute.ai/build/telephony) when you want them.

Everything runs in Europe: `deployment_region` in `targets.yaml`, `world_part` on
the speech models, and `location` on the model. Change those three together to
move the call somewhere else, and change `timezone:` on the `today` pre-fetch
entry with them.

## Structure

| Path | What it holds |
|---|---|
| `agent.yaml` | the package: two agents and the tasks they run, the chase group, handoffs, variables, pre-fetch and secrets |
| `targets.yaml` | the two targets, LiveKit and Pipecat, browser audio on both |
| `instructions.md` | the receivables agent's prompt |
| `agents/billing-specialist.md` | the billing queries prompt |
| `tasks/` | the verification, promise and dispute step prompts |
| `tools/` | four local Python tools over one in-memory sales ledger, plus the `end_call` builtin |

## The two agents and their tasks

**Two agents.** The receivables agent is the one the caller talks to for almost
the whole call. Billing is a second agent because it holds a permission the
receivables agent must not have: opening a dispute puts an invoice on hold and
takes any promise off it. The agent whose job is to get a date should not be able
to do that on its own.

**Three tasks, two of them steps of the chase group.**
Verification confirms the account and the caller's paperwork.
The promise step says where the account stands and records one date.
Billing records disputes in its own task and appends typed `Dispute` values.

**One agent verifies.** `verify_contact` is on the receivables agent and nowhere
else. A task within reach beats a prompt rule, so the task is not listed on the
billing specialist, however plainly its prompt says not to verify again. Every
tool that needs the account refuses while it is unconfirmed, so the gate is still
there, and `to_receivables` is the way back to the agent that verifies.

**Reading is not a task.** Explaining a statement collects nothing and saves
nothing, so it has no task and no finish contract. `manage_invoices` sits on both
agents directly and the prompt does the rest. A task with no data to gather is
scaffolding.

## The chase flow

**One flow, two steps, no request between them.** `chase` is a task group:
verification, then the promise. The receivables agent calls it once and does not
choose between the two steps. Verification carries
`skip_when_confirmed: account_reference`, so a second promise on the same call
goes straight to the promise step; a caller who corrects their customer number
gets verification again, because entering that step withdraws the confirmation it
made.

**All three steps end on their own tools.** `verify_contact` names its check
under `finish:`, `secure_promise` names a recorded promise, and `intake_dispute`
names an opened dispute. When one of those returns a result the package calls a
success, the step saves its `assign:` from that result and hands over, with no
model request in between and without the result reaching the model. A
`not_confirmed` or an `invalid_date` goes back to the model and the step stays
open.

Each of those tools returns the record it saved, whole, on success, which is why
the step's `assign:` needs no model in the middle and why the model can never
retype an ID it was handed.

## Four tools, not fourteen

`manage_invoices` takes an `action` of `list`, `detail` or `send_copy`.
`manage_promise` takes `promise`, `cancel` or `list`. `manage_dispute` takes
`open` or `list`. That is four tools where a first draft of this pack has
fourteen, and it is the shape to copy. The model picks a value from an enum
instead of picking between fourteen tool names that all sound alike, the
arguments are declared once, and the rules that decide whether an action is
allowed sit next to each other in one function rather than drifting apart across
fourteen files.

Four is where it stops, and each reason is worth knowing:

- **`verify_billing_contact` cannot join them.** The other three carry
  `inject: account_reference`, and an injected value the caller has not confirmed
  makes the tool refuse itself. Verification is what produces that confirmation,
  so a tool that did both could never run.
- **`manage_promise` and `manage_dispute` cannot join either.** They live on
  different agents, and the tool list is the permission. Merge them and the
  agent chasing the invoice can put it on hold instead.
- **`manage_invoices` stays separate because it is the read.** It needs no
  agreement from the caller, it is on both agents, and it is the one tool in the
  package that cannot change anything. Folding a read that always runs into a
  write that needs a yes is how a confirmation flag ends up being sent `true` out
  of habit.

Every result is a pydantic `BaseModel` with plain fields, literals and lists, and
no validators. The rules that decide whether a promise is legal are written as
`if` statements in the function, where they read like the credit policy they are.

## Which call is this

The same agent makes the reminder before the due date and the follow-up after it,
and nothing in the package switches between them. The data does.
`overdue_amount` comes back from verification: zero means nothing is late yet, so
the prompt opens with the invoice coming up and asks whether it is in the next
run. Anything else means it opens with how much is late and how old it is.

That is worth copying. Two prompts that differ by one sentence drift apart within
a month, and a caller who is two days late and a caller who is eighty days late
are not two agents.

## Knowing who you are talking to

A company's invoices, amounts and due dates are its business. Reading them to
whoever picked up the phone is a disclosure, so the rule here is the same as a
consumer line even though nobody is embarrassed: **nothing about the account is
said out loud until the caller has shown they hold the paperwork.**

Three places, not one prompt rule:

1. **The greeting says the company and nothing else.** Ashgrove is calling about
   an account. No invoice number, no amount, no word about it being late. Naming
   your own company to another business is normal; naming their balance is not.
2. **`account_reference` carries `confirm: verify_contact`.** Until that step has
   heard the caller agree, the value renders in no prompt but that step's own,
   refused at compile time everywhere else. The receivables agent's prompt
   genuinely does not hold it, so there is nothing for the model to read out.
3. **Every tool that injects it refuses itself** while it is unconfirmed, by
   name, and the model is told which step supplies it.

The second factor is an invoice number rather than a password, because that is
what a business call actually has: only somebody sitting in front of the account
can read one out. `total_outstanding` and `overdue_amount` are assigned by the
verification step, so before it runs they are empty and every prompt that names
them reads whole without them.

## Rules that live in the backend

Rules the prompt states and the ledger enforces, because a prompt rule alone is a
request:

- **One promise at a time.** A second is refused with `has_promise` while the
  account already holds one, and the refusal hands back what is there so the
  agent can say what it is. Without this, a caller saying "actually make it the
  30th" ends up with two dates and a model that says both are agreed.
- **A promise lands after today and within 60 days.** A date in the past, today,
  or four months out is refused. On a call that crosses midnight the ledger and
  the prompt read the same clock, in the seller's own timezone rather than the
  container's UTC.
- **An invoice on hold cannot be promised.** Naming one is refused with
  `invoice_disputed`, and it drops out of what a whole-account promise can cover.
- **Opening a dispute takes off a promise made against that invoice**, and says
  so in `promise_cancelled` so the agent can mention it once. Nobody should be
  chased on a date they agreed for an invoice that is now on hold.
- **A dispute credits nothing.** The invoice stays on the account at its full
  amount.
- **An unknown reason code is filed as `other`.** A code the model invented is
  still a real dispute, and losing it to a validation error is worse than putting
  it in the bucket a human reads anyway.

## What the call writes back

Two typed records, and they are the point of the call:

- `Promise`: which invoice or the whole account, the amount, the date, and how
  they are paying. This is the row a dunning run reads tomorrow.
- `Dispute`: which invoice, a reason code out of seven, one sentence in the
  caller's own words, and how much of the invoice is challenged. The code is what
  routes it; the sentence is what the person reading it needs.

Both are `shapes:` in `agent.yaml` and pydantic models in `tools/receivables.py`,
which is two copies of one fact. Change them together. Point the handler at a
real ERP and the rest of the package does not move.

## Try it

Six conversations worth having before you trust it, one per thing that can go
wrong:

1. **Wrong person.** Say you are not the one who pays invoices. It should ask for
   the right person or a callback time, without saying what is owed.
2. **The follow-up.** Verify with `CU-4821` and `INV-88120`, then say the payment
   run goes out on Friday. It should land one promise on a real date.
3. **The courtesy call.** Verify with `CU-6107` and `INV-89402`. Nothing is late,
   so it should not sound like it is chasing you.
4. **What is this line?** Verify with `CU-5390` and `INV-87744`, then ask what
   the invoice is made up of. It should read the lines, not open a dispute.
5. **Then dispute it.** From there, say the fuel surcharge was never agreed. It
   should record a pricing dispute for 450 pounds and say the invoice is on hold.
6. **Dispute what you promised.** Agree a date for `INV-88120` first, then
   dispute that same invoice. It should say the promise has come off.

Run the ledger's own check without the agent:

```sh
uv run --with pydantic python3 order-to-cash/tools/receivables.py
```

## Troubleshooting

### It stops at startup and nothing speaks

A value the agent reads at startup is missing from `.env`. This package needs
two: `GOOGLE_API_KEY` for Gemini and `SLNG_API_KEY` for speech.

**Fix:** take the names from the generated example file, fill them in, and run
again.

```sh
cp order-to-cash/build/pipecat/.env.example order-to-cash/.env
unmute dev order-to-cash --target pipecat
```

### The agent talks over itself in the browser

It is hearing its own voice through the speakers and treating it as the caller
interrupting.

**Fix:** use headphones.

### It will not tell me what is outstanding

That is the feature. Nothing about the account is said before the verification
step passes, and no amount is in any prompt until then.

**Fix:** give it a customer number and an invoice number from the same row of the
table in [Quickstart](#quickstart), and agree to the readback.

### It will not take a second date

The account already has a promise on it. The ledger refuses a second one rather
than stacking them.

**Fix:** cancel the existing one first, which the agent can do in the same call.
The ledger's own check shows the rule on its own:

```sh
uv run --with pydantic python3 order-to-cash/tools/receivables.py
```

### A date it worked out is a day off

The ledger and the pre-fetch both read `Europe/London`. If your team is somewhere
else, change the `timezone:` on the `today` pre-fetch entry in `agent.yaml` and
`_SELLER_TIMEZONE` in `tools/receivables.py` together. They are two copies of one
fact, and a call taken near midnight is where they disagree.

## Where to go next

- [`debt-collection`](../debt-collection/) - the same shapes on a consumer line,
  where the caller owes the money themselves and the disclosure rules are harder
- [`multi-agent-handoff`](../multi-agent-handoff/) - the same shapes with
  telephony, tracing, knowledge bases and a manager transfer added
- [`README.md`](../README.md) - every template in this repo
