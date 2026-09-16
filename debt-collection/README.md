# debt-collection

A collections line. The agent confirms the account belongs to the person on the
call, says where the balance stands, takes a payment or sets up an arrangement,
and hands over to disputes when the caller says the money is not owed.

Debt collection is one of the biggest categories of voice agent, and it is the
one where getting the structure wrong is expensive. Almost every rule in this
package exists because saying the wrong thing to the wrong person is a
compliance problem, not just a bad call. So this is the package to read when the
thing you are building has to prove who it is talking to before it says
anything at all.

Everything here is fictional. The ledger is three made-up accounts in memory,
and no money moves.

On this page:

- [Quickstart](#quickstart) - validate, compile, talk
- [What you need](#what-you-need) - the values in `.env`
- [Structure](#structure) - what each path holds
- [The two agents and their tasks](#the-two-agents-and-their-tasks) - who does what
- [The payment flow](#the-payment-flow) - one group, two steps
- [Three tools, not eleven](#three-tools-not-eleven) - one action argument each
- [Right party contact, in the schema](#right-party-contact-in-the-schema) - the confirm gate
- [Rules that live in the backend](#rules-that-live-in-the-backend) - what a prompt cannot hold
- [Try it](#try-it) - five conversations worth having
- [Troubleshooting](#troubleshooting) - what goes wrong
- [Where to go next](#where-to-go-next)

## Quickstart

```sh
unmute validate debt-collection
unmute compile debt-collection
```

The generated projects land in `build/livekit/` and `build/pipecat/`. Each one
carries its own `README.md`, which is the deployment runbook. Do not commit
`build/`, it is disposable.

Talk to it in the browser:

```sh
cp debt-collection/build/pipecat/.env.example debt-collection/.env
unmute dev debt-collection --target pipecat
```

Use `--target livekit` for the same conversation on the other target. Use
headphones, or the agent hears its own voice and interrupts itself.

The agent speaks first, and it opens without saying what the call is about. That
is deliberate: see [Right party contact](#right-party-contact-in-the-schema).

To get past verification, use one of the three fictional accounts:

| Reference | Date of birth | Owed | Past due |
|---|---|---|---|
| `AC-10023` | 1988-04-17 | 420 pounds | 34 days |
| `AC-20117` | 1975-11-02 | 1290 pounds | 91 days |
| `AC-30542` | 1993-06-25 | 85 pounds | 12 days |

Say the reference however you like. "A C one oh oh two three", "ac 10023" and
just "10023" all reach the same account.

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

## Structure

| Path | What it holds |
|---|---|
| `agent.yaml` | the package: two agents and the tasks they run, the payment group, handoffs, variables, pre-fetch and secrets |
| `targets.yaml` | the two targets, LiveKit and Pipecat, browser audio on both |
| `instructions.md` | the collections agent's prompt |
| `agents/dispute-specialist.md` | the disputes prompt |
| `tasks/` | the verification, payment and dispute step prompts |
| `tools/` | three local Python tools over one in-memory ledger, plus the `end_call` builtin |

## The two agents and their tasks

**Two agents.** The collections agent is the one the caller talks to for almost
the whole call. Disputes is a second agent because it holds a permission the
collections agent must not have: opening a dispute puts collection on hold, and
the agent whose job is to collect should not be able to do that on its own.

**Three tasks, two of them steps of the payment group.**
Verification confirms the account belongs to the caller.
The payment step does pay now, schedule, plan and cancel in one task and saves a
typed `Arrangement`.
Disputes records disputes in its own task and appends typed `Dispute` values.

**One agent verifies.** `verify_account` is on the collections agent and nowhere
else. A task within reach beats a prompt rule, so the task is not listed on the
dispute specialist, however plainly its prompt says not to verify again. Every
tool that needs the account refuses while it is unconfirmed, so the gate is
still there, and `to_collections` is the way back to the agent that verifies.

**One agent asks for agreement.** The dispute specialist says the summary back
and asks once; `handle_dispute` records what was agreed and asks nothing. Both
asking costs the caller a whole turn to learn nothing.

## The payment flow

**One flow, two steps, no request between them.** `collect` is a task group:
verification, then payment. The collections agent calls it once and does not
choose between the two steps. Verification carries
`skip_when_confirmed: account_reference`, so a second arrangement on the same
call goes straight to the payment step; a caller who corrects their reference
gets verification again, because entering that step withdraws the confirmation
it made.

**All three steps end on their own tools.** `verify_account` names its check
under `finish:`, `arrange_payment` names the three payment results that count as
success, and `handle_dispute` names an opened dispute. When one of those returns
a result the package calls a success, the step saves its `assign:` from that
result and hands over, with no model request in between and without the result
reaching the model. A `not_confirmed` or an `invalid_date` goes back to the model
and the step stays open.

Each of those tools returns the record it saved, whole, on success, which is why
the step's `assign:` needs no model in the middle and why the model can never
retype an ID it was handed.

## Three tools, not eleven

`manage_payment` takes an `action` of `pay_now`, `schedule`, `plan`, `cancel` or
`list`. That is one tool where a first draft has five, and it is the shape to
copy. The model picks a value from an enum instead of picking between five tool
names that all sound alike, the arguments are declared once, and the rules that
decide whether an action is allowed sit next to each other in one function
rather than drifting apart across five files. `manage_dispute` does the same with
`open` and `list`.

Three tools is where it stops, and both reasons are worth knowing:

- **`verify_account_holder` cannot join them.** The other two carry
  `inject: account_reference`, and an injected value the caller has not confirmed
  makes the tool refuse itself. Verification is what produces that confirmation,
  so a tool that does both could never run.
- **`manage_payment` and `manage_dispute` cannot join either.** They live on
  different agents, and the tool list is the permission. Merge them and the
  collections agent can put its own account on hold.

Every result is a pydantic `BaseModel` with plain fields, literals and lists, and
no validators. The rules that decide whether a payment is legal are written as
`if` statements in the function, where they read like the policy they are.

## Right party contact, in the schema

The one rule this whole package is built around: **nothing about the debt is said
out loud to somebody who has not shown the account is theirs.** Saying it to the
wrong person is a disclosure, and it is the single most expensive mistake a
collections agent can make.

A prompt rule is not enough for that, so it is in three places:

1. **The greeting says nothing.** It gives the agency's name and asks whether it
   has the right person. It does not name the creditor, the balance, or the word
   debt.
2. **`account_reference` carries `confirm: verify_account`.** Until that step has
   heard the caller agree, the value renders in no prompt but that step's own,
   refused at compile time everywhere else. The collections agent's prompt
   genuinely does not hold it, so there is nothing for the model to read out.
3. **Every tool that injects it refuses itself** while it is unconfirmed, by
   name, and the model is told which step supplies it.

The balance is the same story from the other end. `balance_due` and
`days_past_due` are assigned by the verification step, so before it runs they are
empty and every prompt that names them reads whole without them.

## Rules that live in the backend

Two rules the prompt states and the ledger enforces, because a prompt rule alone
is a request:

- **One arrangement at a time.** `schedule` and `plan` are refused with
  `has_arrangement` while the account already holds one, and the refusal hands
  back what is there so the agent can say what it is. Paying now is always
  allowed. Without this, a caller saying "actually make it monthly" ends up with
  a one-off payment and a plan, and a model that says both are set up.
- **A first payment lands after today.** A date in the past, or today, is
  refused. On a call that crosses midnight the ledger and the prompt read the
  same clock, in the agency's own timezone rather than the container's UTC.

A dispute changes no balance, which is also enforced rather than promised.

## Try it

Five conversations worth having before you trust it, one per thing that can go
wrong:

1. **Wrong person.** Say you are not the account holder. It should say it will
   call back and end, without mentioning a debt, a balance, or a company name.
2. **The happy path.** Verify with `AC-10023`, ask what you owe, agree to pay the
   whole 420 pounds today.
3. **Cannot pay.** Verify with `AC-20117`, say you are out of work. It should get
   to an instalment plan without being asked and without pushing twice.
4. **Dispute mid-payment.** Start arranging a payment, then say the account was
   closed last year. It should stop asking for money on that turn and move to
   disputes with what you just said.
5. **Pressure.** Ask what happens if you do not pay. It should not threaten
   anything: no court, no bailiffs, no credit file.

Run the ledger's own check without the agent:

```sh
uv run --with pydantic python3 debt-collection/tools/ledger.py
```

## Troubleshooting

### It stops at startup and nothing speaks

A value the agent reads at startup is missing from `.env`. This package needs
two: `GOOGLE_API_KEY` for Gemini and `SLNG_API_KEY` for speech.

**Fix:** take the names from the generated example file, fill them in, and run
again.

```sh
cp debt-collection/build/pipecat/.env.example debt-collection/.env
unmute dev debt-collection --target pipecat
```

### The agent talks over itself in the browser

It is hearing its own voice through the speakers and treating it as the caller
interrupting.

**Fix:** use headphones.

### It will not tell me the balance

That is the feature. Nothing about the account is said before the verification
step passes, and the balance is not in any prompt until then.

**Fix:** give it a reference and the matching date of birth from the table in
[Quickstart](#quickstart), and agree to the readback.

### It will not set up a plan

The account already has an arrangement on it. The ledger refuses a second one
rather than stacking them.

**Fix:** cancel the existing one first, which the agent can do in the same call.
The ledger's own check shows the rule on its own:

```sh
uv run --with pydantic python3 debt-collection/tools/ledger.py
```

### A date it worked out is a day off

The ledger and the pre-fetch both read `Europe/London`. If your agency is
somewhere else, change the `timezone:` on the `today` pre-fetch entry in
`agent.yaml` and `_AGENCY_TIMEZONE` in `tools/ledger.py` together. They are two
copies of one fact, and a call taken near midnight is where they disagree.

## Where to go next

- [`multi-agent-handoff`](../multi-agent-handoff/) - the same shapes with
  telephony, tracing, knowledge bases and a manager transfer added
- [`single-prompt`](../single-prompt/) - what it looks like without any of this
  structure
- [`README.md`](../README.md) - every template in this repo
