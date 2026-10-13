### What I did myself:
- Read and analyzed the PDF spec, resolved all rule conflicts, and wrote the rationale in `DECISIONS.md`.
- Wrote the core hold engine logic in `hold_engine.py` (seat state transitions, locking mechanism, and the injectable fake clock).
- Ran all unit, stress, and model tests locally using `unittest`.
- Checked invariant assertions under concurrent load and verified reproducible runs using different random seeds.
- Confirmed the stress test genuinely catches bugs by running it against the broken engine test case.
- Wrote `README.md` and `BUGS_I_FEAR.md`.


# AI Usage

### Tool Used
- (Claude, by Anthropic)

### What I used AI for:
- Discussed edge cases around deadlock handling when multiple users request overlapping seats in different orders. Confirmed that sorting seat IDs before acquiring locks is the cleanest way to prevent cyclic deadlocks.
- Bounced ideas on how to interpret conflicting rules (specifically R3 vs R4 vs R5 when retrying expired holds).