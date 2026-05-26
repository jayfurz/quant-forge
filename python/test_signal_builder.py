#!/usr/bin/env python3
"""Smoke test for QuantForge Python modules."""

import sys
sys.path.insert(0, '.')

from features.signal_builder import (
    filing_diff_score, evasiveness_score, interpret_signal,
    build_composite_signal
)

errors = 0

# ── Filing Diff ──────────────────────────────────────────────────
result = filing_diff_score(
    'The company faces significant cyber and regulatory risks. Material adverse effects possible.',
    'The company faces standard market risks.'
)
assert result['severity_score'] == 11, f"severity={result['severity_score']}"
assert result['new_risk_count'] == 5, f"new_risks={result['new_risk_count']}"
print(f"  ✅ Filing diff: severity={result['severity_score']}, changes={result['pct_changed']}%")

# ── Evasiveness ──────────────────────────────────────────────────
ev = evasiveness_score(
    "We decline to answer. Too early to say. Not providing guidance. "
    "Difficult to predict. Normal operations."
)
assert ev['evasive_phrase_count'] == 4
# Short text: 4 evasive phrases in ~12 words = high per-10k but capped at 100
assert ev['evasiveness_score'] >= 50, f"score={ev['evasiveness_score']}"
print(f"  ✅ Evasiveness (short): count={ev['evasive_phrase_count']}, score={ev['evasiveness_score']}")

# Longer earnings call
ev2 = evasiveness_score("""Good morning and welcome to the quarterly results call.
Revenue grew 15% year over year. Our AI division is expanding rapidly
with new customer wins. Margins improved 200bps. Very pleased with execution.
Now I'll take your questions.
Q: Can you provide Q3 guidance?
A: We're not providing guidance at this time. Too early to say how tariffs
will impact our supply chain. We don't have visibility into H2 yet.
We'll see how it plays out.
Q: What about the regulatory investigation?
A: We decline to answer that for competitive reasons.
Q: Any comment on the CFO departure?
A: No comment. Next question please.
""")
assert ev2['evasive_phrase_count'] >= 5, f"got {ev2['evasive_phrase_count']}"
assert 0 < ev2['evasiveness_score'] <= 100, f"score={ev2['evasiveness_score']}"
print(f"  ✅ Evasiveness (earnings call): count={ev2['evasive_phrase_count']}, score={ev2['evasiveness_score']}")

# ── Interpretation ───────────────────────────────────────────────
tests = [
    (2.0, 'STRONG_BULLISH'),
    (0.7, 'BULLISH'),
    (0.0, 'NEUTRAL'),
    (-1.0, 'BEARISH'),
    (-2.0, 'STRONG_BEARISH'),
]
for score, expected in tests:
    got = interpret_signal(score)
    assert got == expected, f"interpret({score}) = {got}, expected {expected}"
print(f"  ✅ Interpretation: all 5 thresholds correct")

# ── Composite Signal ─────────────────────────────────────────────
# Empty
sig = build_composite_signal('EMPTY')
assert sig['composite_score'] == 0.0
print(f"  ✅ Empty composite: {sig['composite_score']} → {sig['interpretation']}")

# Filing + evasiveness only (both negative drivers)
sig2 = build_composite_signal(
    'BEAR',
    sec_filing_score={'severity_score': 8, 'pct_changed': 20.0, 'new_risk_count': 4},
    evasiveness={'evasiveness_score': 40.0},
)
assert sig2['composite_score'] < 0, f"Expected negative, got {sig2['composite_score']}"
print(f"  ✅ Risk + evasiveness: {sig2['composite_score']:+.3f} → {sig2['interpretation']}")

# Filing only
sig3 = build_composite_signal(
    'MODERATE',
    sec_filing_score={'severity_score': 1, 'pct_changed': 5.0, 'new_risk_count': 1},
)
print(f"  ✅ Filing only: {sig3['composite_score']:+.3f} → {sig3['interpretation']}")
assert sig3['components']['filing_risk'] < 0  # Risk is negative signal
assert sig3['components']['filing_risk'] > -1.0  # Light severity

# ── Done ─────────────────────────────────────────────────────────
print()
print("=" * 50)
print("ALL SIGNAL BUILDER TESTS PASSED ✅")
print("=" * 50)
