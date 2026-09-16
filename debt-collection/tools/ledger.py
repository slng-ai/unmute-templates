"""Collections demo tools, backed by one in-process ledger.

Three tools share this file. The compiler copies it once per tool
(`tools/<tool_name>.py`), so a module-level dict would give each tool its own
private ledger and the copies would never see each other's writes. One module
parked in `sys.modules` under a name nothing else uses is the smallest thing
every copy can reach.

Every result is a pydantic `BaseModel` returned as a dict. Plain models: fields,
literals and lists, and no validators. The rules that decide whether a payment is
legal are written out as `if` statements in the functions below, where they read
like the policy they are, rather than hidden in a validator that runs on the way
out.
"""

import sys
import threading
import types
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel

_AGENCY_TIMEZONE = "Europe/London"
_HOLD_DAYS = 30
_MAX_INSTALLMENTS = 12

# The fictional ledger. Balances are whole pounds on purpose: the voice says
# "420 pounds" cleanly, and a demo is not the place to test how a TTS reads
# pence.
_ACCOUNTS = {
    "AC-10023": {
        "name": "Jamie Carter",
        "date_of_birth": "1988-04-17",
        "creditor": "Northwind Energy",
        "balance": 420.0,
        "days_past_due": 34,
    },
    "AC-20117": {
        "name": "Priya Raman",
        "date_of_birth": "1975-11-02",
        "creditor": "Northwind Energy",
        "balance": 1290.0,
        "days_past_due": 91,
    },
    "AC-30542": {
        "name": "Tom Okafor",
        "date_of_birth": "1993-06-25",
        "creditor": "Meridian Card Services",
        "balance": 85.0,
        "days_past_due": 12,
    },
}

_fresh = types.ModuleType("unmute_collections_state")
vars(_fresh).update(
    paid={},
    arrangements={},
    disputes={},
    # ponytail: one lock for the whole ledger. Per-account locks if a real
    # backend ever lands here and throughput matters.
    lock=threading.Lock(),
)
_state = sys.modules.setdefault("unmute_collections_state", _fresh)


class Arrangement(BaseModel):
    arrangement_id: str
    kind: Literal["pay_now", "schedule", "plan"]
    amount: float
    first_payment_date: str
    installments: int


class Dispute(BaseModel):
    dispute_id: str
    reason: str
    amount_disputed: float


class Verification(BaseModel):
    account_reference: str = ""
    status: Literal["verified", "not_found", "mismatch"]
    customer_name: str = ""
    creditor: str = ""
    balance_due: float = 0.0
    minimum_payment: float = 0.0
    days_past_due: int = 0
    summary: str


class PaymentResult(BaseModel):
    status: Literal[
        "paid",
        "scheduled",
        "plan_started",
        "cancelled",
        "listed",
        "not_confirmed",
        "invalid_amount",
        "invalid_date",
        "invalid_installments",
        "has_arrangement",
        "nothing_to_cancel",
        "account_not_found",
    ]
    summary: str
    balance_remaining: float = 0.0
    arrangement: Arrangement | None = None
    arrangements: list[Arrangement] = []


class DisputeResult(BaseModel):
    status: Literal["opened", "listed", "not_confirmed", "invalid_reason", "account_not_found"]
    summary: str
    hold_until: str = ""
    dispute: Dispute | None = None
    disputes: list[Dispute] = []


def _today() -> date:
    """The calendar date every check here runs against, in the agency's own zone.

    Not `date.today()`, which reads the container clock. That clock is UTC, so a
    call taken at 23:30 in London landed on the following day and a payment
    booked for "tomorrow" was refused as being in the past. The zone matches the
    `timezone:` on the `today` prefetch entry in agent.yaml, which is what
    {{current_date}} is read in, so the prompt and the ledger agree about what
    day it is.
    """
    return datetime.now(ZoneInfo(_AGENCY_TIMEZONE)).date()


def _normalize_reference(reference):
    """Digits and letters only, uppercased, and the ledger's one key.

    A caller reads a reference out and the transcript comes back as "ac 10023",
    "AC10023" or "A.C. 10023". All three name one account, so every function here
    normalises its own argument rather than trusting the caller to. Bare digits
    get the AC prefix, because a caller who has the letter part in front of them
    still often reads only the number.
    """
    kept = "".join(character for character in str(reference) if character.isalnum()).upper()
    if kept.isdigit() and kept:
        return "AC-" + kept
    letters, digits = kept[:2], kept[2:]
    if not letters.isalpha() or not digits.isdigit() or not digits:
        return ""
    return letters + "-" + digits


