# BUGS_I_FEAR

**Bug class: the clock going backwards or jumping.**
The fake clock in my tests only moves forward. The engine relies on that: it assumes a hold that got taken over is already expired, and it prunes expired holds from a user's count. If production used a wall clock and NTP stepped it back, an expired hold could look live again, and the cap or the "retaken" logic could be wrong. My tests would never show it.

How I'd catch it in production: use a monotonic clock only (the default is `time.monotonic`), log and alert if two reads in a row ever go backwards, and run a periodic audit that compares the engine's state with the payment records (any seat sold twice, or any sale on a hold that was retaken, pages someone).
