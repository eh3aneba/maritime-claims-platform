from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.modules.external_document_sources.observation_refresh_admission_execution_service as aj_service
import app.modules.external_document_sources.observation_refresh_admission_authorization_service as ai_service
import app.modules.external_document_sources.observation_refresh_execution_service as ah_service
import app.modules.external_document_sources.observation_review_decision_service as ag_service
import app.modules.external_document_sources.observation_review_handoff_service as af_service
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _prior_source_state,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
)
from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
    ExternalDocumentSourceObservationReviewDecisionReceipt,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
    ExternalDocumentSourceObservationReviewHandoffReceipt,
)
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingItem,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_due_tick_service_executor import _prepare
from tests.test_external_document_source_observation_refresh_admission_authorization import (
    _AUTH_REASON as _AI_AUTH_REASON,
)
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _EXEC_REASON,
    setup_function as _aj_setup,
    teardown_function as _aj_teardown,
)
from tests.test_external_document_source_observation_refresh_execution import _refresh_io
from tests.test_external_document_source_observation_review_decision import _changed_result


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_REFRESH_ADMISSION_EXEC_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "Phase AJ concurrency regression runs only in the dedicated PostgreSQL CI job"
    ),
)


def setup_function() -> None:
    _aj_setup()


def teardown_function() -> None:
    _aj_teardown()