def _money(value):
    """Pounds and pence, or -1 for anything that is not a number at all.

    -1 rather than None so the caller's own `<= 0` check catches a bad value on
    the same line it catches a zero, instead of growing a second branch.
    """
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return -1.0


def _count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_date(text):
    try:
        return date.fromisoformat(str(text).strip())
    except (TypeError, ValueError):
        return None


def _balance(reference):
    """What is left on the account. Call under the lock."""
    return round(_ACCOUNTS[reference]["balance"] - _state.paid.get(reference, 0.0), 2)


def _held(reference):
    """The arrangements on the account. Call under the lock."""
    return [Arrangement(**row) for row in _state.arrangements.get(reference, [])]


def verify_account_holder(account_reference, date_of_birth):
    reference = _normalize_reference(account_reference)
    account = _ACCOUNTS.get(reference)
    if account is None:
        return Verification(
            status="not_found",
            summary="No account matches that reference.",
        ).model_dump(exclude_none=True)

    if str(date_of_birth).strip() != account["date_of_birth"]:
        # The reference is deliberately not returned here. A reference plus a
        # wrong date of birth is somebody who is not the account holder, and
        # nothing about the account goes back to them.
        return Verification(
            status="mismatch",
            summary="The date of birth does not match that account.",
        ).model_dump(exclude_none=True)

    with _state.lock:
        balance = _balance(reference)
    return Verification(
        account_reference=reference,
        status="verified",
        customer_name=account["name"],
        creditor=account["creditor"],
        balance_due=balance,
        minimum_payment=balance if balance <= 20.0 else round(balance * 0.1, 2),
        days_past_due=account["days_past_due"],
        summary="The account holder was verified.",
    ).model_dump(exclude_none=True)


def manage_payment(account_reference, action, amount, first_payment_date, installments, confirmed):
    reference = _normalize_reference(account_reference)
    if reference not in _ACCOUNTS:
        return PaymentResult(
            status="account_not_found",
            summary="That account is not on file.",
        ).model_dump(exclude_none=True)

    with _state.lock:
        balance = _balance(reference)
        held = _held(reference)

    if action == "list":
        return PaymentResult(
            status="listed",
            summary="There is nothing set up on the account." if not held else "The account already has an arrangement.",
            balance_remaining=balance,
            arrangements=held,
        ).model_dump(exclude_none=True)

    if confirmed is not True:
        return PaymentResult(
            status="not_confirmed",
            summary="The caller has not agreed to this yet.",
            balance_remaining=balance,
        ).model_dump(exclude_none=True)

    if action == "cancel":
        if not held:
            return PaymentResult(
                status="nothing_to_cancel",
                summary="There is no arrangement on the account to cancel.",
                balance_remaining=balance,
            ).model_dump(exclude_none=True)
        with _state.lock:
            _state.arrangements.pop(reference, None)
        return PaymentResult(
            status="cancelled",
            summary="The arrangement was cancelled. The balance is unchanged.",
            balance_remaining=balance,
        ).model_dump(exclude_none=True)

    value = _money(amount)
    if value <= 0 or value > balance:
        return PaymentResult(
            status="invalid_amount",
            summary="The amount must be more than zero and no more than the balance outstanding.",
            balance_remaining=balance,
        ).model_dump(exclude_none=True)

    if action == "pay_now":
        with _state.lock:
            _state.paid[reference] = round(_state.paid.get(reference, 0.0) + value, 2)
            remaining = _balance(reference)
        return PaymentResult(
            status="paid",
            summary="The payment was taken.",
            balance_remaining=remaining,
            arrangement=Arrangement(
                arrangement_id="pay_" + uuid4().hex[:12],
                kind="pay_now",
                amount=value,
                first_payment_date=_today().isoformat(),
                installments=1,
            ),
        ).model_dump(exclude_none=True)

    # schedule and plan both book something for later, so an account that
    # already holds one is refused rather than quietly given a second.
    if held:
        return PaymentResult(
            status="has_arrangement",
            summary="The account already has an arrangement. Cancel it before setting up another.",
            balance_remaining=balance,
            arrangements=held,
        ).model_dump(exclude_none=True)

    when = _parse_date(first_payment_date)
    if when is None or when <= _today():
        return PaymentResult(
            status="invalid_date",
            summary="The first payment has to land on a date after today.",
            balance_remaining=balance,
        ).model_dump(exclude_none=True)

    count = 1
    if action == "plan":
        count = _count(installments)
        if count < 2 or count > _MAX_INSTALLMENTS:
            return PaymentResult(
                status="invalid_installments",
                summary="A plan runs over 2 to 12 monthly instalments.",
                balance_remaining=balance,
            ).model_dump(exclude_none=True)

    record = Arrangement(
        arrangement_id=("plan_" if action == "plan" else "sch_") + uuid4().hex[:12],
        kind="plan" if action == "plan" else "schedule",
        amount=value,
        first_payment_date=when.isoformat(),
        installments=count,
    )
    with _state.lock:
        _state.arrangements.setdefault(reference, []).append(record.model_dump())
    monthly = round(value / count, 2)
    return PaymentResult(
        status="plan_started" if action == "plan" else "scheduled",
        summary=(
            "The plan was set up at " + str(monthly) + " pounds a month."
            if action == "plan"
            else "The payment was booked."
        ),
        balance_remaining=balance,
        arrangement=record,
    ).model_dump(exclude_none=True)


