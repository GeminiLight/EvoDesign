"""verification_stage.critic — VLM-based subjective critique.

Single multimodal call to a VLM (configured via models.yaml) returning
a 3-dimensional structured score: structure / styling / layout.

The PNG is read as raw bytes inside `critic_agent.py` and base64-encoded
for the API payload — the verifier itself never visually inspects the image.
"""

from .critic_agent import VerifierCriticAgent  # noqa: F401

__all__ = ["VerifierCriticAgent"]
