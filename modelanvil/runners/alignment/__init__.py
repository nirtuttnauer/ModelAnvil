"""Preference, reward model, RLHF, and verifier RL alignment module (WP-11 / TECH-018-019)."""
from .preferences import PreferencePair, PreferenceDataset, build_preference_dataset_from_records
from .dpo import DPOEngine
from .reward_model import RewardModelEngine
from .rlhf import RLHFOrchestrator
from .verifier import VerifierEngine
from .release_gate import evaluate_alignment_release_gate, AlignmentReleaseGateResult

__all__ = [
    "PreferencePair",
    "PreferenceDataset",
    "build_preference_dataset_from_records",
    "DPOEngine",
    "RewardModelEngine",
    "RLHFOrchestrator",
    "VerifierEngine",
    "evaluate_alignment_release_gate",
    "AlignmentReleaseGateResult",
]
