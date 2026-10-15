"""Independent delivery-order reference for recording simulated online decisions.

Unlike historical replay, this implementation knows only deliveries already fed
to ``observe``. It maintains live per-account transaction and state registers;
it does not call the replay engine or read a generator oracle. Feed every delivery
through the decision cutoff before requesting features. Earlier queries require
the historical replay engine, not this forward-only reference.
"""

from __future__ import annotations

from datetime import timedelta

from .schema import ContractError, Cutoff, Event, timestamp


def _effective_key(event: Event) -> tuple[str, str, int]:
    return event.event_time, event.available_at, event.delivery_seq


class OnlineReference:
    """Small, deterministic reference implementation of the live feature contract."""

    def __init__(self) -> None:
        self._watermark: tuple[str, int] | None = None
        self._sequences: set[int] = set()
        self._received: dict[str, Event] = {}
        self._replaced: dict[str, str] = {}
        self._transaction_roots: dict[str, str] = {}
        self._transactions: dict[str, Event] = {}
        self._accounts: dict[str, dict[str, Event]] = {}
        self._registers: dict[tuple[str, str], dict[str, Event]] = {}

    @staticmethod
    def _register_key(event: Event) -> tuple[str, str] | None:
        if event.event_type in {"blocklist", "flag"}:
            return event.event_type, event.payload["account_id"]
        if event.event_type == "outage":
            return "outage", "velocity"
        if event.event_type == "checkpoint":
            return "checkpoint", event.payload["scope"]
        return None

    def _remove(self, event: Event) -> None:
        if event.event_type == "transaction":
            self._transactions.pop(event.transaction_id, None)
            self._accounts[event.payload["account_id"]].pop(event.transaction_id, None)
        key = self._register_key(event)
        if key is not None:
            self._registers[key].pop(event.event_id, None)

    def _insert(self, event: Event) -> None:
        if event.event_type == "transaction":
            self._transactions[event.transaction_id] = event
            self._accounts.setdefault(event.payload["account_id"], {})[event.transaction_id] = event
        key = self._register_key(event)
        if key is not None:
            self._registers.setdefault(key, {})[event.event_id] = event
        # Outcome identities remain auditable, but have no feature register.

    def observe(self, event: Event) -> None:
        """Receive one validated immutable delivery in strictly increasing delivery order."""
        if not isinstance(event, Event):
            raise ContractError("OnlineReference.observe requires a validated Event")
        # Reconstruct a private immutable record. This also verifies its payload
        # hash instead of retaining a reference to a caller-owned record.
        received = Event(**event.to_dict())
        if self._watermark is not None and received.delivery_key <= self._watermark:
            raise ContractError(
                "Online deliveries must be strictly ordered by availability and sequence"
            )
        if received.delivery_seq in self._sequences:
            raise ContractError(f"{received.event_id}: reused online delivery sequence")
        existing = self._received.get(received.event_id)
        if existing is not None:
            semantic_fields = (
                "event_type",
                "event_time",
                "transaction_id",
                "source",
                "payload_hash",
                "supersedes",
            )
            if any(
                getattr(existing, field) != getattr(received, field) for field in semantic_fields
            ):
                raise ContractError(f"{received.event_id}: conflicting online event identity")
        elif received.supersedes is not None:
            previous = self._received.get(received.supersedes)
            if previous is None:
                raise ContractError(f"{received.event_id}: correction predecessor has not arrived")
            if (
                previous.event_type != received.event_type
                or previous.transaction_id != received.transaction_id
            ):
                raise ContractError(
                    f"{received.event_id}: correction changes event type or transaction identity"
                )
            if previous.event_id in self._replaced:
                raise ContractError(
                    f"{received.event_id}: correction branches from an already replaced event"
                )
        elif (
            received.event_type == "transaction"
            and received.transaction_id in self._transaction_roots
        ):
            raise ContractError(f"{received.transaction_id}: multiple online transaction roots")

        self._sequences.add(received.delivery_seq)
        self._watermark = received.delivery_key
        if existing is not None:
            return  # A duplicate delivery never resurrects a superseded identity.
        self._received[received.event_id] = received
        if received.supersedes is not None:
            self._remove(self._received[received.supersedes])
            self._replaced[received.supersedes] = received.event_id
        elif received.event_type == "transaction":
            self._transaction_roots[received.transaction_id] = received.event_id
        self._insert(received)

    def _latest(self, kind: str, subject: str) -> Event | None:
        return max(
            self._registers.get((kind, subject), {}).values(), key=_effective_key, default=None
        )

    def _check_completeness(self, window_start, account: str) -> None:
        for scope in ("blocklist", "flags"):
            markers = list(self._registers.get(("checkpoint", scope), {}).values())
            latest = max(markers, key=_effective_key, default=None)
            if latest is None or not latest.payload["complete"]:
                raise ContractError(f"Missing historical {scope} state in the online reference")
            gap = max(
                (marker for marker in markers if not marker.payload["complete"]),
                key=_effective_key,
                default=None,
            )
            if gap is not None:
                resumed = min(
                    (
                        marker
                        for marker in markers
                        if marker.payload["complete"]
                        and _effective_key(marker) > _effective_key(gap)
                    ),
                    key=_effective_key,
                )
                kind = "blocklist" if scope == "blocklist" else "flag"
                state = self._latest(kind, account)
                if state is None or _effective_key(state) <= _effective_key(resumed):
                    raise ContractError(
                        f"Missing historical {scope} state for account {account}: "
                        "coverage resumed without a subsequent effective account state"
                    )
        checkpoints = list(self._registers.get(("checkpoint", "velocity"), {}).values())
        last_gap = max(
            (_effective_key(event) for event in checkpoints if not event.payload["complete"]),
            default=None,
        )
        covered = [
            event
            for event in checkpoints
            if event.payload["complete"] and (last_gap is None or _effective_key(event) > last_gap)
        ]
        origin = min(covered, key=_effective_key, default=None)
        if origin is None:
            raise ContractError("Missing historical velocity state in the online reference")
        if timestamp(origin.event_time) > window_start:
            raise ContractError(
                "Missing online velocity history: complete coverage starts inside the window"
            )

    def features(
        self, transaction_id: str, cutoff: Cutoff, window_seconds: int = 3600
    ) -> dict[str, float]:
        """Read six scalar features from received state at a nonhistorical cutoff.

        Velocity includes distinct other transactions with event time in
        ``(cutoff - window_seconds, cutoff]``. A recorded outage returns -1 for
        both velocity values. Missing state is an error, never an empty list.
        """
        if type(window_seconds) is not int or window_seconds <= 0:
            raise ContractError("Online velocity window_seconds must be a positive integer")
        if self._watermark is not None and cutoff.key < self._watermark:
            raise ContractError(
                "OnlineReference cannot read behind its received delivery watermark"
            )
        current = self._transactions.get(transaction_id)
        if current is None or current.delivery_key > cutoff.key:
            raise ContractError(
                f"Transaction {transaction_id} has not arrived in the online reference"
            )
        end = timestamp(cutoff.time)
        start = end - timedelta(seconds=window_seconds)
        account = current.payload["account_id"]
        self._check_completeness(start, account)
        blocked = self._latest("blocklist", account)
        flagged = self._latest("flag", account)
        outage = self._latest("outage", "velocity")
        unavailable = bool(outage is not None and outage.payload["active"])
        transactions = [
            event
            for key, event in self._accounts.get(account, {}).items()
            if key != transaction_id and start < timestamp(event.event_time) <= end
        ]
        # Define addition order explicitly for identical currency rounding, even
        # when older events arrive after newer ones.
        transactions.sort(key=_effective_key)
        return {
            "amount": float(current.payload["amount"]),
            "velocity_1h": -1.0 if unavailable else float(len(transactions)),
            "velocity_amount_1h": -1.0
            if unavailable
            else round(sum(event.payload["amount"] for event in transactions), 2),
            "blocked": float(bool(blocked is not None and blocked.payload["blocked"])),
            "flagged": float(bool(flagged is not None and flagged.payload["flagged"])),
            "outage": float(unavailable),
        }
