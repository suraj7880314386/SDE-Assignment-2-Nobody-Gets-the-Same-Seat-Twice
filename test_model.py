import os, random, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hold_engine import *

SEED = int(os.environ.get("SEED", random.randrange(2 ** 32)))
print("model seed:", SEED)

SEATS = ["A", "B", "C", "D", "E"]
USERS = ["u1", "u2", "u3"]


class Model:
    """Dumb reference. Keeps every hold forever and works out everything from scratch.
    A hold can still be confirmed only if it is the newest hold ever made on its seat
    and was not released or confirmed."""

    def __init__(self, clock):
        self.clock, self.holds = clock, []

    def _latest(self, seat):
        for h in reversed(self.holds):
            if h["seat"] == seat:
                return h

    def _live(self, h):
        return not h["confirmed"] and not h["released"] and self._latest(h["seat"]) is h

    def _sold(self, seat):
        return next((h for h in self.holds if h["seat"] == seat and h["confirmed"]), None)

    def active_hold_count(self, user):
        now = self.clock()
        return sum(1 for h in self.holds if h["user"] == user and self._live(h) and h["exp"] > now)

    def hold_many(self, user, seats, ttl):
        if not isinstance(ttl, (int, float)) or ttl <= 0:
            raise InvalidArgument()
        wanted = list(dict.fromkeys(seats))
        for s in wanted:
            if s not in SEATS:
                raise UnknownSeat()
        now, mine, fresh = self.clock(), {}, []
        for s in wanted:
            if self._sold(s):
                raise SeatUnavailable()
            cur = self._latest(s)
            if cur and self._live(cur) and cur["exp"] > now:
                if cur["user"] != user:
                    raise SeatUnavailable()
                mine[s] = cur["id"]
            else:
                fresh.append(s)
        if self.active_hold_count(user) + len(fresh) > MAX_HOLDS_PER_USER:
            raise HoldLimitExceeded()
        for s in fresh:
            h = dict(id="h%d" % (len(self.holds) + 1), seat=s, user=user, exp=now + ttl,
                     confirmed=False, released=False)
            self.holds.append(h)
            mine[s] = h["id"]
        return [mine[s] for s in wanted]

    def hold(self, seat, user, ttl):
        return self.hold_many(user, [seat], ttl)[0]

    def _find(self, hid):
        for h in self.holds:
            if h["id"] == hid:
                return h
        raise UnknownHold()

    def confirm(self, hid):
        h = self._find(hid)
        if h["confirmed"]:
            return True
        if h["released"]:
            raise HoldReleased()
        if self._latest(h["seat"]) is not h:
            raise HoldExpired()
        h["confirmed"] = True
        return True

    def release(self, hid):
        h = self._find(hid)
        if h["released"]:
            return True
        if h["confirmed"]:
            raise AlreadySold()
        if self._latest(h["seat"]) is not h:
            raise HoldExpired()
        h["released"] = True
        return True

    def seat_status(self, seat):
        if seat not in SEATS:
            raise UnknownSeat()
        s = self._sold(seat)
        if s:
            return Sold(s["user"])
        cur = self._latest(seat)
        if cur and self._live(cur) and cur["exp"] > self.clock():
            return Held(cur["user"], cur["exp"])
        return Free()


def run_sequence(seed, n_ops=150):
    rng = random.Random(seed)
    clock = FakeClock()
    engine, model = HoldEngine(SEATS, clock=clock), Model(clock)
    ids = []

    def both(name, *args):
        out = []
        for impl in (engine, model):
            try:
                out.append(("ok", getattr(impl, name)(*args)))
            except HoldError as e:
                out.append(("err", type(e).__name__))
        return out

    for step in range(n_ops):
        op = rng.choice(["hold", "hold", "many", "many", "confirm", "release", "advance", "status"])
        if op == "hold":
            args = ("hold", rng.choice(SEATS + ["ZZ"]), rng.choice(USERS),
                    rng.choice([1, 2, 3, 5, 5, 8, 0, -1]))
        elif op == "many":
            args = ("hold_many", rng.choice(USERS), rng.choices(SEATS, k=rng.randint(0, 5)),
                    rng.choice([1, 2, 3, 5, 8]))
        elif op in ("confirm", "release"):
            args = (op, rng.choice(ids + ["h999"]) if ids else "h999")
        elif op == "status":
            args = ("seat_status", rng.choice(SEATS))
        else:
            clock.advance(rng.randint(0, 4))
            args = None
        if args:
            got, want = both(*args)
            assert got == want, "seed %s step %d %r: engine=%r model=%r" % (seed, step, args, got, want)
            if args[0] in ("hold", "hold_many") and got[0] == "ok":
                ids.extend(got[1] if isinstance(got[1], list) else [got[1]])
        for s in SEATS:
            assert engine.seat_status(s) == model.seat_status(s), \
                "seed %s step %d: status of %s differs" % (seed, step, s)
        for u in USERS:
            assert engine.active_hold_count(u) == model.active_hold_count(u), \
                "seed %s step %d: hold count of %s differs" % (seed, step, u)
        engine.check_invariants()


class ModelTest(unittest.TestCase):
    def test_random_sequences_match_reference(self):
        for i in range(400):
            run_sequence(SEED + i)


if __name__ == "__main__":
    unittest.main()
