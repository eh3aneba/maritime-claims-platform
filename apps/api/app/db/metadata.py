"""Import all SQLAlchemy models so Alembic can discover application metadata."""

from app.db.base import Base
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.claims.models import Claim, ClaimReferenceSequence  # noqa: F401
from app.modules.claims.facts import ClaimFact  # noqa: F401
from app.modules.documents.models import Document  # noqa: F401
from app.modules.intelligence.models import AIFeedback, AIRun, DocumentExtraction  # noqa: F401
from app.modules.organizations.models import Organization  # noqa: F401
from app.modules.processing.models import DocumentProcessingJob, DocumentTextExtraction, DocumentTextSegment  # noqa: F401
from app.modules.users.models import User  # noqa: F401
from app.modules.vessels.models import Vessel  # noqa: F401

__all__ = ["Base"]
