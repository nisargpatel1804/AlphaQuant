from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from scans.futureoptions.main import FOEngine as FOEngine
from scans.futureoptions.models import TickerFOData

__all__ = ["FOEngine", "TickerFOData"]


def __getattr__(name: str) -> Any:
	if name == "FOEngine":
		from scans.futureoptions.main import FOEngine

		return FOEngine
	raise AttributeError(f"module '{__name__}' has no attribute '{name}'")