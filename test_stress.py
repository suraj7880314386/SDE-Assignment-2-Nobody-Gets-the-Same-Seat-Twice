import os, random, sys, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hold_engine import *

SEED = int(os.environ.get("SEED", random.randrange(2 ** 32)))
print("stress seed:", SEED, "(rerun with SEED=%d to replay the same inputs)" % SEED)

SEATS = ["S%d" % i for i in range(6)]
USERS = ["u%d" % i for i in range(5)]


class NullLock:
    def acquire(self, *a, **k): return True
    def release(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


class BrokenEngine(HoldEngine):
    """No locks + a pause between check and write. The stress test must catch this."""
    def __init__(self, *a, **k):
        super().__init__(*a, lock_factory=NullLock, **k)

    def _pause(self):
        time.sleep(0.0002)


def replay(engine, problems):
    for s in SEATS:
        sold, last = False, None
        for kind, hid, user, now, exp in engine.history(s):
            if kind == "hold":
                if sold:
                    problems.append("%s: hold created on sold seat" % s)
                if last is not None and last[2] > now:
                    problems.append("%s: new hold over a live hold" % s)
                last = (hid, user, exp)
            elif kind == "confirm":
                if sold:
                    problems.append("%s: double sale" % s)
                if last is None or last[0] != hid:
                    problems.append("%s: confirmed hold %s that was retaken" % (s, hid))
                sold, last = True, None
            elif kind == "release":
                if last is not None and last[0] == hid:
                    last = None


def run_stress(engine_cls, seed, n_threads=8, ops=1200):
    clock = FakeClock()
    engine = engine_cls(SEATS, clock=clock, record_history=True)
    problems, known = [], []
    lock = threading.Lock()

    def note(msg):
        with lock:
            problems.append(msg)

    def pick_known(rng):
        with lock:
            return rng.choice(known) if known else "h1"

    def worker(i):
        rng = random.Random("%s-%s" % (seed, i))
        try:
            for _ in range(ops):
                user, r = rng.choice(USERS), rng.random()
                try:
                    if r < 0.30:
                        ids = [engine.hold(rng.choice(SEATS), user, rng.randint(1, 6))]
                    elif r < 0.45:
                        ids = engine.hold_many(user, rng.sample(SEATS, rng.randint(1, 4)),
                                               rng.randint(1, 6))
                    elif r < 0.65:
                        engine.confirm(pick_known(rng)); continue
                    elif r < 0.80:
                        engine.release(pick_known(rng)); continue
                    elif r < 0.90:
                        engine.seat_status(rng.choice(SEATS)); continue
                    else:
                        clock.advance(rng.random() * 2); continue
                    with lock:
                        known.extend(ids)
                    if engine.active_hold_count(user) > MAX_HOLDS_PER_USER:
                        note("user %s over the hold cap" % user)
                except HoldError:
                    pass
        except Exception as e:
            note("unexpected %r" % (e,))

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n_threads)]
    for t in threads:
        t.start()
    deadline = time.time() + 60
    for t in threads:
        t.join(max(0, deadline - time.time()))
    if any(t.is_alive() for t in threads):
        problems.append("threads still running: hang or deadlock")
        return problems
    try:
        engine.check_invariants()
    except AssertionError as e:
        problems.append("invariant: %s" % e)
    replay(engine, problems)
    return problems


class Stress(unittest.TestCase):
    def setUp(self):
        self._sw = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

    def tearDown(self):
        sys.setswitchinterval(self._sw)

    def test_engine_holds_invariants(self):
        for k in range(3):
            self.assertEqual(run_stress(HoldEngine, SEED + k), [], "seed %d" % (SEED + k))

    def test_no_deadlock_on_opposite_order(self):
        e = HoldEngine(["A", "B", "C"], clock=FakeClock())

        def go(user, order):
            for _ in range(2000):
                try:
                    ids = e.hold_many(user, order, 100)
                    for h in ids:
                        e.release(h)
                except HoldError:
                    pass

        ts = [threading.Thread(target=go, args=("u1", ["A", "B", "C"]), daemon=True),
              threading.Thread(target=go, args=("u2", ["C", "B", "A"]), daemon=True)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertFalse(any(t.is_alive() for t in ts), "deadlock")

    def test_checker_actually_fails_on_a_broken_engine(self):
        self.assertTrue(run_stress(BrokenEngine, SEED, ops=200))


if __name__ == "__main__":
    unittest.main()
