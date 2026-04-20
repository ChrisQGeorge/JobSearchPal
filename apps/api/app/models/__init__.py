"""Import all ORM models so Alembic can see them via Base.metadata."""
from app.models.base import Base

from app.models.user import ApiCredential, Persona, User
from app.models.history import (
    Achievement,
    Certification,
    Contact,
    Course,
    CustomEvent,
    Education,
    Language,
    Presentation,
    Project,
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
    WorkAuthorization,
)
from app.models.jobs import (
    ApplicationEvent,
    Company,
    InterviewArtifact,
    InterviewRound,
    TrackedJob,
)
from app.models.documents import DocumentEdit, GeneratedDocument, WritingSample
from app.models.companion import CompanionConversation, ConversationMessage, Task
from app.models.operational import AuditLog, AutofillLog, MetricSnapshot

__all__ = [
    "Base",
    "User",
    "Persona",
    "ApiCredential",
    "WorkExperience",
    "WorkExperienceSkill",
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
    "Company",
    "TrackedJob",
    "ApplicationEvent",
    "InterviewRound",
    "InterviewArtifact",
    "GeneratedDocument",
    "DocumentEdit",
    "WritingSample",
    "CompanionConversation",
    "ConversationMessage",
    "Task",
    "AuditLog",
    "AutofillLog",
    "MetricSnapshot",
]
