"""Pluggable, deterministic conflict-detection rule-packs.

Importing this package registers the default SOP-QC-008 pack.
"""

from oligos_agents.rules import sop_qc_008  # noqa: F401  (self-registers on import)
from oligos_agents.rules.base import RulePack, get_pack, get_packs, register_pack, run_all

__all__ = ["RulePack", "get_pack", "get_packs", "register_pack", "run_all"]
