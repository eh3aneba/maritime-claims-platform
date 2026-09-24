from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceValidationError,
    _normalize_sftp_hostname,
    _normalize_sftp_port,
)


@dataclass(frozen=True)
class SftpDestinationPolicy:
    approved_hostname: str
    approved_port: int
    allow_private_networks: bool = False

    @classmethod
    def from_approved_destination(
        cls,
        *,
        hostname: str,
        port: int,
        allow_private_networks: bool = False,
    ) -> "SftpDestinationPolicy":
        return cls(
            approved_hostname=_normalize_sftp_hostname(hostname),
            approved_port=_normalize_sftp_port(port),
            allow_private_networks=bool(allow_private_networks),
        )


def validate_sftp_resolved_destination(
    *,
    policy: SftpDestinationPolicy,
    hostname: str,
    port: int,
    resolved_addresses: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    normalized_hostname = _normalize_sftp_hostname(hostname)
    normalized_port = _normalize_sftp_port(port)

    if normalized_hostname != policy.approved_hostname:
        raise ExternalDocumentSourceValidationError(
            "SFTP destination hostname does not match the approved profile"
        )
    if normalized_port != policy.approved_port:
        raise ExternalDocumentSourceValidationError(
            "SFTP destination port does not match the approved profile"
        )
    if not resolved_addresses:
        raise ExternalDocumentSourceValidationError(
            "SFTP destination resolution returned no addresses"
        )

    normalized: set[str] = set()
    for raw in resolved_addresses:
        try:
            address = ip_address(str(raw).strip())
        except ValueError as exc:
            raise ExternalDocumentSourceValidationError(
                "SFTP destination resolution returned an invalid IP address"
            ) from exc

        if (
            address.is_unspecified
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        ):
            raise ExternalDocumentSourceValidationError(
                "SFTP destination address is prohibited by network policy"
            )

        if address.is_private and not policy.allow_private_networks:
            raise ExternalDocumentSourceValidationError(
                "SFTP private-network destinations are disabled by deployment policy"
            )

        if not address.is_private and not address.is_global:
            raise ExternalDocumentSourceValidationError(
                "SFTP destination address is not globally routable"
            )

        normalized.add(str(address))

    if not normalized:
        raise ExternalDocumentSourceValidationError(
            "SFTP destination resolution returned no usable addresses"
        )

    return tuple(sorted(normalized))
