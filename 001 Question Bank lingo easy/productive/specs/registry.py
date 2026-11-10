"""Registry of the authored task specs (single source of truth for the generators)."""
from . import writing_a, writing_b, writing_c, speaking_a, speaking_b, speaking_c

WRITING = {"placement": writing_c.PLACEMENT, "A1": writing_a.A1, "A2": writing_a.A2, "B1": writing_b.B1, "B2": writing_b.B2, "C1": writing_c.C1, "C2": writing_c.C2}
SPEAKING = {"placement": speaking_c.PLACEMENT, "A1": speaking_a.A1, "A2": speaking_a.A2, "B1": speaking_b.B1, "B2": speaking_b.B2, "C1": speaking_c.C1, "C2": speaking_c.C2}
POOLS = {"writing": WRITING, "speaking": SPEAKING}
