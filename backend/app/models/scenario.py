"""
Scenario dataclasses for description-based simulation flow.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any


@dataclass
class AgentGroup:
    """Definition of a single agent group within a scenario."""
    name: str                      # snake_case identifier, e.g. "normal_users"
    label: str                     # human-readable label, e.g. "Normal Social Media Users"
    count: int                     # number of agents in this group
    percentage: float              # fraction of total agents (0.0–1.0)
    behavior_description: str      # what agents in this group post/do
    communication_style: str       # "independent" | "coordinate_within_group" | "broadcast"
    interacts_with: List[str] = field(default_factory=list)  # other group names they target
    sentiment_bias: float = 0.0    # -1.0 (hostile) to 1.0 (positive)
    activity_level: float = 0.5    # 0.0 (very inactive) to 1.0 (very active)
    stance: str = "neutral"        # "neutral" | "supportive" | "opposing" | "disruptive"
    active_hours_hint: str = "all day"  # "all day" | "late night" | "business hours" | "morning" | "evening"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioDefinition:
    """Complete scenario definition parsed from a free-form description."""
    title: str
    total_agents: int
    theme: str
    groups: List[AgentGroup] = field(default_factory=list)
    original_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "total_agents": self.total_agents,
            "theme": self.theme,
            "original_description": self.original_description,
            "groups": [g.to_dict() for g in self.groups],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioDefinition":
        groups = [
            AgentGroup(
                name=g.get("name", "group"),
                label=g.get("label", g.get("name", "Group")),
                count=int(g.get("count", 0)),
                percentage=float(g.get("percentage", 0.0)),
                behavior_description=g.get("behavior_description", ""),
                communication_style=g.get("communication_style", "independent"),
                interacts_with=g.get("interacts_with", []),
                sentiment_bias=float(g.get("sentiment_bias", 0.0)),
                activity_level=float(g.get("activity_level", 0.5)),
                stance=g.get("stance", "neutral"),
                active_hours_hint=g.get("active_hours_hint", "all day"),
            )
            for g in data.get("groups", [])
        ]
        return cls(
            title=data.get("title", "Untitled Scenario"),
            total_agents=int(data.get("total_agents", sum(g.count for g in groups))),
            theme=data.get("theme", ""),
            groups=groups,
            original_description=data.get("original_description", ""),
        )
