"""Frontier Agent Benchmark (FAB).

An independent observability and benchmarking platform for evaluating
autonomous AI engineering agents.

Design principles
-----------------
1. Provenance discipline: every measurement is tagged OBSERVED, ESTIMATED or
   UNAVAILABLE.  Nothing is ever fabricated.
2. Quality over quantity: scores reward correctness, reliability and design,
   never raw volume (lines of code / commits / tokens are context, not rank).
3. Subject isolation: benchmarked projects are copied into scratch workspaces
   before anything is executed; original repositories are never modified.
"""

__version__ = "0.1.0"
