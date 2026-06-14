"""
Registration Module — Enumerations
=====================================
Consent types and identity verification classifications used
throughout the patient registration workflow.
"""

from enum import Enum


class ConsentType(str, Enum):
    """Types of consent that may be captured during registration."""

    TREATMENT = "treatment"
    DATA_SHARING = "data_sharing"
    RESEARCH = "research"
    HIPAA_NOTICE = "hipaa_notice"
    TELEHEALTH = "telehealth"


class VerificationType(str, Enum):
    """Types of identity documents accepted during registration."""

    GOVERNMENT_ID = "government_id"
    PASSPORT = "passport"
    INSURANCE_CARD = "insurance_card"
    BIOMETRIC = "biometric"
    OTHER = "other"
