"""Domain aliases for canonical benefit entities.

Business calculations are added in later tasks; this module deliberately owns
no persistence or transport dependencies.
"""

from ..contracts.applicant import ApplicantAdmissionFacts
from ..contracts.public import AdmissionBenefitRule, IndividualAchievementRule

__all__ = ["AdmissionBenefitRule", "ApplicantAdmissionFacts", "IndividualAchievementRule"]
