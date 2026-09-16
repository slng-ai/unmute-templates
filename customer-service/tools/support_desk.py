"""The support line's one tool: three actions behind one `action` argument.

Everything in here is fake and in process. There is no API, no database and no
network call, so the package runs on its own with nothing but the two model
keys. Wiring it to a real system means replacing the dictionaries at the top
and keeping the returns exactly as they are.

Run the self check on its own, without compiling anything:

    uv run --with pydantic python customer-service/tools/support_desk.py
"""

from __future__ import annotations

import sys
import threading
import types
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ValidationError

try:  # Python 3.9 and up
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - the generated projects are newer
    ZoneInfo = None

# The generated project imports this file as a plain module, and a module can
# end up imported twice under two names. Two copies would mean two ticket
# counters and two tickets called TCK-2001. One module registered by hand, and
# both copies write to the same one.
_fresh = types.ModuleType("unmute_support_state")
vars(_fresh).update(tickets={}, lock=threading.Lock())
_state = sys.modules.setdefault("unmute_support_state", _fresh)

# The desk's own clock. Not the container's, which is UTC and would name the
# wrong day for a caller who is not on it.
_DESK_TIMEZONE = "Europe/London"

# Three accounts, so a demo call has something to find. The postcode is the
# second half of the check: an account number on its own is written on every
# bill, and a bill is the easiest thing in the world to read off somebody's
# kitchen table.
_ACCOUNTS = {
    "BW-40118": {
        "account_number": "BW-40118",
        "customer_name": "Dana Whitlock",
        "postcode": "M4 1HN",
        "plan": "fibre_plus",
        "monthly_price": 42.0,
        "next_bill_on": "2026-10-03",
        "balance": 0.0,
        "service_status": "active",
    },
    "BW-40233": {
        "account_number": "BW-40233",
        "customer_name": "Owen Pryce",
        "postcode": "BS1 5TR",
        "plan": "family",
        "monthly_price": 29.5,
        "next_bill_on": "2026-09-28",
        "balance": 29.5,
        "service_status": "fault_reported",
    },
    "BW-40967": {
        "account_number": "BW-40967",
        "customer_name": "Marta Beck",
        "postcode": "LS9 8AZ",
        "plan": "essential",
        "monthly_price": 21.0,
        "next_bill_on": "2026-10-11",
        "balance": 63.0,
        "service_status": "suspended",
    },
}

# The answers the agent is allowed to give to a general question. They live
# here rather than in the prompt on purpose: a policy that changes is one line
# in one file, and the agent cannot invent a notice period it half remembers.
_ANSWERS = {
    "opening_hours": (
        "The support line is open 8 in the morning until 8 at night, seven days "
        "a week. Engineer visits are booked between 8 and 6, Monday to Saturday."
    ),
    "payment_methods": (
        "Bills are paid by direct debit on the date printed on the bill. A card "
        "payment can be made in the app or on the automated line, and nobody on "
        "this line ever takes card details."
    ),
    "moving_home": (
        "A house move needs two weeks notice. The plan and the price move with "
        "the account, and the line at the new address is usually live on the day "
        "of the move."
    ),
    "cancellation_notice": (
        "Cancelling needs thirty days notice. Nothing is charged after those "
        "thirty days, and the router goes back in a prepaid bag we send out."
    ),
    "router_reset": (
        "Hold the small reset button on the back of the router for ten seconds, "
        "then leave it alone for five minutes while it comes back up. Most drop "
        "outs clear on their own that way."
    ),
    "speed_test": (
        "Run the speed test in the Brightwire app standing next to the router, "
        "then run it again on a cable if you can. We compare both against the "
        "speed the plan is sold at."
    ),
}

# Who picks the ticket up, and how fast. This is the only real decision in the
# package, and it is a dictionary rather than something the model works out, so
# two callers with the same problem always get the same answer.
_ROUTING = {
    "no_service": ("network", "high"),
    "slow_speed": ("network", "normal"),
    "engineer_visit": ("network", "normal"),
    "billing_error": ("billing", "normal"),
    "complaint": ("customer_relations", "high"),
    "other": ("support", "normal"),
}


