"""
SimpleContext v4
~~~~~~~~~~~~~~~~
Universal AI Brain — Tiered Memory, Context Planning, Smart Retrieval.
Zero external dependencies. Fully backward compatible.
"""

from .core import SimpleContext, ChatContext
from .memory import Memory, TieredMemory, TierView
from .skills import Skills, SkillGroup
from .plugins.base import BasePlugin
from .config.schema import Config
from .agent.schema import AgentDef
from .agent.registry import AgentRegistry
from .agent.router import AgentRouter, RouteResult
from .context.node import ContextNode
from .context.planner import ContextPlanner, RetrievalPlan
from .context.engine import ContextEngine
from .context.builder import PromptBuilder
from .context.processor import MemoryProcessor, ProcessTurn
from .enums import Tier, NodeKind, NodeStatus, Intent

__version__ = "4.0.0"
from .context.fuzzy    import FuzzyRetriever
from .context.graph    import GraphStore, Relationship
from .context.patterns import PatternDetector
from .context.adaptive import AdaptiveScorer
from .context.processor import SmartCompressor

__all__ = [
    "SimpleContext", "ChatContext",
    "Memory", "TieredMemory", "TierView",
    "Skills", "SkillGroup",
    "BasePlugin",
    "Config",
    "AgentDef", "AgentRegistry", "AgentRouter", "RouteResult",
    "ContextNode", "ContextPlanner", "RetrievalPlan",
    "ContextEngine", "PromptBuilder",
    "MemoryProcessor", "ProcessTurn",
    "Tier", "NodeKind", "NodeStatus", "Intent",
    "FuzzyRetriever", "GraphStore", "Relationship",
    "PatternDetector", "AdaptiveScorer", "SmartCompressor",
]