def _seed_authorized_refresh(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    *,
    include_admission_authorization: bool = True,
):
    (
        actor_id,
        profile_id,
        _schedule_id,
        organization_id,
        document_id,
        dispatch_id,
        metadata_adapter,
    ) = _prepare(monkeypatch, suffix)
    metadata_adapter.result = _changed_result()

    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"

        binding = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            observation.binding_id,
        )
        current = db.get(Document, observation.current_document_id)
        assert binding is not None
        assert current is not None

        projected_at = datetime(2026, 9, 20, 0, 1, tzinfo=UTC)
        projector_id_hash = af_service._projector_hash(
            "external-evidence-review-projector-v1"
        )
        handoff = ExternalDocumentSourceObservationReviewHandoff(
            id=uuid4(),
            organization_id=observation.organization_id,
            claim_id=observation.claim_id,
            profile_id=observation.profile_id,
            observation_execution_id=observation.id,
            schedule_id=observation.schedule_id,
            binding_id=observation.binding_id,
            document_family_id=observation.document_family_id,
            observed_document_id=observation.current_document_id,
            observed_version_number=observation.current_version_number,
            provider_kind=observation.provider_kind,
            profile_hash=observation.profile_hash,
            stable_source_item_hash=observation.stable_source_item_hash,
            observation_completion_hash=observation.completion_hash,
            due_at=observation.due_at,
            result_status=observation.result_status,
            observed_projection_hash=observation.observed_projection_hash,
            observed_version_token_hash=observation.observed_version_token_hash,
            projector_id_hash=projector_id_hash,
            status="pending",
            projected_at=projected_at,
            scope_hash="",
            completion_hash="",
            **af_service._safety(),
        )
        handoff.scope_hash = af_service._scope_hash(
            observation=observation,
            projector_id_hash=projector_id_hash,
        )
        handoff.completion_hash = af_service._completion_hash(handoff)
        db.add(handoff)
        db.flush()

        handoff_receipt = ExternalDocumentSourceObservationReviewHandoffReceipt(
            id=uuid4(),
            organization_id=observation.organization_id,
            handoff_id=handoff.id,
            sequence_number=1,
            event_type="projected",
            status_after="pending",
            projector_id_hash=projector_id_hash,
            occurred_at=projected_at,
            scope_hash=handoff.scope_hash,
            decision_hash=handoff.completion_hash,
            receipt_hash="",
            **af_service._safety(),
        )
        handoff_receipt.receipt_hash = af_service._receipt_hash(handoff_receipt)
        db.add(handoff_receipt)
        db.flush()

        prior_projection_hash, prior_provider_version_hash = _prior_source_state(
            db,
            binding=binding,
            current_document=current,
        )
        decided_at = datetime(2026, 9, 21, 0, 2, tzinfo=UTC)
        decision_reason = (
            "Human reviewer authorizes one exact changed-item content refresh."
        )
        decision = ExternalDocumentSourceObservationReviewDecision(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=handoff.claim_id,
            profile_id=profile_id,
            handoff_id=handoff.id,
            observation_execution_id=handoff.observation_execution_id,
            schedule_id=handoff.schedule_id,
            binding_id=handoff.binding_id,
            document_family_id=handoff.document_family_id,
            current_document_id=current.id,
            current_version_number=current.version_number,
            current_document_file_hash=current.file_hash,
            result_status=handoff.result_status,
            provider_kind=handoff.provider_kind,
            profile_hash=handoff.profile_hash,
            stable_source_item_hash=handoff.stable_source_item_hash,
            handoff_completion_hash=handoff.completion_hash,
            binding_completion_hash=binding.completion_hash,
            prior_projection_hash=prior_projection_hash,
            prior_provider_version_hash=prior_provider_version_hash,
            observed_projection_hash=handoff.observed_projection_hash,
            observed_version_token_hash=handoff.observed_version_token_hash,
            request_key=f"{suffix}-approve",
            decision_kind="approve_refresh",
            status="refresh_authorized",
            decided_by_id=actor_id,
            decision_reason=decision_reason,
            decided_at=decided_at,
            scope_hash="",
            request_hash="",
            completion_hash="",
            **ag_service._safety(),
        )
        decision.scope_hash = ag_service._scope_hash(
            handoff=handoff,
            current=current,
            binding_completion_hash=binding.completion_hash,
            prior_projection_hash=prior_projection_hash,
            prior_provider_version_hash=prior_provider_version_hash,
            request_key=decision.request_key,
        )
        decision.request_hash = ag_service._request_hash(decision)
        decision.completion_hash = ag_service._completion_hash(decision)
        db.add(decision)
        db.flush()

        decision_receipt = ExternalDocumentSourceObservationReviewDecisionReceipt(
            id=uuid4(),
            organization_id=organization_id,
            decision_id=decision.id,
            sequence_number=1,
            event_type="approve_refresh",
            status_after="refresh_authorized",
            actor_id=actor_id,
            occurred_at=decided_at,
            reason=decision_reason,
            scope_hash=decision.scope_hash,
            decision_hash=decision.completion_hash,
            prior_receipt_hash=None,
            receipt_hash="",
            **ag_service._safety(),
        )
        decision_receipt.receipt_hash = ag_service._receipt_hash(decision_receipt)
        db.add(decision_receipt)
        db.flush()

        refresh_authorization = ExternalDocumentSourceObservationRefreshAuthorization(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=handoff.claim_id,
            profile_id=profile_id,
            handoff_id=handoff.id,
            decision_id=decision.id,
            binding_id=handoff.binding_id,
            document_family_id=handoff.document_family_id,
            current_document_id=current.id,
            current_version_number=current.version_number,
            current_document_file_hash=current.file_hash,
            provider_kind=handoff.provider_kind,
            profile_hash=handoff.profile_hash,
            stable_source_item_hash=handoff.stable_source_item_hash,
            handoff_completion_hash=handoff.completion_hash,
            decision_completion_hash=decision.completion_hash,
            binding_completion_hash=binding.completion_hash,
            result_status="changed",
            prior_projection_hash=prior_projection_hash,
            prior_provider_version_hash=prior_provider_version_hash,
            observed_projection_hash=handoff.observed_projection_hash,
            observed_version_token_hash=handoff.observed_version_token_hash,
            execution_limit=1,
            status="authorized",
            authorized_by_id=actor_id,
            authorized_at=decided_at,
            scope_hash="",
            authorization_hash="",
            **ag_service._safety(),
        )
        refresh_authorization.scope_hash = ag_service._authorization_scope_hash(
            refresh_authorization
        )
        refresh_authorization.authorization_hash = ag_service._authorization_hash(
            refresh_authorization
        )
        db.add(refresh_authorization)
        db.flush()

        profile = db.get(ExternalDocumentSourceProfile, profile_id)
        lineage = db.get(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution,
            observation.provider_lineage_observation_id,
        )
        assert profile is not None
        assert lineage is not None
        item = db.get(
            ExternalDocumentSourceRemoteMetadataListingItem,
            lineage.metadata_item_id,
        )
        assert item is not None

        changed_body, read_adapter, store = _refresh_io()
        policy = ah_service._read_policy(
            profile.provider_kind,
            profile.normalized_config,
            item,
        )
        read_adapter_kind = ah_service._normalize_identifier(
            read_adapter.adapter_kind,
            field="Observation refresh content adapter kind",
        )
        endpoint_policy_hash = ah_service._endpoint_policy_hash(policy)
        backend = store.sanitized_health_identity.backend

        execution_id = uuid5(
            NAMESPACE_URL,
            f"mcri:observation-refresh:{refresh_authorization.id}",
        )
        storage_key = ah_service._storage_key(
            refresh_authorization.id,
            execution_id,
        )
        storage_key_hash = hashlib.sha256(storage_key.encode("utf-8")).hexdigest()
        digest = hashlib.sha256(changed_body).hexdigest()
        store.put_bytes_if_absent(
            changed_body,
            storage_key=storage_key,
            expected_sha256=digest,
        )

        requested_at = datetime(2026, 9, 21, 1, 0, tzinfo=UTC)
        refresh_execution = ExternalDocumentSourceObservationRefreshExecution(
            id=execution_id,
            organization_id=organization_id,
            claim_id=refresh_authorization.claim_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization.id,
            decision_id=refresh_authorization.decision_id,
            handoff_id=refresh_authorization.handoff_id,
            observation_execution_id=observation.id,
            binding_id=refresh_authorization.binding_id,
            document_family_id=refresh_authorization.document_family_id,
            current_document_id=current.id,
            current_version_number=current.version_number,
            current_document_file_hash=current.file_hash,
            provider_kind=refresh_authorization.provider_kind,
            profile_hash=refresh_authorization.profile_hash,
            stable_source_item_hash=refresh_authorization.stable_source_item_hash,
            authorization_hash=refresh_authorization.authorization_hash,
            decision_completion_hash=decision.completion_hash,
            handoff_completion_hash=refresh_authorization.handoff_completion_hash,
            binding_completion_hash=refresh_authorization.binding_completion_hash,
            observed_projection_hash=refresh_authorization.observed_projection_hash,
            observed_version_token_hash=refresh_authorization.observed_version_token_hash,
            read_operation_kind=read_adapter.read_operation_kind,
            read_adapter_kind=read_adapter_kind,
            endpoint_policy_hash=endpoint_policy_hash,
            storage_backend_kind=backend,
            storage_purpose=ah_service.STORAGE_PURPOSE,
            storage_object_key=storage_key,
            storage_object_key_hash=storage_key_hash,
            content_sha256=digest,
            content_byte_count=len(changed_body),
            content_media_type_class=read_adapter.media,
            content_version_token_hash=read_adapter.version,
            content_proof_hash=ah_service._content_proof_hash(
                authorization_hash=refresh_authorization.authorization_hash,
                content_sha256=digest,
                content_byte_count=len(changed_body),
                media_type_class=read_adapter.media,
                version_token_hash=read_adapter.version,
                storage_object_key_hash=storage_key_hash,
            ),
            request_key=f"{suffix}-refresh",
            request_hash="",
            scope_hash="",
            status="completed",
            result_status="staged_refresh_verified",
            requested_by_id=actor_id,
            request_reason=(
                "Consume the approved changed-item refresh and stage the exact "
                "remote content before any Evidence admission authority exists."
            ),
            requested_at=requested_at,
            completed_at=requested_at,
            completion_hash="",
            **ah_service._safety(),
        )
        refresh_execution.scope_hash = ah_service._scope_hash(
            refresh_authorization,
            observation=observation,
            current_document_id=current.id,
            current_version_number=current.version_number,
            current_document_file_hash=current.file_hash,
            read_operation_kind=refresh_execution.read_operation_kind,
            read_adapter_kind=refresh_execution.read_adapter_kind,
            endpoint_policy_hash=refresh_execution.endpoint_policy_hash,
            storage_backend_kind=refresh_execution.storage_backend_kind,
            storage_object_key_hash=refresh_execution.storage_object_key_hash,
            request_key=refresh_execution.request_key,
        )
        refresh_execution.request_hash = ah_service._request_hash(
            scope_hash=refresh_execution.scope_hash,
            requested_by_id=actor_id,
            reason=refresh_execution.request_reason,
            requested_at=requested_at,
        )
        refresh_execution.completion_hash = ah_service._completion_hash(
            refresh_execution
        )
        db.add(refresh_execution)
        db.flush()

        refresh_receipt = ExternalDocumentSourceObservationRefreshReceipt(
            id=uuid4(),
            organization_id=organization_id,
            execution_id=refresh_execution.id,
            sequence_number=1,
            event_type="completed",
            status_after="completed",
            actor_id=actor_id,
            occurred_at=requested_at,
            reason=refresh_execution.request_reason,
            scope_hash=refresh_execution.scope_hash,
            decision_hash=refresh_execution.completion_hash,
            prior_receipt_hash=None,
            receipt_hash="",
            **ah_service._safety(),
        )
        refresh_receipt.receipt_hash = ah_service._receipt_hash(refresh_receipt)
        db.add(refresh_receipt)
        db.flush()

        if not include_admission_authorization:
            db.commit()
            return (
                actor_id,
                profile_id,
                organization_id,
                current.claim_id,
                document_id,
                refresh_execution.id,
                None,
                binding.id,
                metadata_adapter,
                read_adapter,
                store,
            )

        authorized_at = datetime(2026, 9, 22, 1, 0, tzinfo=UTC)
        authorization = ExternalDocumentSourceObservationRefreshAdmissionAuthorization(
            id=uuid4(),
            organization_id=organization_id,
            claim_id=refresh_execution.claim_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_execution.id,
            refresh_authorization_id=refresh_execution.authorization_id,
            decision_id=refresh_execution.decision_id,
            handoff_id=refresh_execution.handoff_id,
            binding_id=refresh_execution.binding_id,
            document_family_id=refresh_execution.document_family_id,
            expected_prior_document_id=current.id,
            expected_prior_version_number=current.version_number,
            provider_kind=refresh_execution.provider_kind,
            profile_hash=refresh_execution.profile_hash,
            stable_source_item_hash=refresh_execution.stable_source_item_hash,
            refresh_authorization_hash=refresh_execution.authorization_hash,
            refresh_completion_hash=refresh_execution.completion_hash,
            decision_completion_hash=refresh_execution.decision_completion_hash,
            handoff_completion_hash=refresh_execution.handoff_completion_hash,
            binding_completion_hash=refresh_execution.binding_completion_hash,
            observed_projection_hash=refresh_execution.observed_projection_hash,
            observed_version_token_hash=refresh_execution.observed_version_token_hash,
            prior_document_file_hash=current.file_hash,
            refreshed_content_sha256=refresh_execution.content_sha256,
            refreshed_content_byte_count=refresh_execution.content_byte_count,
            refreshed_content_media_type_class=refresh_execution.content_media_type_class,
            refreshed_content_version_token_hash=refresh_execution.content_version_token_hash,
            refreshed_content_proof_hash=refresh_execution.content_proof_hash,
            storage_backend_kind=refresh_execution.storage_backend_kind,
            storage_purpose=refresh_execution.storage_purpose,
            storage_object_key_hash=refresh_execution.storage_object_key_hash,
            request_key=f"{suffix}-ai-auth",
            scope_hash="",
            request_hash="",
            status="authorized",
            authorized_by_id=actor_id,
            authorization_reason=_AI_AUTH_REASON,
            authorized_at=authorized_at,
            authorization_hash="",
            **ai_service._safety(),
        )
        authorization.scope_hash = ai_service._scope_hash(
            refresh_execution,
            current,
            request_key=authorization.request_key,
        )
        authorization.request_hash = ai_service._request_hash(
            scope_hash=authorization.scope_hash,
            authorized_by_id=actor_id,
            reason=_AI_AUTH_REASON,
            authorized_at=authorized_at,
        )
        authorization.authorization_hash = ai_service._authorization_hash(
            authorization
        )
        db.add(authorization)
        db.flush()

        authorization_receipt = (
            ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt(
                id=uuid4(),
                organization_id=organization_id,
                authorization_id=authorization.id,
                sequence_number=1,
                event_type="authorized",
                status_after="authorized",
                actor_id=actor_id,
                occurred_at=authorized_at,
                reason=_AI_AUTH_REASON,
                scope_hash=authorization.scope_hash,
                decision_hash=authorization.authorization_hash,
                prior_receipt_hash=None,
                receipt_hash="",
                **ai_service._safety(),
            )
        )
        authorization_receipt.receipt_hash = ai_service._receipt_hash(
            authorization_receipt
        )
        db.add(authorization_receipt)
        db.commit()

        return (
            actor_id,
            profile_id,
            organization_id,
            current.claim_id,
            document_id,
            refresh_execution.id,
            authorization.id,
            binding.id,
            metadata_adapter,
            read_adapter,
            store,
        )


