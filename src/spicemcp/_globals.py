"""Module-level server state, initialized at startup via server lifespan."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spicemcp.config import SpiceMCPConfig
    from spicemcp.core.session_manager import SessionManager

config: "SpiceMCPConfig | None" = None
manager: "SessionManager | None" = None
