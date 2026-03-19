"""
OASIS Simulation Manager
Manage Twitter and Reddit dual-platform parallel simulations
Use preset scripts + LLM intelligent generation of config parameters
"""

import os
import json
import shutil
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .entity_reader import EntityReader, FilteredEntities
from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """Simulation status"""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # Simulation manually stopped
    COMPLETED = "completed"  # Simulation completed naturally
    FAILED = "failed"


class PlatformType(str, Enum):
    """Platform type"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """Simulation status"""
    simulation_id: str
    project_id: str
    graph_id: str
    
    # Platform enabled state
    enable_twitter: bool = True
    enable_reddit: bool = True

    # Simulation mode
    simulation_mode: str = "oasis"  # "oasis" | "sms"

    # Status
    status: SimulationStatus = SimulationStatus.CREATED
    
    # Preparation phase data
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # Config generation information
    config_generated: bool = False
    config_reasoning: str = ""
    
    # Runtime data
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Error message
    error: Optional[str] = None

    # Description-based flow fields (sentinel values for document flow)
    scenario_definition: Optional[Dict[str, Any]] = None  # parsed ScenarioDefinition dict
    total_agents: int = 0  # set from ScenarioDefinition.total_agents; 0 in document flow
    config_batch_current: int = 0  # current config-gen batch (description flow)
    config_batch_total: int = 0    # total config-gen batches (description flow)

    def to_dict(self) -> Dict[str, Any]:
        """Complete status dict (internal use)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "simulation_mode": self.simulation_mode,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "total_agents": self.total_agents,
            "scenario_definition": self.scenario_definition,
            "config_batch_current": self.config_batch_current,
            "config_batch_total": self.config_batch_total,
        }

    def to_simple_dict(self) -> Dict[str, Any]:
        """Simplified status dict (API return use)"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
            "total_agents": self.total_agents,
            "config_batch_current": self.config_batch_current,
            "config_batch_total": self.config_batch_total,
        }


class SimulationManager:
    """
    Simulation Manager
    
    Core Functions:
    1. Read entities from graph and filter
    2. Generate OASIS Agent Profile
    3. Use LLM intelligent generation of simulation config parameters
    4. Prepare all files required by preset scripts
    """
    
    # Simulation data storage directory
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), 
        '../../uploads/simulations'
    )
    
    def __init__(self):
        # Ensure directory exists
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # In-memory simulation state cache
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """Get simulation data directory"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """Save simulation state to file"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """Load simulation state from file"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            simulation_mode=data.get("simulation_mode", "oasis"),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
            total_agents=data.get("total_agents", 0),
            scenario_definition=data.get("scenario_definition"),
            config_batch_current=data.get("config_batch_current", 0),
            config_batch_total=data.get("config_batch_total", 0),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        Create new simulation
        
        Args:
            project_id: Project ID
            graph_id: Graph ID
            enable_twitter: Whether to enable Twitter simulation
            enable_reddit: Whether to enable Reddit simulation
            
        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"Create simulation: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3,
        storage: 'GraphStorage' = None,
    ) -> SimulationState:
        """
        Prepare simulation environment (fully automated)
        
        Steps:
        1. Read and filter entities from graph
        2. Generate OASIS Agent Profile for each entity (optional LLM enhancement, parallel support)
        3. Use LLM intelligent generation of simulation config parameters (time, activity, speaking frequency, etc.)
        4. Save config files and Profile files
        5. Copy preset scripts to simulation directory
        
        Args:
            simulation_id: Simulation ID
            simulation_requirement: Simulation requirement description (for LLM config generation)
            document_text: Original document content (for LLM background understanding)
            defined_entity_types: Predefined entity types (optional)
            use_llm_for_profiles: Whether to use LLM to generate detailed profiles
            progress_callback: Progress callback function (stage, progress, message)
            parallel_profile_count: Number of parallel profile generations, default 3
            
        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation does not exist: {simulation_id}")
        
        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)
            
            # ========== Phase 1: Read and filter entities ==========
            if progress_callback:
                progress_callback("reading", 0, "Connecting to graph...")

            if not storage:
                raise ValueError("storage (GraphStorage) is required for prepare_simulation")
            reader = EntityReader(storage)
            
            if progress_callback:
                progress_callback("reading", 30, "Reading node data...")
            
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )
            
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)
            
            if progress_callback:
                progress_callback(
                    "reading", 100, 
                    f"Completed, total {filtered.filtered_count} entities",
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )
            
            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "No entities matching criteria found, check if graph is correctly constructed"
                self._save_simulation_state(state)
                return state
            
            # ========== Phase 2: Generate Agent Profile ==========
            total_entities = len(filtered.entities)
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 0, 
                    "Starting generation...",
                    current=0,
                    total=total_entities
                )
            
            # Pass graph_id to enable graph retrieval functionality, get richer context
            generator = OasisProfileGenerator(storage=storage, graph_id=state.graph_id)
            
            def profile_progress(current, total, msg):
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 
                        int(current / total * 100), 
                        msg,
                        current=current,
                        total=total,
                        item_name=msg
                    )
            
            # Set real-time save file path (prefer Reddit JSON format)
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"
            
            profiles = generator.generate_profiles_from_entities(
                entities=filtered.entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=state.graph_id,  # Pass graph_id for graph retrieval
                parallel_count=parallel_profile_count,  # Parallel generation count
                realtime_output_path=realtime_output_path,  # Real-time save path
                output_platform=realtime_platform  # Output format
            )
            
            state.profiles_count = len(profiles)
            
            # Save Profile files (Note: Twitter uses CSV format, Reddit uses JSON format)
            # Reddit has been saved in real-time during generation, save once more here to ensure completeness
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95, 
                    "Saving Profile files...",
                    current=total_entities,
                    total=total_entities
                )
            
            if state.enable_reddit:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit"
                )
            
            if state.enable_twitter:
                # Twitter uses CSV format! This is OASIS requirement
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter"
                )
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 100, 
                    f"Completed, total {len(profiles)} Profiles",
                    current=len(profiles),
                    total=len(profiles)
                )
            
            # ========== Phase 3: LLM intelligent generation of simulation config ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0, 
                    "Analyzing simulation requirements...",
                    current=0,
                    total=3
                )
            
            config_generator = SimulationConfigGenerator()
            
            if progress_callback:
                progress_callback(
                    "generating_config", 30, 
                    "Calling LLM to generate config...",
                    current=1,
                    total=3
                )
            
            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit
            )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 70, 
                    "Saving config files...",
                    current=2,
                    total=3
                )
            
            # Save config files
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())
            
            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100, 
                    "Config generation completed",
                    current=3,
                    total=3
                )
            
            # Note: Run scripts remain in backend/scripts/ directory, no longer copy to simulation directory
            # When starting simulation, simulation_runner runs scripts from scripts/ directory
            
            # Update status
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"Simulation preparation completed: {simulation_id}, "
                       f"entities={state.entities_count}, profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"Simulation preparation failed: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    
    # ------------------------------------------------------------------
    # Description-based flow
    # ------------------------------------------------------------------

    def create_from_description(
        self,
        description: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> str:
        """
        Create a simulation from a free-form scenario description.

        This method is non-blocking: it creates the simulation record, fires a
        background thread to do the heavy work, and immediately returns the
        simulation_id.  The caller should poll GET /api/simulation/<id> and
        watch for status PREPARING → READY (or FAILED).

        Args:
            description: Free-form scenario description text.
            enable_twitter: Whether to enable the Twitter platform.
            enable_reddit:  Whether to enable the Reddit platform.

        Returns:
            simulation_id string.
        """
        import uuid
        import threading

        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"

        state = SimulationState(
            simulation_id=simulation_id,
            project_id="scenario_flow",
            graph_id="",
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.PREPARING,
        )
        self._save_simulation_state(state)
        logger.info(f"Created description-based simulation: {simulation_id}")

        thread = threading.Thread(
            target=self._prepare_from_description_async,
            args=(simulation_id, description, enable_twitter, enable_reddit),
            daemon=True,
        )
        thread.start()

        return simulation_id

    def _prepare_from_description_async(
        self,
        simulation_id: str,
        description: str,
        enable_twitter: bool,
        enable_reddit: bool,
    ) -> None:
        """
        Background thread: parse description → generate profiles → generate config.

        Updates SimulationState status at each milestone so the frontend can
        track progress via GET /api/simulation/<id>.
        """
        from .scenario_parser import ScenarioParser
        from .description_profile_generator import DescriptionProfileGenerator
        from .description_config_generator import DescriptionConfigGenerator

        state = self._load_simulation_state(simulation_id)

        try:
            sim_dir = self._get_simulation_dir(simulation_id)

            # ---- Phase 1: Parse description ----
            logger.info(f"[{simulation_id}] Parsing scenario description...")
            parser = ScenarioParser()
            scenario = parser.parse(description)

            state.total_agents = scenario.total_agents
            state.scenario_definition = scenario.to_dict()
            self._save_simulation_state(state)

            # Save scenario_definition.json
            scenario_def_path = os.path.join(sim_dir, "scenario_definition.json")
            with open(scenario_def_path, 'w', encoding='utf-8') as f:
                f.write(scenario.to_json())

            logger.info(
                f"[{simulation_id}] Scenario parsed: '{scenario.title}', "
                f"{scenario.total_agents} agents"
            )

            # ---- Phase 2: Generate profiles ----
            logger.info(f"[{simulation_id}] Generating {scenario.total_agents} agent profiles...")

            # Determine realtime output path
            if enable_reddit:
                realtime_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            else:
                realtime_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"

            profile_generator = DescriptionProfileGenerator()

            def profile_progress(current, total, msg):
                state.profiles_count = current
                self._save_simulation_state(state)

            profiles = profile_generator.generate(
                scenario=scenario,
                progress_callback=profile_progress,
                realtime_output_path=realtime_path,
                output_platform=realtime_platform,
            )

            state.profiles_count = len(profiles)
            self._save_simulation_state(state)

            # Persist profiles in both formats if both platforms enabled
            if enable_reddit:
                reddit_path = os.path.join(sim_dir, "reddit_profiles.json")
                import json as _json
                reddit_data = [p.to_reddit_format() for p in profiles]
                with open(reddit_path, 'w', encoding='utf-8') as f:
                    _json.dump(reddit_data, f, ensure_ascii=False, indent=2)

            if enable_twitter:
                twitter_path = os.path.join(sim_dir, "twitter_profiles.csv")
                import csv as _csv
                twitter_data = [p.to_twitter_format() for p in profiles]
                if twitter_data:
                    with open(twitter_path, 'w', encoding='utf-8', newline='') as f:
                        writer = _csv.DictWriter(f, fieldnames=list(twitter_data[0].keys()))
                        writer.writeheader()
                        writer.writerows(twitter_data)

            logger.info(f"[{simulation_id}] Generated {len(profiles)} profiles")

            # ---- Phase 3: Generate simulation config ----
            logger.info(f"[{simulation_id}] Generating simulation config...")
            config_gen = DescriptionConfigGenerator()

            def config_progress(current_batch: int, total_batches: int) -> None:
                state.config_batch_current = current_batch
                state.config_batch_total = total_batches
                self._save_simulation_state(state)

            sim_params = config_gen.generate(
                simulation_id=simulation_id,
                scenario=scenario,
                profiles=profiles,
                enable_twitter=enable_twitter,
                enable_reddit=enable_reddit,
                progress_callback=config_progress,
            )

            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())

            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning

            # ---- Done ----
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)

            logger.info(
                f"[{simulation_id}] Description-based preparation complete: "
                f"profiles={len(profiles)}, agents={scenario.total_agents}"
            )

        except Exception as exc:
            import traceback as _tb
            logger.error(f"[{simulation_id}] Description-based preparation failed: {exc}")
            logger.error(_tb.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(exc)
            self._save_simulation_state(state)

    def start_sms_simulation(self, simulation_id: str) -> dict:
        """Start an SMS-mode simulation as a background thread."""
        import threading
        import asyncio
        import json as _json
        from .sms_db import init_db, register_agents
        from .sms_simulation_runner import SmsSimulationRunner

        state = self.get_simulation(simulation_id)
        if state is None:
            raise ValueError(f"Simulation {simulation_id} not found")

        sim_dir = self._get_simulation_dir(simulation_id)

        # Load profiles (get_profiles returns List[Dict]), reconstruct as OasisAgentProfile objects
        raw_profiles = self.get_profiles(simulation_id)
        if not raw_profiles:
            raise ValueError("No profiles found for simulation")

        profiles = []
        for p in raw_profiles:
            uid = p.get("user_id", 0)
            profile = OasisAgentProfile(
                user_id=uid,
                user_name=p.get("username", p.get("user_name", "")),
                name=p.get("name", ""),
                bio=p.get("bio", ""),
                persona=p.get("persona", ""),
                phone_number=p.get("phone_number") or f"+1555{uid:04d}",
                karma=p.get("karma", 1000),
                age=p.get("age"),
                gender=p.get("gender"),
                mbti=p.get("mbti"),
                country=p.get("country"),
                profession=p.get("profession"),
                interested_topics=p.get("interested_topics", []),
                group_id=p.get("group_id", ""),
            )
            profiles.append(profile)

        # Load relationships
        relationships_path = os.path.join(sim_dir, "relationships_ai.json")
        relationships = {}
        if os.path.exists(relationships_path):
            with open(relationships_path, "r", encoding="utf-8") as f:
                relationships = _json.load(f)

        # Load config for total_rounds
        config_path = os.path.join(sim_dir, "simulation_config.json")
        config = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = _json.load(f)

        total_rounds = config.get("max_rounds") or config.get("total_rounds") or 10

        # Init SMS DB
        init_db(simulation_id)
        register_agents(simulation_id, profiles)

        # Update state to RUNNING
        state.status = SimulationStatus.RUNNING
        self._save_simulation_state(state)

        def _run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                runner = SmsSimulationRunner(
                    simulation_id=simulation_id,
                    profiles=profiles,
                    relationships=relationships,
                    config={"total_rounds": total_rounds},
                )
                loop.run_until_complete(runner.run())
                state.status = SimulationStatus.COMPLETED
                self._save_simulation_state(state)
            except Exception as exc:
                logger.error("SMS simulation %s failed: %s", simulation_id, exc, exc_info=True)
                state.status = SimulationStatus.FAILED
                self._save_simulation_state(state)
            finally:
                loop.close()

        thread = threading.Thread(target=_run_in_thread, daemon=True, name=f"sms-sim-{simulation_id}")
        thread.start()

        return {"simulation_id": simulation_id, "mode": "sms", "status": "started"}

    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """Get simulation state"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """List all simulations"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # Skip hidden files (such as .DS_Store) and non-directory files
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def delete_simulation(self, simulation_id: str) -> None:
        """Permanently delete a simulation directory and remove from in-memory cache."""
        sim_dir = self._get_simulation_dir(simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")
        shutil.rmtree(sim_dir)
        self._simulations.pop(simulation_id, None)

    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """Get Agent Profiles for simulation"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation does not exist: {simulation_id}")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Get simulation config"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """Get run instructions"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. Activate conda environment: conda activate MiroFish\n"
                f"2. Run simulation (scripts located in {scripts_dir}):\n"
                f"   - Run Twitter alone: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - Run Reddit alone: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - Run both platforms in parallel: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
