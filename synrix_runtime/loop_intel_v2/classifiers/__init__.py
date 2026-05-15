"""Individual loop classifiers. Each is a pure function of a window of events.

Each classifier module exports a single `classify(events)` function that
returns `Optional[LoopDetection]`. Returning None means "this type did not
match." Returning a `LoopDetection` means it did, and the detection struct
carries the full evidence chain.

Classifiers never mutate input. Classifiers do not call external services.
"""

from .retry import classify as classify_retry, RULE_VERSION as RETRY_VERSION
from .polling import classify as classify_polling, RULE_VERSION as POLLING_VERSION
from .decision_oscillation import (
    classify as classify_decision_oscillation,
    RULE_VERSION as DECISION_OSC_VERSION,
)
from .cost_inflation import (
    classify as classify_cost_inflation,
    RULE_VERSION as COST_INFLATION_VERSION,
)
from .self_correction import (
    classify as classify_self_correction,
    RULE_VERSION as SELF_CORRECTION_VERSION,
)
from .ping_pong import (
    classify as classify_ping_pong,
    RULE_VERSION as PING_PONG_VERSION,
)
from .tool_nondeterminism import (
    classify as classify_tool_nondeterminism,
    RULE_VERSION as TOOL_NONDET_VERSION,
)
from .recall_write import (
    classify as classify_recall_write,
    RULE_VERSION as RECALL_WRITE_VERSION,
)
from .clarification import (
    classify as classify_clarification,
    RULE_VERSION as CLARIFICATION_VERSION,
)
from .reflection import (
    classify as classify_reflection,
    RULE_VERSION as REFLECTION_VERSION,
)

__all__ = [
    "classify_retry",
    "classify_polling",
    "classify_decision_oscillation",
    "classify_cost_inflation",
    "classify_self_correction",
    "classify_ping_pong",
    "classify_tool_nondeterminism",
    "classify_recall_write",
    "classify_clarification",
    "classify_reflection",
    "RETRY_VERSION",
    "POLLING_VERSION",
    "DECISION_OSC_VERSION",
    "COST_INFLATION_VERSION",
    "SELF_CORRECTION_VERSION",
    "PING_PONG_VERSION",
    "TOOL_NONDET_VERSION",
    "RECALL_WRITE_VERSION",
    "CLARIFICATION_VERSION",
    "REFLECTION_VERSION",
]
