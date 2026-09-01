"""MIOS V5 stage engines.

Phase A: Stage 0 (health).
Phase B: adapter engines wrapping proven vob_minimal.py analytics
(re-expressed in the uniform contract) + DISABLED stubs for data-limited
stages.
"""

from .stage00_health import HealthEngine
from .stage02_structure import MarketStructureEngine
from .stage03_memory import MemoryEngine
from .stage04_context import MarketContextEngine
from .stage05_regime import RegimeEngine
from .stage06_timecycle import TimeCycleEngine
from .stage11_dealer import DealerEngine
from .stage12_options import OptionChainEngine
from .stage13_institutional import InstitutionalEngine
from .stage14_orderflow import OrderFlowEngine
from .stage15_microstructure import MicrostructureEngine
from .stage17_liquidity import LiquidityEngine
from .stage18_sector import SectorRotationEngine
from .stage19_global import GlobalEngine
from .stage20_macro import MacroEngine
from .stage21_news import NewsEngine
from .stage22_vix import VixEngine
from .stage23_flows import FlowsEngine
from .stage24_preparation import PreparationEngine
from .stage25_intent import IntentEngine
from .stage26_patterns import PatternAlignmentEngine
from .stage27_conflict import ConflictEngine
from .stage28_event_detection import EventDetectionEngine
from .stage29_evolution import EvolutionEngine
from .stage30_calendar import CalendarEngine
from .stage31_probability import ProbabilityEngine
from .stage33_event_impact import EventImpactEngine
from .stage34_explain import EventExplanationEngine
from .stage35_reaction_zone import ReactionZoneEngine
from .stage36_story import StoryEngine
from .stage38_tomorrow import TomorrowEngine
from .stage39_premarket import PreMarketEngine
from .stage40_learning import LearningEngine
from .stage37_energy import MarketEnergyEngine
from .stage42_acceptance import AcceptanceEngine
from .stage43_absorption import AbsorptionEngine
from .stage44_flow_shift import FlowShiftEngine
from .stage45_htf_vpfr import HTFVpfrEngine
from .stage47_transition import BiasTransitionEngine
from .stage48_market_state import MarketStateEngine
from .stage50_ltp_behaviour import LTPBehaviourEngine
from .stage51_validity import SignalValidityEngine
from .stage52_decision import DecisionEngineV2
from .stage54_memory import MarketMemoryEngine
from .stage53_evidence import EvidenceCorrelationEngine
from .stage68_day_type import MarketDayTypeEngine
from .stage69_session import SessionIntelligenceEngine

#: registered in this order (topo sort re-orders by deps anyway)
ALL_ENGINES = [
    HealthEngine,
    MarketStructureEngine,
    MemoryEngine,
    MarketContextEngine,
    RegimeEngine,
    TimeCycleEngine,
    DealerEngine,
    OptionChainEngine,
    InstitutionalEngine,
    OrderFlowEngine,
    MicrostructureEngine,
    LiquidityEngine,
    SectorRotationEngine,
    GlobalEngine,
    MacroEngine,
    NewsEngine,
    VixEngine,
    FlowsEngine,
    PreparationEngine,
    IntentEngine,
    PatternAlignmentEngine,
    ProbabilityEngine,
    ConflictEngine,
    EventDetectionEngine,
    CalendarEngine,
    EventExplanationEngine,
    EventImpactEngine,
    ReactionZoneEngine,
    EvolutionEngine,
    StoryEngine,
    TomorrowEngine,
    PreMarketEngine,
    LearningEngine,
    MarketEnergyEngine,
    AcceptanceEngine,
    AbsorptionEngine,
    FlowShiftEngine,
    HTFVpfrEngine,
    BiasTransitionEngine,
    LTPBehaviourEngine,
    MarketStateEngine,
    SignalValidityEngine,
    EvidenceCorrelationEngine,
    MarketMemoryEngine,
    MarketDayTypeEngine,
    SessionIntelligenceEngine,
    DecisionEngineV2,
]

__all__ = [
    "HealthEngine", "MarketStructureEngine", "MemoryEngine", "MarketContextEngine",
    "RegimeEngine", "TimeCycleEngine",
    "DealerEngine", "OptionChainEngine", "InstitutionalEngine",
    "OrderFlowEngine", "MicrostructureEngine", "GlobalEngine", "MacroEngine",
    "NewsEngine", "IntentEngine", "ConflictEngine", "EvolutionEngine",
    "ProbabilityEngine", "ReactionZoneEngine", "StoryEngine", "TomorrowEngine",
    "PreMarketEngine", "LearningEngine", "MarketEnergyEngine", "AcceptanceEngine", "AbsorptionEngine", "FlowShiftEngine", "HTFVpfrEngine", "BiasTransitionEngine", "LTPBehaviourEngine", "MarketStateEngine", "SignalValidityEngine", "EvidenceCorrelationEngine", "MarketMemoryEngine", "MarketDayTypeEngine", "SessionIntelligenceEngine", "DecisionEngineV2", "LiquidityEngine", "VixEngine",
    "FlowsEngine", "PatternAlignmentEngine", "SectorRotationEngine",
    "PreparationEngine", "EventDetectionEngine", "CalendarEngine",
    "EventExplanationEngine", "EventImpactEngine", "ALL_ENGINES",
]
