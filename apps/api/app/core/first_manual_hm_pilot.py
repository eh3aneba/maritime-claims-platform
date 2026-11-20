"""Fail-closed configuration boundary for the FIRST manual H&M machinery pilot.

A configuration check is not a host, network-egress, tenant-isolation,
evidence-authenticity, security-owner or customer authorization attestation.
This first scope intentionally sacrifices machine OCR for source safety.
"""
from __future__ import annotations

from typing import Any


def first_manual_hm_pilot_errors(settings: Any) -> list[str]:
    """Static, secret-free rejections; call in APP_ENV=pilot startup preflight.

    Each optional capability must be *explicitly disabled* in parsed Settings.
    Missing attributes fail closed, rather than importing a fallback default
    from a test stub or an unreviewed future configuration contract.
    """
    errors: list[str] = []
    for key, expected, message in (
        ("ai_provider", "disabled", "First manual H&M pilot requires AI_PROVIDER=disabled"),
        ("ai_model", "", "First manual H&M pilot requires AI_MODEL to be empty"),
        ("openai_api_key", "", "First manual H&M pilot requires OPENAI_API_KEY to be empty"),
        ("allow_external_ai_restricted", False, "First manual H&M pilot forbids restricted external AI"),
        ("ai_local_experimental_enabled", False, "First manual H&M pilot forbids local AI experiments"),
        ("ai_production_control_plane_enabled", False, "First manual H&M pilot forbids production AI control plane"),
        ("external_evidence_live_provider_adapters_enabled", False,
         "First manual H&M pilot forbids live external evidence providers"),
        ("external_evidence_live_sftp_adapters_enabled", False,
         "First manual H&M pilot forbids live SFTP evidence ingestion"),
        ("ocr_enabled", False, "First manual H&M pilot requires OCR_ENABLED=false pending H&M source review"),
    ):
        value = getattr(settings, key, None)
        if type(value) is not type(expected) or value != expected:
            errors.append(message)
    return errors
