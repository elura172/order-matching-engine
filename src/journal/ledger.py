"""Append-only audit ledger with cryptographic SHA-256 state root verification."""

import hashlib
import json
import time
from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel


def _json_serial(obj: Any) -> Any:
    """JSON serializer for Decimal and other non-standard types."""
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


class JournalEntry(BaseModel):
    sequence_num: int
    event_type: str
    timestamp_ns: int
    payload: dict[str, Any]
    prev_hash: str
    state_hash: str


class AuditLedger:
    """Cryptographic tamper-evident journal recording all exchange state transitions."""

    GENESIS_HASH: str = "0000000000000000000000000000000000000000000000000000000000000000"

    def __init__(self) -> None:
        self.entries: list[JournalEntry] = []
        self._current_hash: str = self.GENESIS_HASH

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        sequence_num: int,
        timestamp_ns: Optional[int] = None,
    ) -> JournalEntry:
        """Append an event to the ledger and update the rolling cryptographic state hash."""
        ts = timestamp_ns if timestamp_ns is not None else time.time_ns()
        prev = self._current_hash

        canonical_payload = json.dumps(payload, sort_keys=True, default=_json_serial)
        hasher = hashlib.sha256()
        hasher.update(prev.encode("utf-8"))
        hasher.update(str(sequence_num).encode("utf-8"))
        hasher.update(event_type.encode("utf-8"))
        hasher.update(canonical_payload.encode("utf-8"))
        state_hash = hasher.hexdigest()

        entry = JournalEntry(
            sequence_num=sequence_num,
            event_type=event_type,
            timestamp_ns=ts,
            payload=payload,
            prev_hash=prev,
            state_hash=state_hash,
        )

        self.entries.append(entry)
        self._current_hash = state_hash
        return entry

    @property
    def state_root(self) -> str:
        return self._current_hash

    def verify_chain_integrity(self) -> bool:
        """Verify the full mathematical chain of hashes from genesis to latest state root."""
        expected_prev = self.GENESIS_HASH
        for entry in self.entries:
            if entry.prev_hash != expected_prev:
                return False

            canonical_payload = json.dumps(entry.payload, sort_keys=True, default=_json_serial)
            hasher = hashlib.sha256()
            hasher.update(entry.prev_hash.encode("utf-8"))
            hasher.update(str(entry.sequence_num).encode("utf-8"))
            hasher.update(entry.event_type.encode("utf-8"))
            hasher.update(canonical_payload.encode("utf-8"))
            calculated_hash = hasher.hexdigest()

            if calculated_hash != entry.state_hash:
                return False

            expected_prev = entry.state_hash

        return True
