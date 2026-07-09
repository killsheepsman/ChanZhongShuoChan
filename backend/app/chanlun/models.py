from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Direction = Literal["up", "down"]
FractalKind = Literal["top", "bottom"]
SignalSide = Literal["buy", "sell"]
SignalStatus = Literal["candidate", "confirmed", "invalidated"]
SegmentStatus = Literal["IS_RUNNING", "CONFIRMED"]


@dataclass(frozen=True)
class KLine:
    index: int
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0


@dataclass(frozen=True)
class Fractal:
    index: int
    time: str
    kind: FractalKind
    price: float
    high: float
    low: float


@dataclass(frozen=True)
class Stroke:
    start_index: int
    end_index: int
    start_time: str
    end_time: str
    start_price: float
    end_price: float
    direction: Direction
    high: float
    low: float


@dataclass(frozen=True)
class Segment:
    id: int
    start_index: int
    end_index: int
    start_time: str
    end_time: str
    start_price: float
    end_price: float
    direction: Direction
    high: float
    low: float
    stroke_ids: list[int]
    status: SegmentStatus = "CONFIRMED"


@dataclass(frozen=True)
class Center:
    id: int
    start_index: int
    end_index: int
    start_time: str
    end_time: str
    zg: float
    zd: float
    gg: float
    dd: float
    segment_ids: list[int]


@dataclass(frozen=True)
class Divergence:
    segment_id: int
    side: SignalSide
    kind: Literal["trend", "consolidation"]
    strength: float
    reason: str


@dataclass(frozen=True)
class BuySellSignal:
    id: str
    side: SignalSide
    type: int
    index: int
    time: str
    price: float
    status: SignalStatus
    confidence: float
    reason: str
    center_id: int | None = None
    segment_id: int | None = None
