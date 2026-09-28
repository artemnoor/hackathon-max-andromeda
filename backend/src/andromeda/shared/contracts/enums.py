from enum import StrEnum


class EducationLevel(StrEnum):
    BACHELOR = "bachelor"
    SPECIALIST = "specialist"
    MASTER = "master"
    POSTGRADUATE = "postgraduate"


class AssessmentType(StrEnum):
    EXAM = "exam"
    CREDIT = "credit"
    GRADED_CREDIT = "graded_credit"
    COURSEWORK = "coursework"
    COURSE_PROJECT = "course_project"
    STATE_EXAM = "state_exam"


class SourceKind(StrEnum):
    BMSTU_COMMON = "bmstu_common"
    BMSTU_MAJOR_CATALOG = "bmstu_major_catalog"
    BMSTU_MAJOR_DETAIL = "bmstu_major_detail"
    BMSTU_CURRICULUM_DOCUMENT = "bmstu_curriculum_document"
    BMSTU_CURRICULUM_METADATA = "bmstu_curriculum_metadata"
    BMSTU_ADMISSION_ORDERS_INDEX = "bmstu_admission_orders_index"
    BMSTU_ADMISSION_ORDERS_DOCUMENT = "bmstu_admission_orders_document"
    BMSTU_ADMISSION_DOCUMENT_INDEX = "bmstu_admission_document_index"
    BMSTU_ADMISSION_RULES = "bmstu_admission_rules"
    BMSTU_ADMISSION_BENEFITS = "bmstu_admission_benefits"
    BMSTU_ADMISSION_INDIVIDUAL_ACHIEVEMENTS = "bmstu_admission_individual_achievements"
    BMSTU_EVENTS = "bmstu_events"
    BMSTU_CAMPUS_POINTS = "bmstu_campus_points"
    HSE_COMMON = "hse_common"
    HSE_PROGRAM_CATALOG = "hse_program_catalog"
    HSE_PROGRAM_DETAIL = "hse_program_detail"
    HSE_CURRICULUM_INDEX = "hse_curriculum_index"
    HSE_CURRICULUM_DOCUMENT = "hse_curriculum_document"
    HSE_ADMISSION_RULES = "hse_admission_rules"
    HSE_ADMISSION_PLACES = "hse_admission_places"
    HSE_TUITION = "hse_tuition"
    HSE_PASSING_SCORES = "hse_passing_scores"
    HSE_ENROLLMENT_INDEX = "hse_enrollment_index"
    HSE_ENROLLMENT_DOCUMENT = "hse_enrollment_document"


class CompareStatus(StrEnum):
    BOTH = "both"
    ONLY_A = "only_a"
    ONLY_B = "only_b"
    DIFFERENT = "different"


class ComparisonScope(StrEnum):
    ALL = "all"
    SEMESTER = "semester"
