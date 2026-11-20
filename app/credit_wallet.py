"""Durable additive recording-hour wallet for BeOnMeet.

No subscription cycles, expiration or automatic renewal. Amounts are stored in
SECONDS, not floating hours. Credits and debits have unique references for
payment callback / delivery retry idempotency.
"""
from __future__ import annotations

from datetime import datetime, timezone

def create_wallet_schema(db) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS credit_entries (
            reference TEXT PRIMARY KEY,
            telegram_id TEXT NOT NULL,
            seconds_delta BIGINT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_credit_entries_user ON credit_entries(telegram_id);
    """)

def add_entry(db, telegram_id: str, seconds_delta: int, reference: str, kind: str) -> bool:
    delta=int(seconds_delta)
    if not delta or not reference or not str(telegram_id).strip():
        raise ValueError("Invalid wallet transaction")
    if kind not in {"purchase", "migration", "recording", "admin", "refund", "trial"}:
        raise ValueError("Invalid wallet transaction kind")
    row=db.execute("SELECT telegram_id, seconds_delta, kind FROM credit_entries WHERE reference=?", (reference,)).fetchone()
    if row:
        if str(row["telegram_id"])!=str(telegram_id) or int(row["seconds_delta"])!=delta or row["kind"]!=kind:
            raise ValueError("Wallet transaction reference collision")
        return False
    # Unique reference remains a hard invariant under simultaneous callbacks.
    cursor=db.execute(
        """INSERT INTO credit_entries(reference, telegram_id, seconds_delta, kind, created_at)
           VALUES(?,?,?,?,?) ON CONFLICT(reference) DO NOTHING""",
        (reference, str(telegram_id), delta, kind, datetime.now(timezone.utc).isoformat()),
    )
    # Verify the persisted row even under simultaneous callbacks, where a
    # conflicting transaction may have inserted between our check and write.
    stored=db.execute(
        "SELECT telegram_id, seconds_delta, kind FROM credit_entries WHERE reference=?",
        (reference,),
    ).fetchone()
    if not stored or (str(stored["telegram_id"]),int(stored["seconds_delta"]),str(stored["kind"])) != (str(telegram_id),delta,kind):
        raise ValueError("Wallet transaction reference collision")
    return cursor.rowcount == 1

def balance(db, telegram_id: str) -> dict:
    row=db.execute(
        """SELECT COALESCE(SUM(CASE WHEN seconds_delta>0 THEN seconds_delta ELSE 0 END),0) AS credited,
                  COALESCE(SUM(CASE WHEN seconds_delta<0 THEN -seconds_delta ELSE 0 END),0) AS used,
                  COALESCE(SUM(seconds_delta),0) AS net,
                  COALESCE(SUM(CASE WHEN kind='trial' AND seconds_delta>0 THEN seconds_delta ELSE 0 END),0) AS welcome
           FROM credit_entries WHERE telegram_id=?""",
        (str(telegram_id),),
    ).fetchone()
    net=int(row["net"] or 0) if row else 0
    used=int(row["used"] or 0) if row else 0
    welcome=int(row["welcome"] or 0) if row else 0
    total=max(0,net)
    welcome_remaining=min(total,max(0,welcome-used))
    return {
        "remaining_seconds": total,
        "trial_granted_seconds": welcome,
        "trial_remaining_seconds": welcome_remaining,
        "paid_remaining_seconds": total-welcome_remaining,
        "signed_balance_seconds": net,
        "credited_seconds": int(row["credited"] or 0) if row else 0,
        "used_seconds": int(row["used"] or 0) if row else 0,
    }

def has_wallet_history(db, telegram_id: str) -> bool:
    return bool(db.execute("SELECT reference FROM credit_entries WHERE telegram_id=? LIMIT 1",(str(telegram_id),)).fetchone())
