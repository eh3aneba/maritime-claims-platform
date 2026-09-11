"""Import all SQLAlchemy models so Alembic can discover application metadata."""

from app.db.base import Base
from app.modules.adjustments.models import AdjustmentLine, AdjustmentStatement  # noqa: F401
from app.modules.ai_bounded_full_production.models import AIBoundedFullProductionApproval, AIBoundedFullProductionAuthorization, AIBoundedFullProductionDocumentEligibility, AIBoundedFullProductionIncident, AIBoundedFullProductionMonitor, AIBoundedFullProductionRun  # noqa: F401
from app.modules.ai_bounded_full_production_outcomes.models import AIBoundedFullProductionOutcomeAssessment, AIBoundedFullProductionOutcomeBusinessEvidence, AIBoundedFullProductionOutcomeEnterpriseEvidence, AIBoundedFullProductionOutcomeObservation, AIBoundedFullProductionOutcomeReview  # noqa: F401
from app.modules.ai_broader_production.models import AIBroaderProductionApproval, AIBroaderProductionAuthorization, AIBroaderProductionDocumentEligibility, AIBroaderProductionIncident, AIBroaderProductionMonitor, AIBroaderProductionRun  # noqa: F401
from app.modules.ai_broader_production_outcomes.models import AIBroaderProductionOutcomeAssessment, AIBroaderProductionOutcomeObservation, AIBroaderProductionOutcomeReview  # noqa: F401
from app.modules.ai_evaluation.models import AIEvaluationCaseResult, AIEvaluationReview, AIEvaluationSuite  # noqa: F401
from app.modules.ai_final_production.models import AIFinalProductionApproval, AIFinalProductionAuthorization, AIFinalProductionDocumentEligibility, AIFinalProductionIncident, AIFinalProductionMonitor, AIFinalProductionRun  # noqa: F401
from app.modules.ai_final_production_outcomes.models import AIFinalProductionOutcomeAssessment, AIFinalProductionOutcomeBusinessEvidence, AIFinalProductionOutcomeObservation, AIFinalProductionOutcomeReview  # noqa: F401
from app.modules.ai_final_production_readiness.models import AIFinalProductionReadinessAssessment, AIFinalProductionReadinessClaimEvidence, AIFinalProductionReadinessControlEvidence, AIFinalProductionReadinessReview  # noqa: F401
from app.modules.ai_governance.models import AIDocumentEligibilityAttestation, AIProviderActivationApproval, AIProviderActivationRequest  # noqa: F401
from app.modules.ai_high_coverage.models import AIHighCoverageApproval, AIHighCoverageAuthorization, AIHighCoverageDocumentEligibility, AIHighCoverageIncident, AIHighCoverageMonitor, AIHighCoverageRun  # noqa: F401
from app.modules.ai_high_coverage_outcomes.models import AIHighCoverageOutcomeAssessment, AIHighCoverageOutcomeObservation, AIHighCoverageOutcomeReview  # noqa: F401
from app.modules.ai_limited_production.models import AILimitedProductionApproval, AILimitedProductionAuthorization, AILimitedProductionDocumentEligibility, AILimitedProductionIncident, AILimitedProductionMonitor, AILimitedProductionRun  # noqa: F401
from app.modules.ai_limited_production_outcomes.models import AILimitedProductionOutcomeAssessment, AILimitedProductionOutcomeObservation, AILimitedProductionOutcomeReview  # noqa: F401
from app.modules.ai_near_universal_outcomes.models import AINearUniversalOutcomeAssessment, AINearUniversalOutcomeBusinessEvidence, AINearUniversalOutcomeObservation, AINearUniversalOutcomeReview  # noqa: F401
from app.modules.ai_near_universal_production.models import AINearUniversalApproval, AINearUniversalAuthorization, AINearUniversalDocumentEligibility, AINearUniversalIncident, AINearUniversalMonitor, AINearUniversalRun  # noqa: F401
from app.modules.ai_pilot_outcomes.models import AIPilotOutcomeAssessment, AIPilotOutcomeReview, AIPilotWorkflowObservation  # noqa: F401
from app.modules.ai_private_pilot.models import AIPrivatePilotApproval, AIPrivatePilotAuthorization, AIPrivatePilotDocumentEligibility, AIPrivatePilotIncident, AIPrivatePilotRun  # noqa: F401
from app.modules.ai_production_wide.models import AIProductionDecisionLog, AIProductionEligibilityDecision, AIProductionWideApproval, AIProductionWideAuthorization, AIProductionWideIncident, AIProductionWideMonitor  # noqa: F401
from app.modules.ai_scale_up.models import AIScaleUpApproval, AIScaleUpAuthorization, AIScaleUpDocumentEligibility, AIScaleUpIncident, AIScaleUpMonitor, AIScaleUpRun  # noqa: F401
from app.modules.ai_scale_up_outcomes.models import AIScaleUpOutcomeAssessment, AIScaleUpOutcomeObservation, AIScaleUpOutcomeReview  # noqa: F401
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.auth.models import AuthSession, EnterpriseIdentityProvider, ExternalIdentityBinding  # noqa: F401
from app.modules.assessments.models import InitialAssessment, AssessmentSection  # noqa: F401
from app.modules.claim_intelligence.models import ClaimIntelligenceItem, ClaimIntelligenceItemDecision, ClaimIntelligenceSnapshot  # noqa: F401
from app.modules.claim_packs.models import ClaimPackExport  # noqa: F401
from app.modules.claims.models import Claim, ClaimReferenceSequence  # noqa: F401
from app.modules.claims.facts import ClaimFact  # noqa: F401
from app.modules.chronology.models import ChronologyEvent, EventEvidence, EvidenceConflict  # noqa: F401
from app.modules.correspondence.models import ClaimCorrespondence  # noqa: F401
from app.modules.documents.models import Document, QuarantinedUpload  # noqa: F401
from app.modules.documents.recovery_authority_switch_models import EvidenceRecoveryAuthoritySwitchReceipt, EvidenceRecoveryAuthoritySwitchRehearsal  # noqa: F401
from app.modules.documents.recovery_cutover_admission_models import EvidenceRecoveryCutoverAdmission, EvidenceRecoveryCutoverAdmissionReceipt  # noqa: F401
from app.modules.documents.recovery_cutover_execution_models import EvidenceRecoveryCutoverExecutionLease, EvidenceRecoveryCutoverExecutionReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_health_models import EvidenceRecoveryDurableReadHealthQualification, EvidenceRecoveryDurableReadHealthQualificationReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_models import EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification, EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_models import EvidenceRecoveryDurableReadReauthorizedRenewalLease, EvidenceRecoveryDurableReadReauthorizedRenewalReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_renewal_health_models import EvidenceRecoveryDurableReadRenewalHealthQualification, EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_renewal_models import EvidenceRecoveryDurableReadRenewalAuthorization, EvidenceRecoveryDurableReadRenewalAuthorizationReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_renewal_reauthorization_models import EvidenceRecoveryDurableReadRenewalReauthorization, EvidenceRecoveryDurableReadRenewalReauthorizationReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_renewal_routing_models import EvidenceRecoveryDurableReadRenewalLease, EvidenceRecoveryDurableReadRenewalReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_promotion_models import EvidenceRecoveryDurableReadPromotionAuthorization, EvidenceRecoveryDurableReadPromotionAuthorizationReceipt  # noqa: F401
from app.modules.documents.recovery_durable_read_routing_models import EvidenceRecoveryDurableReadPromotionLease, EvidenceRecoveryDurableReadPromotionReceipt  # noqa: F401
from app.modules.documents.recovery_read_ownership_transition_authorization_models import EvidenceRecoveryReadOwnershipTransitionAuthorization, EvidenceRecoveryReadOwnershipTransitionAuthorizationReceipt  # noqa: F401
from app.modules.documents.recovery_read_ownership_transition_routing_models import EvidenceRecoveryReadOwnershipTransitionLease, EvidenceRecoveryReadOwnershipTransitionReceipt  # noqa: F401
from app.modules.documents.recovery_read_path_cutover_models import EvidenceRecoveryReadPathCutoverAuthorization, EvidenceRecoveryReadPathCutoverAuthorizationReceipt  # noqa: F401
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathCutoverLease, EvidenceRecoveryReadPathCutoverReceipt, EvidenceRecoveryReadPathRoute  # noqa: F401
from app.modules.documents.recovery_routable_read_qualification_models import EvidenceRecoveryRoutableReadQualification, EvidenceRecoveryRoutableReadQualificationReceipt  # noqa: F401
from app.modules.documents.recovery_promotion_models import EvidenceRecoveryPromotionAttestation  # noqa: F401
from app.modules.documents.recovery_replication_models import EvidenceRecoveryReplica, EvidenceRecoveryVerification  # noqa: F401
from app.modules.documents.recovery_restore_models import EvidenceRecoveryRestoreRehearsal, EvidenceRecoveryRestoreVerification  # noqa: F401
from app.modules.documents.recovery_shadow_models import EvidenceRecoveryShadowPromotion, EvidenceRecoveryShadowVerification  # noqa: F401
from app.modules.email_ingestion.models import EmailAdapterRun, EmailAttachmentManifest, EmailIngestionConnection, EmailProviderAdapter, EmailRetentionRun, IngestedEmailMessage  # noqa: F401
from app.modules.evidence_search.models import ClaimEvidenceSearchRun, ClaimEvidenceSearchUnit  # noqa: F401
from app.modules.evidence_search.qa_synthesis_models import ClaimQaSynthesisRun  # noqa: F401
from app.modules.external_portal.models import ExternalPortalInvitation, ExternalPortalPublicationProposal, ExternalPortalPublishedItem, ExternalPortalSession, ExternalPortalSubmission  # noqa: F401
from app.modules.governance_webhooks.models import GovernanceWebhookDelivery, GovernanceWebhookDestination  # noqa: F401
from app.modules.intelligence.models import AIFeedback, AIRun, DocumentExtraction  # noqa: F401
from app.modules.intake.models import ClaimIntakeDraft, ClaimIntakeProcessingJob  # noqa: F401
from app.modules.financial.models import CostItem, FinancialFlag, ReserveHistory  # noqa: F401
from app.modules.organizations.models import Organization  # noqa: F401
from app.modules.outreach.models import DesignPartnerAccount, DesignPartnerContact, OutreachTouch, PaidPilotOffer  # noqa: F401
from app.modules.processing.models import DocumentProcessingJob, DocumentTextExtraction, DocumentTextSegment  # noqa: F401
from app.modules.pilot.models import PilotCommercialValidation, PilotEvent, PilotFeedback, PilotSession  # noqa: F401
from app.modules.pilot_operations.models import DeploymentReadinessReview, DesignPartnerRehearsal, OperationalAcceptance, OperationalAcceptanceApproval, OperationalAcceptanceCheck, OperationalIncident, OperationalMonitorRun, PilotExitManifest, PilotGovernanceProfile, PrivatePilotCaseRun, PrivatePilotExecution, ProductGapFinding, ProductionArchitectureBaseline, ProductionArchitectureControl, ProductionControlEvidence, ProductionControlVerificationGate, RehearsalControlEvidence, RehearsalRemediationFinding  # noqa: F401
from app.modules.recovery_timebar.models import RecoveryTimebarDecision, RecoveryTimebarEvaluation, RecoveryTimebarSnapshot  # noqa: F401
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RuleEvaluationRun  # noqa: F401
from app.modules.rules.requirement_lineage import ClaimDocumentRequirementDecision, ClaimDocumentRequirementState  # noqa: F401
from app.modules.settlements.models import PaymentAuthorization, SettlementProposal  # noqa: F401
from app.modules.severity_reserve.models import SeverityReserveDecision, SeverityReserveEvaluation, SeverityReserveSnapshot  # noqa: F401
from app.modules.tasks.models import ClaimTask, DocumentRequestBatch  # noqa: F401
from app.modules.technical.models import TechnicalInvestigationDecision  # noqa: F401
from app.modules.users.models import User  # noqa: F401
from app.modules.vessels.models import Vessel  # noqa: F401

__all__ = ["Base"]