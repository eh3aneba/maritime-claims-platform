"""Import all SQLAlchemy models so Alembic can discover application metadata."""

from app.db.base import Base
from app.modules.adjustments.models import AdjustmentLine, AdjustmentStatement  # noqa: F401
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.assessments.models import InitialAssessment, AssessmentSection  # noqa: F401
from app.modules.claim_packs.models import ClaimPackExport  # noqa: F401
from app.modules.claims.models import Claim, ClaimReferenceSequence  # noqa: F401
from app.modules.claims.facts import ClaimFact  # noqa: F401
from app.modules.chronology.models import ChronologyEvent, EventEvidence, EvidenceConflict  # noqa: F401
from app.modules.correspondence.models import ClaimCorrespondence  # noqa: F401
from app.modules.documents.models import Document, QuarantinedUpload  # noqa: F401
from app.modules.intelligence.models import AIFeedback, AIRun, DocumentExtraction  # noqa: F401
from app.modules.intake.models import ClaimIntakeDraft, ClaimIntakeProcessingJob  # noqa: F401
from app.modules.financial.models import CostItem, FinancialFlag, ReserveHistory  # noqa: F401
from app.modules.organizations.models import Organization  # noqa: F401
from app.modules.outreach.models import DesignPartnerAccount, DesignPartnerContact, OutreachTouch, PaidPilotOffer  # noqa: F401
from app.modules.processing.models import DocumentProcessingJob, DocumentTextExtraction, DocumentTextSegment  # noqa: F401
from app.modules.pilot.models import PilotCommercialValidation, PilotEvent, PilotFeedback, PilotSession  # noqa: F401
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RuleEvaluationRun  # noqa: F401
from app.modules.settlements.models import PaymentAuthorization, SettlementProposal  # noqa: F401
from app.modules.tasks.models import ClaimTask, DocumentRequestBatch  # noqa: F401
from app.modules.users.models import User  # noqa: F401
from app.modules.vessels.models import Vessel  # noqa: F401

__all__ = ["Base"]
