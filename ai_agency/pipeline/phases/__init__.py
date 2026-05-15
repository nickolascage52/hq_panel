"""Pipeline phases — one module per phase.

Phase order:
    1. Prompt refinement      (phase1_prompt)
    2. PRD generation          (phase2_prd)
    3. Architecture decision   (phase3_architecture)
    4. Sprint planning         (phase4_sprints)
    5. Sprint execution loop   (phase5_execution)
    6. Final validation        (phase6_validation)
    7. Handoff                 (phase7_handoff)
"""
from .base import PhaseBase

__all__ = ['PhaseBase']
