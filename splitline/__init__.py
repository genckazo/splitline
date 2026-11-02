"""SplitLine — one line for the game, one line for everything else.

Stdlib-only, fully offline. Every mutating operation is planned first,
printed, executed step-by-step with an undo for every step, verified after
apply, and automatically rolled back if anything fails. The tool never
leaves a half-applied routing state behind.
"""

__version__ = "0.2.0"