def _key(text):
    """Letters and digits only, in capitals.

    A caller says "bee double you four oh one one eight" and the transcript
    arrives as "BW40118", "bw-40118" or "BW 40118". A postcode arrives with the
    space in the wrong place about as often as not. Comparing on this makes all
    of those the same string, and it is three lines instead of a parser.
    """
    return "".join(character for character in str(text).upper() if character.isalnum())


_BY_KEY = {_key(number): account for number, account in _ACCOUNTS.items()}


def _match(account_number, postcode):
    """The account, when the number and the postcode both match. Else None.

    One answer for a wrong postcode, an unknown number and a blank, on purpose.
    Three different answers would tell somebody guessing which half they got
    right.
    """
    account = _BY_KEY.get(_key(account_number))
    if account is None or _key(account["postcode"]) != _key(postcode):
        return None
    return account


def _today():
    if ZoneInfo is None:  # pragma: no cover
        return date.today()
    return datetime.now(ZoneInfo(_DESK_TIMEZONE)).date()


def _callback_by(today, priority):
    """The date the team has to have rung back by.

    Working days, not calendar days. A high priority ticket raised on a Friday
    promises Monday, not Saturday, because nobody is there on Saturday and a
    promise the desk cannot keep is worse than a longer one it can.
    """
    left = 1 if priority == "high" else 3
    day = today
    while left:
        day += timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return day


class SupportArgs(BaseModel):
    """What the model is allowed to send.

    A plain model: fields, literals and defaults. No validators and no config.
    The literals do the real work, because a value outside one is refused here
    and never reaches an account or a ticket.
    """

    action: Literal["answer_question", "verify_account", "open_ticket"]
    topic: (
        Literal[
            "opening_hours",
            "payment_methods",
            "moving_home",
            "cancellation_notice",
            "router_reset",
            "speed_test",
        ]
        | None
    ) = None
    account_number: str = ""
    postcode: str = ""
    category: Literal[
        "no_service",
        "slow_speed",
        "billing_error",
        "engineer_visit",
        "complaint",
        "other",
    ] = "other"
    summary: str = ""


def support_desk(
    action,
    topic="",
    account_number="",
    postcode="",
    category="",
    summary="",
):
    """Answer a common question, check who is calling, or raise a ticket."""

    supplied = {
        "action": action,
        "topic": topic,
        "account_number": account_number,
        "postcode": postcode,
        "category": category,
        "summary": summary,
    }

    # An optional input property is always passed, as an empty string, so the
    # defaults in the signature above never fire. Dropping the empty ones here
    # is what lets each pydantic field's own default apply.
    try:
        args = SupportArgs(**{name: value for name, value in supplied.items() if value != ""})
    except ValidationError as refused:
        # A refusal goes back as a result, not an exception. The model reads
        # the sentence, picks a word that exists, and the call carries on one
        # turn later instead of breaking.
        return {"status": "rejected", "problem": refused.errors()[0]["msg"]}

    if args.action == "answer_question":
        if args.topic is None:
            return {"status": "rejected", "problem": "answer_question needs a topic."}
        return {"status": "answered", "answer": _ANSWERS[args.topic]}

    # Both halves, every time. open_ticket checks again rather than trusting
    # that a check happened earlier in the call: the tool is the only thing a
    # prompt cannot be talked around.
    account = _match(args.account_number, args.postcode)
    if account is None:
        return {"status": "not_matched"}

    if args.action == "verify_account":
        return {"status": "verified", "account": dict(account)}

    team, priority = _ROUTING[args.category]
    today = _today()
    with _state.lock:
        ticket_id = "TCK-%d" % (2000 + len(_state.tickets) + 1)
        ticket = {
            "ticket_id": ticket_id,
            "account_number": account["account_number"],
            "category": args.category,
            "summary": args.summary,
            "priority": priority,
            "team": team,
            "raised_on": today.isoformat(),
            "callback_by": _callback_by(today, priority).isoformat(),
        }
        _state.tickets[ticket_id] = ticket
    return {"status": "opened", "ticket": dict(ticket)}


