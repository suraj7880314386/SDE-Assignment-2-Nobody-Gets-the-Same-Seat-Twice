"""In-memory, thread-safe seat hold engine. Rule choices are in DECISIONS.md."""
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

MAX_HOLDS_PER_USER = 4

_ACTIVE, _CONFIRMED, _RELEASED, _SUPERSEDED = "active", "confirmed", "released", "superseded"


class HoldError(Exception):
    pass


class InvalidArgument(HoldError):
    pass


class UnknownSeat(HoldError):
    pass


class UnknownHold(HoldError):
    pass


class SeatUnavailable(HoldError):
    pass


class HoldLimitExceeded(HoldError):
    pass


class HoldExpired(HoldError):
    """Hold ran out AND someone else took the seat afterwards."""


class HoldReleased(HoldError):
    pass


class AlreadySold(HoldError):
    pass


@dataclass(frozen=True)
class Free:
    pass


@dataclass(frozen=True)
class Held:
    user: object
    expires_at: float


@dataclass(frozen=True)
class Sold:
    user: object


class FakeClock:
    def __init__(self, start=0.0):
        self._t = start
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self._t

    def advance(self, dt):
        with self._lock:
            self._t += dt


class _Hold:
    __slots__ = ("id", "seat", "user", "expires_at", "status")

    def __init__(self, hid, seat, user, expires_at):
        self.id = hid
        self.seat = seat
        self.user = user
        self.expires_at = expires_at
        self.status = _ACTIVE


class _Seat:
    def __init__(self, lock):
        self.lock = lock
        self.current = None   # latest ACTIVE hold (may be expired but still revivable)
        self.sold_to = None
        self.history = []


class _User:
    def __init__(self, lock):
        self.lock = lock
        self.hold_ids = set()


