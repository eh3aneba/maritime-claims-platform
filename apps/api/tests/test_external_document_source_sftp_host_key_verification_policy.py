import pytest

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_host_key_verification_policy import (
    SftpDestinationPolicy,
    validate_sftp_resolved_destination,
)


def _policy(*, allow_private: bool = False) -> SftpDestinationPolicy:
    return SftpDestinationPolicy.from_approved_destination(
        hostname="sftp.example.com",
        port=22,
        allow_private_networks=allow_private,
    )


def test_sftp_destination_policy_accepts_exact_public_destination() -> None:
    result = validate_sftp_resolved_destination(
        policy=_policy(),
        hostname="SFTP.EXAMPLE.COM.",
        port=22,
        resolved_addresses=["8.8.8.8", "2001:4860:4860::8888", "8.8.8.8"],
    )
    assert result == ("2001:4860:4860::8888", "8.8.8.8")


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.0",
        "::",
        "127.0.0.1",
        "::1",
        "169.254.10.20",
        "fe80::1",
        "224.0.0.1",
        "ff02::1",
        "240.0.0.1",
    ],
)
def test_sftp_destination_policy_always_rejects_special_addresses(
    address: str,
) -> None:
    with pytest.raises(ExternalDocumentSourceValidationError):
        validate_sftp_resolved_destination(
            policy=_policy(allow_private=True),
            hostname="sftp.example.com",
            port=22,
            resolved_addresses=[address],
        )


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.10",
        "172.16.0.10",
        "192.168.1.10",
        "fc00::10",
    ],
)
def test_sftp_destination_policy_denies_private_networks_by_default(
    address: str,
) -> None:
    with pytest.raises(ExternalDocumentSourceValidationError):
        validate_sftp_resolved_destination(
            policy=_policy(),
            hostname="sftp.example.com",
            port=22,
            resolved_addresses=[address],
        )


def test_sftp_destination_policy_allows_private_only_with_deployment_policy() -> None:
    result = validate_sftp_resolved_destination(
        policy=_policy(allow_private=True),
        hostname="sftp.example.com",
        port=22,
        resolved_addresses=["10.20.30.40"],
    )
    assert result == ("10.20.30.40",)


def test_sftp_destination_policy_rejects_mixed_public_private_resolution() -> None:
    with pytest.raises(ExternalDocumentSourceValidationError):
        validate_sftp_resolved_destination(
            policy=_policy(),
            hostname="sftp.example.com",
            port=22,
            resolved_addresses=["8.8.8.8", "10.0.0.5"],
        )


def test_sftp_destination_policy_rejects_destination_retargeting() -> None:
    with pytest.raises(ExternalDocumentSourceValidationError):
        validate_sftp_resolved_destination(
            policy=_policy(),
            hostname="other.example.com",
            port=22,
            resolved_addresses=["8.8.8.8"],
        )

    with pytest.raises(ExternalDocumentSourceValidationError):
        validate_sftp_resolved_destination(
            policy=_policy(),
            hostname="sftp.example.com",
            port=2222,
            resolved_addresses=["8.8.8.8"],
        )


def test_sftp_destination_policy_rejects_empty_or_invalid_resolution() -> None:
    with pytest.raises(ExternalDocumentSourceValidationError):
        validate_sftp_resolved_destination(
            policy=_policy(),
            hostname="sftp.example.com",
            port=22,
            resolved_addresses=[],
        )

    with pytest.raises(ExternalDocumentSourceValidationError):
        validate_sftp_resolved_destination(
            policy=_policy(),
            hostname="sftp.example.com",
            port=22,
            resolved_addresses=["not-an-ip"],
        )