def _demo():
    """One runnable check. It fails if any of the three actions breaks."""

    import re

    # A common question comes back as text the agent reads out.
    answered = support_desk("answer_question", topic="cancellation_notice")
    assert answered["status"] == "answered"
    assert "thirty days" in answered["answer"]

    # A topic nobody wrote an answer for is refused rather than guessed at.
    assert support_desk("answer_question", topic="refunds")["status"] == "rejected"
    assert support_desk("answer_question")["status"] == "rejected"

    # Verification: both halves have to match, however they were said.
    verified = support_desk("verify_account", account_number="bw 40118", postcode="m41hn")
    assert verified["status"] == "verified"
    assert verified["account"]["customer_name"] == "Dana Whitlock"
    assert verified["account"]["plan"] == "fibre_plus"

    # Right number, wrong postcode, and an account that does not exist, both
    # come back the same way and with no account attached.
    wrong = support_desk("verify_account", account_number="BW-40118", postcode="LS9 8AZ")
    assert wrong == {"status": "not_matched"}
    assert support_desk("verify_account", account_number="BW-99999", postcode="M4 1HN") == wrong
    assert support_desk("verify_account") == wrong

    # Escalation: the category decides the team and the speed, not the model.
    complaint = support_desk(
        "open_ticket",
        account_number="BW-40967",
        postcode="LS9 8AZ",
        category="complaint",
        summary="Service was cut off after a payment that had already cleared.",
    )["ticket"]
    assert complaint["team"] == "customer_relations"
    assert complaint["priority"] == "high"

    billing = support_desk(
        "open_ticket",
        account_number="BW-40233",
        postcode="bs15tr",
        category="billing_error",
        summary="Charged twice in August.",
    )["ticket"]
    assert billing["team"] == "billing"
    assert billing["priority"] == "normal"

    # Two tickets, two references, and the shapes the types promise.
    assert complaint["ticket_id"] != billing["ticket_id"]
    assert re.fullmatch(r"TCK-\d{4}", complaint["ticket_id"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", complaint["callback_by"])

    # A callback is never promised for a Saturday or a Sunday.
    for raised in (date(2026, 9, 18), date(2026, 9, 19), date(2026, 9, 20)):
        for speed in ("high", "normal"):
            assert _callback_by(raised, speed).weekday() < 5

    # A ticket is checked the same way a lookup is, so knowing somebody else's
    # account number is not enough to raise one on their line.
    assert support_desk("open_ticket", account_number="BW-40118", postcode="BS1 5TR") == wrong
    assert support_desk("open_ticket", account_number="BW-99999", postcode="M4 1HN") == wrong

    # A word outside a literal never reaches an account or a ticket.
    refused = support_desk("open_ticket", account_number="BW-40118", postcode="M4 1HN", category="vibes")
    assert refused["status"] == "rejected"
    assert support_desk("wipe_account")["status"] == "rejected"

    # A second copy of this module counts tickets with the first one.
    import importlib.util

    spec = importlib.util.spec_from_file_location("support_desk_again", __file__)
    second = importlib.util.module_from_spec(spec)
    sys.modules["support_desk_again"] = second
    spec.loader.exec_module(second)
    again = second.support_desk(
        "open_ticket",
        account_number="BW-40118",
        postcode="M4 1HN",
        category="no_service",
        summary="No connection since last night.",
    )["ticket"]
    assert again["ticket_id"] not in (complaint["ticket_id"], billing["ticket_id"])
    assert again["team"] == "network" and again["priority"] == "high"
    assert len(_state.tickets) == 3

    print("support desk demo ok")


if __name__ == "__main__":
    _demo()