def _session_factory():
    engine = create_engine(
        os.environ["DATABASE_URL"],
        future=True,
        pool_pre_ping=True,
    )
    return engine, sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        class_=Session,
    )


def test_concurrent_aj_consumers_serialize_on_exact_ai_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _seed_authorized_refresh(monkeypatch, "aj-pg-race")

    monkeypatch.setattr(aj_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(
        aj_service,
        "validate_file_signature",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        aj_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(
            verdict=MalwareScanVerdict.CLEAN
        ),
    )

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(
                    ExternalDocumentSourceObservationRefreshAdmissionAuthorization
                )
                .where(
                    ExternalDocumentSourceObservationRefreshAdmissionAuthorization.id
                    == authorization_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_observation_refresh_admission(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        binding_id=binding_id,
                        authorization_id=authorization_id,
                        executed_by_id=actor_id,
                        request_key="aj-pg-blocked",
                        execution_reason=_EXEC_REASON,
                    )
                blocked_db.rollback()

            assert (
                lock_owner.query(
                    ExternalDocumentSourceObservationRefreshAdmissionExecution
                ).count()
                == 0
            )
            prior = lock_owner.get(Document, prior_document_id)
            assert prior is not None and prior.is_current is True
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            execution, outcome = execute_observation_refresh_admission(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-pg-winner",
                execution_reason=_EXEC_REASON,
            )
            assert outcome == "admitted"
            execution_id = execution.id
            new_document_id = execution.new_document_id

        with SessionLocal() as db:
            rows = db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).all()
            assert len(rows) == 1
            assert rows[0].id == execution_id
            assert rows[0].authorization_id == authorization_id

            prior = db.get(Document, prior_document_id)
            new = db.get(Document, new_document_id)
            assert prior is not None and new is not None
            assert prior.is_current is False
            assert new.is_current is True
            assert new.version_number == prior.version_number + 1
            assert new.supersedes_document_id == prior.id
            current = list(
                db.scalars(
                    select(Document).where(
                        Document.organization_id == organization_id,
                        Document.claim_id == new.claim_id,
                        Document.document_family_id == new.document_family_id,
                        Document.is_current.is_(True),
                        Document.deleted_at.is_(None),
                    )
                ).all()
            )
            assert len(current) == 1
            assert current[0].id == new.id
    finally:
        engine.dispose()
