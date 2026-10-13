# Seat hold engine

Thread-safe in-memory ticket hold engine in Python 3 (standard library only).

## Run the tests
    python -m unittest discover -s . -p "test_*.py" -v

The stress and model tests print their seed. Replay inputs with `SEED=<n> python -m unittest discover -s . -p "test_*.py"`.
Threads still interleave differently each run, so a stress failure may need a few reruns. The model test is fully repeatable.

## Use it
    from hold_engine import HoldEngine, FakeClock
    clock = FakeClock()
    e = HoldEngine(["A1", "A2"], clock=clock)
    h = e.hold("A1", "suraj", 30)
    clock.advance(10)
    e.confirm(h)
    e.seat_status("A1")        # Sold(user='suraj')

API: `hold`, `hold_many`, `confirm`, `release`, `seat_status`. Errors are `HoldError` subclasses.
The clock is any function returning seconds (default `time.monotonic`).

## What works
All 6 rules, atomic `hold_many`, no deadlock on opposite seat order, injectable clock.
Tests: unit tests per rule and rule conflict, a threaded stress test with invariant checks, a randomized comparison against a simple reference model, and a test that runs the stress test against a deliberately broken engine to prove it can fail.

## What doesn't
Everything is in memory in one process, with no persistence. Hold records are never deleted, so memory grows over time. Seats must be given at construction.

Rule conflicts and my choices: DECISIONS.md. Known blind spot: BUGS_I_FEAR.md.