def manage_dispute(account_reference, action, reason, amount_disputed, confirmed):
    reference = _normalize_reference(account_reference)
    if reference not in _ACCOUNTS:
        return DisputeResult(
            status="account_not_found",
            summary="That account is not on file.",
        ).model_dump(exclude_none=True)

    with _state.lock:
        balance = _balance(reference)
        held = [Dispute(**row) for row in _state.disputes.get(reference, [])]

    if action == "list":
        return DisputeResult(
            status="listed",
            summary="There is nothing open on the account." if not held else "The account has an open dispute.",
            disputes=held,
        ).model_dump(exclude_none=True)

    if confirmed is not True:
        return DisputeResult(
            status="not_confirmed",
            summary="The caller has not agreed to the summary yet.",
        ).model_dump(exclude_none=True)

    clean_reason = " ".join(str(reason).split())
    if not clean_reason:
        return DisputeResult(
            status="invalid_reason",
            summary="A dispute needs one short sentence saying what is wrong.",
        ).model_dump(exclude_none=True)

    # Zero means the caller is challenging the whole balance, which is the
    # common case and the one a model is least likely to put a number to.
    value = _money(amount_disputed)
    if value <= 0 or value > balance:
        value = balance

    record = Dispute(
        dispute_id="dsp_" + uuid4().hex[:12],
        reason=clean_reason,
        amount_disputed=value,
    )
    with _state.lock:
        _state.disputes.setdefault(reference, []).append(record.model_dump())
    return DisputeResult(
        status="opened",
        summary="The dispute was opened and collection is on hold while it is reviewed.",
        hold_until=(_today() + timedelta(days=_HOLD_DAYS)).isoformat(),
        dispute=record,
    ).model_dump(exclude_none=True)


