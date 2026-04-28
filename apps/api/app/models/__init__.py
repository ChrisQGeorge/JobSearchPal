"""Import all ORM models so Alembic can see them via Base.metadata."""
from app.models.base import Base

from app.models.user import ApiCredential, Persona, User
from app.models.history import (
    Achievement,
    Certification,
    Contact,
    Course,
    CourseSkill,
    CustomEvent,
    Education,
    Language,
    Presentation,
    Project,
    ProjectSkill,
    Publication,
    Skill,
    VolunteerWork,
    WorkExperience,
    WorkExperienceSkill,
)
from app.models.preferences import (
    Demographics,
    DemographicSharePolicy,
    JobCriterion,
    JobPreferences,
    ResumeProfile,
    WorkAuthorization,
)
from app.models.jobs import (
    ApplicationEvent,
    InterviewArtifact,
    InterviewRound,
    JobFetchQueue,
    Organization,
    TrackedJob,
)
from app.models.documents import (
    CoverLetterSnippet,
    DocumentEdit,
    GeneratedDocument,
    WritingSample,
)
from app.models.companion import CompanionConversation, ConversationMessage, Task
from app.models.links import EntityLink
from app.models.operational import AuditLog, AutofillLog, MetricSnapshot

__all__ = [
    "Base",
    "User",
    "Persona",
    "ApiCredential",
    "WorkExperience",
    "WorkExperienceSkill",
    "CourseSkill",
    "ProjectSkill",
    "Education",
    "Course",
    "Certification",
    "Skill",
    "Language",
    "Project",
    "Publication",
    "Presentation",
    "Achievement",
    "VolunteerWork",
    "Contact",
    "CustomEvent",
    "JobPreferences",
    "JobCriterion",
    "WorkAuthorization",
    "Demographics",
    "DemographicSharePolicy",
    "ResumeProfile",
    "Organization",
    "TrackedJob",
    "ApplicationEvent",
    "InterviewRound",
    "InterviewArtifact",
    "JobFetchQueue",
    "GeneratedDocument",
    "DocumentEdit",
    "WritingSample",
    "CoverLetterSnippet",
    "CompanionConversation",
    "ConversationMessage",
    "Task",
    "EntityLink",
    "AuditLog",
    "AutofillLog",
    "MetricSnapshot",
]
