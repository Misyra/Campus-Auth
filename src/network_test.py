"""Backward-compatible shim. All implementations moved to network_probes and network_decision."""
from src.network_probes import (
    _check_macos_service,
    is_local_network_connected,
    is_network_available_http,
    is_network_available_socket,
    set_block_proxy,
)
from src.network_decision import (
    check_campus_network_status,
    check_login_prerequisites,
    check_network_status,
    check_pause,
    is_network_available,
)

__all__ = [
    "_check_macos_service",
    "is_local_network_connected",
    "is_network_available_http",
    "is_network_available_socket",
    "set_block_proxy",
    "check_campus_network_status",
    "check_login_prerequisites",
    "check_network_status",
    "check_pause",
    "is_network_available",
]