def _demo():
    import importlib.util
    from concurrent.futures import ThreadPoolExecutor

    assert _normalize_reference("ac 10023") == "AC-10023"
    assert _normalize_reference("A.C.-10023") == "AC-10023"
    assert _normalize_reference("10023") == "AC-10023"
    assert _normalize_reference("") == ""
    assert _normalize_reference("hello") == ""

    assert verify_account_holder("AC-99999", "1988-04-17")["status"] == "not_found"
    wrong = verify_account_holder("AC-10023", "1988-04-18")
    assert wrong["status"] == "mismatch" and wrong["account_reference"] == ""
    assert "customer_name" not in wrong or not wrong["customer_name"]

    verified = verify_account_holder("ac 10023", "1988-04-17")
    assert verified["status"] == "verified"
    assert verified["account_reference"] == "AC-10023"
    assert verified["customer_name"] == "Jamie Carter"
    assert verified["balance_due"] == 420.0
    assert verified["minimum_payment"] == 42.0
    assert verified["days_past_due"] == 34
    account = verified["account_reference"]
    assert verify_account_holder("AC-30542", "1993-06-25")["minimum_payment"] == 8.5

    # Every copy of this module shares one ledger, which is the whole point of
    # the sys.modules entry above.
    spec = importlib.util.spec_from_file_location("collections_copy_two", __file__)
    assert spec is not None and spec.loader is not None
    copy_two = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy_two)
    assert copy_two._state is _state

    assert manage_payment("AC-99999", "list", 0, "", 1, False)["status"] == "account_not_found"
    empty = manage_payment(account, "list", 0, "", 1, False)
    assert empty["status"] == "listed" and empty["arrangements"] == []
    assert empty["balance_remaining"] == 420.0

    assert manage_payment(account, "pay_now", 50, "", 1, False)["status"] == "not_confirmed"
    assert manage_payment(account, "pay_now", 0, "", 1, True)["status"] == "invalid_amount"
    assert manage_payment(account, "pay_now", "lots", "", 1, True)["status"] == "invalid_amount"
    assert manage_payment(account, "pay_now", 999, "", 1, True)["status"] == "invalid_amount"
    assert manage_payment(account, "list", 0, "", 1, False)["balance_remaining"] == 420.0

    taken = manage_payment(account, "pay_now", 20, "", 1, True)
    assert taken["status"] == "paid"
    assert taken["balance_remaining"] == 400.0
    assert taken["arrangement"]["kind"] == "pay_now"
    assert taken["arrangement"]["first_payment_date"] == _today().isoformat()
    # The other copy sees the payment, and verification reads the new balance.
    assert copy_two.verify_account_holder(account, "1988-04-17")["balance_due"] == 400.0

    today = _today()
    past = (today - timedelta(days=1)).isoformat()
    soon = (today + timedelta(days=7)).isoformat()
    assert manage_payment(account, "schedule", 100, past, 1, True)["status"] == "invalid_date"
    assert manage_payment(account, "schedule", 100, "next tuesday", 1, True)["status"] == "invalid_date"
    assert manage_payment(account, "schedule", 100, today.isoformat(), 1, True)["status"] == "invalid_date"

    booked = manage_payment(account, "schedule", 100, soon, 1, True)
    assert booked["status"] == "scheduled"
    assert booked["arrangement"]["first_payment_date"] == soon
    # A booked payment is not a taken one.
    assert booked["balance_remaining"] == 400.0

    # One arrangement at a time, and the refusal hands back what is already there.
    blocked = manage_payment(account, "plan", 400, soon, 4, True)
    assert blocked["status"] == "has_arrangement"
    assert [row["arrangement_id"] for row in blocked["arrangements"]] == [
        booked["arrangement"]["arrangement_id"]
    ]
    # Paying is always allowed, arrangement or not.
    assert manage_payment(account, "pay_now", 10, "", 1, True)["status"] == "paid"

    assert manage_payment(account, "cancel", 0, "", 1, False)["status"] == "not_confirmed"
    assert manage_payment(account, "cancel", 0, "", 1, True)["status"] == "cancelled"
    assert manage_payment(account, "cancel", 0, "", 1, True)["status"] == "nothing_to_cancel"
    assert manage_payment(account, "list", 0, "", 1, False)["arrangements"] == []

    assert manage_payment(account, "plan", 390, soon, 1, True)["status"] == "invalid_installments"
    assert manage_payment(account, "plan", 390, soon, 13, True)["status"] == "invalid_installments"
    plan = manage_payment(account, "plan", 390, soon, 3, True)
    assert plan["status"] == "plan_started"
    assert plan["arrangement"]["installments"] == 3
    assert "130.0 pounds a month" in plan["summary"]

    other = verify_account_holder("AC-20117", "1975-11-02")["account_reference"]
    assert manage_dispute("AC-99999", "open", "Not mine.", 0, True)["status"] == "account_not_found"
    assert manage_dispute(other, "list", "", 0, False)["disputes"] == []
    assert manage_dispute(other, "open", "Not mine.", 0, False)["status"] == "not_confirmed"
    assert manage_dispute(other, "open", "   ", 0, True)["status"] == "invalid_reason"

    opened = manage_dispute(other, "open", "I  closed   this account in March.", 0, True)
    assert opened["status"] == "opened"
    assert opened["dispute"]["reason"] == "I closed this account in March."
    # Zero means the whole outstanding balance.
    assert opened["dispute"]["amount_disputed"] == 1290.0
    assert opened["hold_until"] == (today + timedelta(days=_HOLD_DAYS)).isoformat()
    assert manage_dispute(other, "list", "", 0, False)["status"] == "listed"
    partial = manage_dispute(other, "open", "The late fee is wrong.", 40, True)
    assert partial["dispute"]["amount_disputed"] == 40.0
    assert len(manage_dispute(other, "list", "", 0, False)["disputes"]) == 2
    # A dispute is a record, not a write-off.
    assert manage_payment(other, "list", 0, "", 1, False)["balance_remaining"] == 1290.0

    # Two threads taking a payment at once must not lose one of them.
    third = verify_account_holder("AC-30542", "1993-06-25")["account_reference"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: manage_payment(third, "pay_now", 1, "", 1, True), range(8))
        )
    assert all(row["status"] == "paid" for row in results)
    assert manage_payment(third, "list", 0, "", 1, False)["balance_remaining"] == 77.0

    # A balance small enough that a tenth of it is not worth asking for is
    # quoted whole instead.
    assert manage_payment(third, "pay_now", 62, "", 1, True)["balance_remaining"] == 15.0
    assert verify_account_holder(third, "1993-06-25")["minimum_payment"] == 15.0

    print("collections in-memory check passed")


if __name__ == "__main__":
    _demo()
