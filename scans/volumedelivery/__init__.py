"""
Volume & Delivery Analysis Module (AlphaQuant).
Provides tools for analyzing daily, weekly, and monthly volume/delivery trends,
detecting spikes, and generating accumulation/distribution signals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scans.volumedelivery.main import VolumeDeliveryEngine as VolumeDeliveryEngine
from scans.volumedelivery.models import TickerVolumeDeliveryData, VolumeDeliveryResult

__all__ = [
    "VolumeDeliveryEngine",
    "TickerVolumeDeliveryData",
    "VolumeDeliveryResult"
]


def __getattr__(name: str) -> Any:
    if name == "VolumeDeliveryEngine":
        from scans.volumedelivery.main import VolumeDeliveryEngine

        return VolumeDeliveryEngine
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")