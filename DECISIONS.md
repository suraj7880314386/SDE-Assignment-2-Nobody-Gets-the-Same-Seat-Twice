# DECISIONS

Written before the code. These are the places where the spec clashes with itself, and what I picked.

## R3 vs R4 (expired hold can be confirmed, but holds are never extended)
Confirming an expired hold is not an extension. `expires_at` never changes, and once it passes `seat_status` shows FREE, so anyone else can grab the seat. The old holder just keeps the right to confirm until somebody else takes the seat. "Taken" means any other hold was created on that seat, even if that hold was released again afterwards (the seat was up for grabs, so the old hold stays dead).

## R5 vs R4 (retry is idempotent, but no extending)
A retry on a live hold returns the same `hold_id` and ignores the new TTL. The expiry stays as it was.
If the user's own hold has already expired, the retry is a normal new hold: new id, new TTL, and the old id can no longer be confirmed. I did not return the old id with a fresh expiry, because that is an extension.

## R2 vs R5
A retry on a seat the user already holds is not a new hold, so it still works when the user is at 4.

## What counts toward the limit of 4 (R2 vs R3)
Only live holds: not expired, not released, not confirmed. Expired holds don't count, and sold seats don't count either. So a user with 4 live holds can still confirm an old expired one. They end up with 4 holds plus 1 bought seat, not 5 holds.

## R2 vs R6 (hold_many)
- Seats the user already holds are returned as they are and don't count again.
- Duplicate seats in the list collapse into one.
- Limit check = live holds now + distinct new seats <= 4. If it fails, nothing is held.
- One bad seat (sold, held by someone else, unknown) fails the whole call.
- Order of checks: bad ttl, unknown seat, unavailable seat, limit.
- Empty list returns an empty list. One TTL for the whole batch.

## Small things the spec doesn't say
- Expired means `now >= expires_at`.
- TTL must be a positive finite number.
- A sold seat can't be held again, not even by the buyer.
- `confirm` twice on the same hold is ok (flaky network again). `release` twice is ok too.
- `release` on a confirmed hold is an error. Releasing an expired-but-untaken hold works and ends the right to confirm it.
- Errors are exceptions, all subclasses of `HoldError`.
- Expiry is lazy: nothing runs in the background, expiry is worked out from the clock when someone asks.

## Concurrency
- One lock per seat and one lock per user.
- Every operation takes the user lock first, then the seat locks in sorted seat order. That fixed order is why two users asking for overlapping seats in opposite order can't deadlock.
- The user lock is needed because the cap of 4 spans different seats. Per-seat locks alone would let one user pass the check twice at the same time.
- A hold that was taken over by someone else is already expired. The clock only moves forward, so counting a user's live holds without the seat lock can't count a dead one.
- The clock is read after the locks are taken.
