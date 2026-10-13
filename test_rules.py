import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hold_engine import *


class Rules(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.e = HoldEngine(["A", "B", "C", "D", "E", "F"], clock=self.clock)

    def test_basic_flow(self):
        h = self.e.hold("A", "u1", 10)
        self.assertEqual(self.e.seat_status("A"), Held("u1", 10))
        self.assertTrue(self.e.confirm(h))
        self.assertEqual(self.e.seat_status("A"), Sold("u1"))

    def test_r1_one_holder_and_no_hold_on_sold(self):
        h = self.e.hold("A", "u1", 10)
        with self.assertRaises(SeatUnavailable):
            self.e.hold("A", "u2", 10)
        self.e.confirm(h)
        with self.assertRaises(SeatUnavailable):
            self.e.hold("A", "u2", 10)
        with self.assertRaises(SeatUnavailable):
            self.e.hold("A", "u1", 10)

    def test_expiry_frees_seat(self):
        self.e.hold("A", "u1", 10)
        self.clock.advance(9.99)
        self.assertIsInstance(self.e.seat_status("A"), Held)
        self.clock.advance(0.01)  # now == expires_at counts as expired
        self.assertEqual(self.e.seat_status("A"), Free())
        self.assertTrue(self.e.hold("A", "u2", 10))

    def test_r3_expired_but_untaken_can_be_confirmed(self):
        h = self.e.hold("A", "u1", 5)
        self.clock.advance(100)
        self.assertEqual(self.e.seat_status("A"), Free())  # not extended, shows free
        self.assertTrue(self.e.confirm(h))
        self.assertEqual(self.e.seat_status("A"), Sold("u1"))

    def test_r3_expired_and_taken_cannot_be_confirmed_even_if_taker_leaves(self):
        h1 = self.e.hold("A", "u1", 5)
        self.clock.advance(6)
        h2 = self.e.hold("A", "u2", 5)
        with self.assertRaises(HoldExpired):
            self.e.confirm(h1)
        self.e.release(h2)
        with self.assertRaises(HoldExpired):
            self.e.confirm(h1)
        self.assertEqual(self.e.seat_status("A"), Free())

    def test_r4_retry_never_extends(self):
        h1 = self.e.hold("A", "u1", 10)
        self.clock.advance(4)
        h2 = self.e.hold("A", "u1", 1000)
        self.assertEqual(h1, h2)
        self.assertEqual(self.e.seat_status("A"), Held("u1", 10))

    def test_r5_retry_after_expiry_makes_new_hold_and_kills_old_id(self):
        h1 = self.e.hold("A", "u1", 5)
        self.clock.advance(6)
        h2 = self.e.hold("A", "u1", 5)
        self.assertNotEqual(h1, h2)
        with self.assertRaises(HoldExpired):
            self.e.confirm(h1)
        self.assertTrue(self.e.confirm(h2))

    def test_r2_cap_and_retry_at_cap(self):
        ids = [self.e.hold(s, "u1", 10) for s in "ABCD"]
        with self.assertRaises(HoldLimitExceeded):
            self.e.hold("E", "u1", 10)
        self.assertEqual(self.e.hold("A", "u1", 10), ids[0])  # retry is not a 5th hold
        self.e.release(ids[1])
        self.assertTrue(self.e.hold("E", "u1", 10))

    def test_r2_expired_holds_do_not_count(self):
        for s in "ABCD":
            self.e.hold(s, "u1", 5)
        self.clock.advance(6)
        self.assertEqual(self.e.active_hold_count("u1"), 0)
        for s in "ABCD":
            self.e.hold(s, "u1", 5)

    def test_confirming_expired_hold_while_at_cap(self):
        old = self.e.hold("A", "u1", 5)
        self.clock.advance(6)
        for s in "BCDE":
            self.e.hold(s, "u1", 50)
        self.assertTrue(self.e.confirm(old))   # sold seats don't count as holds
        self.assertEqual(self.e.active_hold_count("u1"), 4)

    def test_r6_all_or_nothing(self):
        self.e.hold("C", "u2", 10)
        with self.assertRaises(SeatUnavailable):
            self.e.hold_many("u1", ["A", "B", "C"], 10)
        self.assertEqual(self.e.seat_status("A"), Free())
        self.assertEqual(self.e.seat_status("B"), Free())
        self.assertEqual(self.e.active_hold_count("u1"), 0)

    def test_r6_cap_all_or_nothing(self):
        self.e.hold("A", "u1", 10)
        self.e.hold("B", "u1", 10)
        with self.assertRaises(HoldLimitExceeded):
            self.e.hold_many("u1", ["C", "D", "E"], 10)
        self.assertEqual(self.e.seat_status("C"), Free())
        self.assertEqual(self.e.active_hold_count("u1"), 2)

    def test_r6_duplicates_and_already_held_seats(self):
        a = self.e.hold("A", "u1", 10)
        ids = self.e.hold_many("u1", ["A", "B", "B", "C", "D"], 10)
        self.assertEqual(len(ids), 4)
        self.assertEqual(ids[0], a)
        self.assertEqual(len(set(ids)), 4)  # duplicate B collapsed
        self.assertEqual(self.e.active_hold_count("u1"), 4)  # A was not counted twice
        self.assertEqual(self.e.hold_many("u1", [], 10), [])

    def test_confirm_release_edges(self):
        h = self.e.hold("A", "u1", 10)
        self.assertTrue(self.e.confirm(h))
        self.assertTrue(self.e.confirm(h))      # idempotent
        with self.assertRaises(AlreadySold):
            self.e.release(h)
        g = self.e.hold("B", "u1", 10)
        self.assertTrue(self.e.release(g))
        self.assertTrue(self.e.release(g))      # idempotent
        with self.assertRaises(HoldReleased):
            self.e.confirm(g)
        with self.assertRaises(UnknownHold):
            self.e.confirm("nope")

    def test_release_expired_hold_kills_revival(self):
        h = self.e.hold("A", "u1", 5)
        self.clock.advance(10)
        self.e.release(h)
        with self.assertRaises(HoldReleased):
            self.e.confirm(h)

    def test_bad_input(self):
        for ttl in (0, -1, float("nan"), float("inf"), "5", None, True):
            with self.assertRaises(InvalidArgument):
                self.e.hold("A", "u1", ttl)
        with self.assertRaises(UnknownSeat):
            self.e.hold("ZZ", "u1", 5)
        with self.assertRaises(UnknownSeat):
            self.e.seat_status("ZZ")
        with self.assertRaises(UnknownSeat):
            self.e.hold_many("u1", ["A", "ZZ"], 5)
        self.assertEqual(self.e.seat_status("A"), Free())


if __name__ == "__main__":
    unittest.main()