class HoldEngine:
    def __init__(self, seat_ids, clock=time.monotonic, lock_factory=threading.Lock,
                 record_history=False):
        self._clock = clock
        self._lock_factory = lock_factory
        self._seats = {s: _Seat(lock_factory()) for s in seat_ids}
        self._reg_lock = threading.Lock()   # guards _holds, _users, id counter
        self._holds = {}
        self._users = {}
        self._next_id = 1
        self._record = record_history

    # ---------- public API ----------

    def hold(self, seat_id, user_id, ttl_seconds):
        return self.hold_many(user_id, [seat_id], ttl_seconds)[0]

    def hold_many(self, user_id, seat_ids, ttl_seconds):
        self._check_ttl(ttl_seconds)
        if user_id is None:
            raise InvalidArgument("user_id is required")
        wanted = list(dict.fromkeys(seat_ids))
        for s in wanted:
            if s not in self._seats:
                raise UnknownSeat(s)
        if not wanted:
            return []

        with self._locked(user_id, wanted):
            now = self._clock()
            mine = {}
            fresh = []
            for s in wanted:
                seat = self._seats[s]
                if seat.sold_to is not None:
                    raise SeatUnavailable(s)
                cur = seat.current
                if cur is not None and cur.expires_at > now:
                    if cur.user != user_id:
                        raise SeatUnavailable(s)
                    mine[s] = cur.id
                else:
                    fresh.append(s)
            if self._active_count(user_id, now) + len(fresh) > MAX_HOLDS_PER_USER:
                raise HoldLimitExceeded(user_id)

            self._pause()  # test hook, no-op normally

            user = self._user(user_id)
            for s in fresh:
                seat = self._seats[s]
                if seat.current is not None:
                    seat.current.status = _SUPERSEDED   # expired and now taken
                h = self._new_hold(s, user_id, now + ttl_seconds)
                seat.current = h
                user.hold_ids.add(h.id)
                self._log(seat, "hold", h, now)
                mine[s] = h.id
            return [mine[s] for s in wanted]

    def confirm(self, hold_id):
        h = self._get_hold(hold_id)
        with self._locked(h.user, [h.seat]):
            if h.status == _CONFIRMED:
                return True
            if h.status == _RELEASED:
                raise HoldReleased(hold_id)
            if h.status == _SUPERSEDED:
                raise HoldExpired(hold_id)
            seat = self._seats[h.seat]
            h.status = _CONFIRMED
            seat.sold_to = h.user
            seat.current = None
            self._user(h.user).hold_ids.discard(h.id)
            self._log(seat, "confirm", h, self._clock())
            return True

    def release(self, hold_id):
        h = self._get_hold(hold_id)
        with self._locked(h.user, [h.seat]):
            if h.status == _RELEASED:
                return True
            if h.status == _CONFIRMED:
                raise AlreadySold(hold_id)
            if h.status == _SUPERSEDED:
                raise HoldExpired(hold_id)
            seat = self._seats[h.seat]
            h.status = _RELEASED
            seat.current = None
            self._user(h.user).hold_ids.discard(h.id)
            self._log(seat, "release", h, self._clock())
            return True

    def seat_status(self, seat_id):
        seat = self._seats.get(seat_id)
        if seat is None:
            raise UnknownSeat(seat_id)
        with seat.lock:
            now = self._clock()
            if seat.sold_to is not None:
                return Sold(seat.sold_to)
            cur = seat.current
            if cur is not None and cur.expires_at > now:
                return Held(cur.user, cur.expires_at)
            return Free()

    # ---------- helpers used by tests ----------

    def active_hold_count(self, user_id):
        with self._user(user_id).lock:
            return self._active_count(user_id, self._clock())

    def history(self, seat_id):
        with self._seats[seat_id].lock:
            return list(self._seats[seat_id].history)

    def check_invariants(self):
        """Only call when no other thread is running."""
        now = self._clock()
        active, sold = {}, {}
        for h in self._holds.values():
            if h.status == _ACTIVE:
                _require(h.seat not in active, "two active holds on seat %s" % h.seat)
                active[h.seat] = h
            elif h.status == _CONFIRMED:
                _require(h.seat not in sold, "seat %s sold twice" % h.seat)
                sold[h.seat] = h
        for sid, seat in self._seats.items():
            if sid in sold:
                _require(seat.sold_to == sold[sid].user and seat.current is None
                         and sid not in active, "seat %s sold state inconsistent" % sid)
            else:
                _require(seat.sold_to is None, "seat %s marked sold without confirmed hold" % sid)
            _require(seat.current is active.get(sid), "seat %s current hold mismatch" % sid)
        per_user = {}
        for h in active.values():
            if h.expires_at > now:
                per_user[h.user] = per_user.get(h.user, 0) + 1
        for u, n in per_user.items():
            _require(n <= MAX_HOLDS_PER_USER, "user %s has %d live holds" % (u, n))

    # ---------- internals ----------

    def _pause(self):
        pass

    def _log(self, seat, kind, h, now):
        if self._record:
            seat.history.append((kind, h.id, h.user, now, h.expires_at))

    def _check_ttl(self, ttl):
        if (isinstance(ttl, bool) or not isinstance(ttl, (int, float))
                or not math.isfinite(ttl) or ttl <= 0):
            raise InvalidArgument("ttl must be a positive finite number")

    def _user(self, user_id):
        with self._reg_lock:
            u = self._users.get(user_id)
            if u is None:
                u = self._users[user_id] = _User(self._lock_factory())
            return u

    def _get_hold(self, hold_id):
        with self._reg_lock:
            h = self._holds.get(hold_id)
        if h is None:
            raise UnknownHold(hold_id)
        return h

    def _new_hold(self, seat, user, expires_at):
        with self._reg_lock:
            hid = "h%d" % self._next_id
            self._next_id += 1
            h = self._holds[hid] = _Hold(hid, seat, user, expires_at)
            return h

    def _active_count(self, user_id, now):
        # Caller holds the user lock. A SUPERSEDED hold is always already expired
        # (clock is monotonic), so reading status without the seat lock is safe.
        user = self._user(user_id)
        n = 0
        for hid in list(user.hold_ids):
            h = self._holds[hid]
            if h.status == _ACTIVE and h.expires_at > now:
                n += 1
            else:
                user.hold_ids.discard(hid)
        return n

    @contextmanager
    def _locked(self, user_id, seat_ids):
        # Order: user lock first, then seat locks in sorted order.
        locks = [self._user(user_id).lock] + [self._seats[s].lock for s in sorted(set(seat_ids))]
        taken = []
        try:
            for lk in locks:
                lk.acquire()
                taken.append(lk)
            yield
        finally:
            for lk in reversed(taken):
                lk.release()


def _require(cond, msg):
    if not cond:
        raise AssertionError(msg)
