"""
Simulation-related API routes
Step2: Entity reading and filtering, simulation preparation and execution (fully automated)
"""

import os
import traceback
from flask import request, jsonify, send_file, current_app

from . import simulation_bp
from ..config import Config
from ..services.entity_reader import EntityReader
from ..services.oasis_profile_generator import OasisProfileGenerator
from ..services.simulation_manager import SimulationManager, SimulationStatus
from ..services.relationship_generator import RelationshipGenerator
from ..utils.logger import get_logger
from ..models.project import ProjectManager

logger = get_logger('mirofish.api.simulation')


# Interview prompt optimization prefix
# Adding this prefix can prevent agents from calling tools and reply directly with text
INTERVIEW_PROMPT_PREFIX = "Based on your persona, all your past memories and actions, reply directly to me with text without calling any tools:"


def optimize_interview_prompt(prompt: str) -> str:
    """
    Optimize Interview questions, add prefix to avoid agent calling tools
    
    Args:
        prompt: Original question
        
    Returns:
        Optimized question
    """
    if not prompt:
        return prompt
    # Avoid adding prefix repeatedly
    if prompt.startswith(INTERVIEW_PROMPT_PREFIX):
        return prompt
    return f"{INTERVIEW_PROMPT_PREFIX}{prompt}"


def _interview_sms_agents(simulation_id: str, interviews: list, manager: 'SimulationManager') -> dict:
    """
    Interview agents in an SMS-mode simulation directly via LLM (no OASIS process needed).

    Looks up each agent's profile, builds a persona-aware system prompt that includes
    their SMS conversation history, and asks the LLM to reply in-character.

    Returns a dict compatible with the OASIS interview_agents_batch result format.
    """
    import json as _json
    import os as _os
    from ..utils.llm_client import LLMClient

    sim_dir = manager._get_simulation_dir(simulation_id)
    profiles_path = _os.path.join(sim_dir, "reddit_profiles.json")

    profiles: list = []
    if _os.path.exists(profiles_path):
        with open(profiles_path, "r", encoding="utf-8") as f:
            profiles = _json.load(f)

    # Build agent_id → profile lookup (profiles are 0-indexed in the list)
    profile_by_id: dict = {}
    for idx, p in enumerate(profiles):
        uid = p.get("user_id", idx)
        profile_by_id[int(uid)] = p
        profile_by_id[idx] = p  # also reachable by list index

    # Lazy-init LLM client
    llm = LLMClient()

    results: dict = {}
    for interview in interviews:
        agent_id = int(interview.get("agent_id", 0))
        prompt = interview.get("prompt", "")
        profile = profile_by_id.get(agent_id)

        if not profile:
            results[f"sms_{agent_id}"] = {
                "agent_id": agent_id,
                "success": False,
                "response": f"Agent {agent_id} not found.",
                "platform": "sms",
            }
            continue

        name = profile.get("name") or profile.get("username") or f"Agent {agent_id}"
        persona = profile.get("persona") or profile.get("bio") or ""

        system_prompt = (
            f"You are {name}. Stay fully in character at all times.\n"
            f"Background: {persona}\n\n"
            "Reply naturally and conversationally as this person would in a text message or interview. "
            "Keep your answer concise (2-4 sentences). Do not break character or mention that you are an AI."
        )

        try:
            response_text = llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.85,
                max_tokens=300,
            )
            results[f"sms_{agent_id}"] = {
                "agent_id": agent_id,
                "success": True,
                "response": response_text,
                "platform": "sms",
            }
        except Exception as exc:
            logger.warning("SMS interview failed for agent %d: %s", agent_id, exc)
            results[f"sms_{agent_id}"] = {
                "agent_id": agent_id,
                "success": False,
                "response": f"Interview failed: {exc}",
                "platform": "sms",
            }

    return {
        "interviews_count": len(interviews),
        "results": results,
    }


# ============== Entity reading interface ==============

@simulation_bp.route('/entities/<graph_id>', methods=['GET'])
def get_graph_entities(graph_id: str):
    """
    Get all entities from the knowledge graph (filtered)
    
    Only return nodes that match predefined entity types (nodes whose Labels are not just Entity)
    
    Query parameters:
        entity_types: comma-separated list of entity types (optional, for further filtering)
        enrich: whether to get related edge information (default true)
    """
    try:
        entity_types_str = request.args.get('entity_types', '')
        entity_types = [t.strip() for t in entity_types_str.split(',') if t.strip()] if entity_types_str else None
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        logger.info(f"Get knowledge graph entities: graph_id={graph_id}, entity_types={entity_types}, enrich={enrich}")
        
        storage = current_app.extensions.get('neo4j_storage')
        if not storage:
            raise ValueError("GraphStorage not initialized")
        reader = EntityReader(storage)
        result = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to get knowledge graph entities: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/<entity_uuid>', methods=['GET'])
def get_entity_detail(graph_id: str, entity_uuid: str):
    """Get detailed information of a single entity"""
    try:
        storage = current_app.extensions.get('neo4j_storage')
        if not storage:
            raise ValueError("GraphStorage not initialized")
        reader = EntityReader(storage)
        entity = reader.get_entity_with_context(graph_id, entity_uuid)
        
        if not entity:
            return jsonify({
                "success": False,
                "error": f"Entity does not exist: {entity_uuid}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": entity.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to get entity details: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/by-type/<entity_type>', methods=['GET'])
def get_entities_by_type(graph_id: str, entity_type: str):
    """Get all entities of specified type"""
    try:
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        storage = current_app.extensions.get('neo4j_storage')
        if not storage:
            raise ValueError("GraphStorage not initialized")
        reader = EntityReader(storage)
        entities = reader.get_entities_by_type(
            graph_id=graph_id,
            entity_type=entity_type,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": {
                "entity_type": entity_type,
                "count": len(entities),
                "entities": [e.to_dict() for e in entities]
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get entities: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Simulation management interface ==============

@simulation_bp.route('/create', methods=['POST'])
def create_simulation():
    """
    Create new simulation
    
    Note: parameters like max_rounds are intelligently generated by LLM, no manual setting needed
    
    Request (JSON):
        {
            "project_id": "proj_xxxx",      // Required
            "graph_id": "mirofish_xxxx"     // Optional, if not provided, get from project
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "project_id": "proj_xxxx",
                "graph_id": "mirofish_xxxx",
                "status": "created",
                "created_at": "2025-12-01T10:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({
                "success": False,
                "error": "Please provide project_id"
            }), 400
        
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project does not exist: {project_id}"
            }), 404
        
        graph_id = data.get('graph_id') or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "Project has not built knowledge graph yet, please call /api/graph/build first"
            }), 400
        
        manager = SimulationManager()
        state = manager.create_simulation(
            project_id=project_id,
            graph_id=graph_id,
        )
        
        return jsonify({
            "success": True,
            "data": state.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Failed to create simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _check_simulation_prepared(simulation_id: str) -> tuple:
    """
    Check if simulation is ready
    
    Check conditions:
    1. state.json exists and status is "ready"
    2. Required files exist: reddit_profiles.json, twitter_profiles.csv, simulation_config.json
    
    Note: run scripts (run_*.py) remain in backend/scripts/ directory, no longer copied to simulation directory
    
    Args:
        simulation_id: Simulation ID
        
    Returns:
        (is_prepared: bool, info: dict)
    """
    import os
    from ..config import Config
    
    simulation_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    
    # Check if directory exists
    if not os.path.exists(simulation_dir):
        return False, {"reason": "Simulation directory does not exist"}
    
    # Required file list
    required_files = [
        "state.json",
        "simulation_config.json",
        "reddit_profiles.json",
    ]
    
    # Check if files exist
    existing_files = []
    missing_files = []
    for f in required_files:
        file_path = os.path.join(simulation_dir, f)
        if os.path.exists(file_path):
            existing_files.append(f)
        else:
            missing_files.append(f)
    
    if missing_files:
        return False, {
            "reason": "Missing required files",
            "missing_files": missing_files,
            "existing_files": existing_files
        }
    
    # Check status in state.json
    state_file = os.path.join(simulation_dir, "state.json")
    try:
        import json
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
        
        status = state_data.get("status", "")
        config_generated = state_data.get("config_generated", False)
        
        # Detailed logs
        logger.debug(f"Detect simulation preparation status: {simulation_id}, status={status}, config_generated={config_generated}")
        
        # If config_generated=True and files exist, consider preparation complete
        # The following statuses indicate preparation is complete：
        # - ready: Preparation complete, can run
        # - preparing: If config_generated=True, description shows completed
        # - running: Running, preparation already completed
        # - completed: Execution complete, preparation already completed
        # - stopped: Stopped, preparation already completed
        # - failed: Execution failed (but preparation is not completed)
        prepared_statuses = ["ready", "preparing", "running", "completed", "stopped", "failed"]
        if status in prepared_statuses and config_generated:
            # Get file statistics
            profiles_file = os.path.join(simulation_dir, "reddit_profiles.json")
            config_file = os.path.join(simulation_dir, "simulation_config.json")
            
            profiles_count = 0
            if os.path.exists(profiles_file):
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles_data = json.load(f)
                    profiles_count = len(profiles_data) if isinstance(profiles_data, list) else 0
            
            # If status is "preparing" but files are completed, update status to "ready"
            if status == "preparing":
                try:
                    state_data["status"] = "ready"
                    from datetime import datetime
                    state_data["updated_at"] = datetime.now().isoformat()
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(state_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"Auto update simulation status: {simulation_id} preparing -> ready")
                    status = "ready"
                except Exception as e:
                    logger.warning(f"Failed to auto update status: {e}")
            
            logger.info(f"Simulation {simulation_id} Detection result: HasPreparation complete (status={status}, config_generated={config_generated})")
            return True, {
                "status": status,
                "entities_count": state_data.get("entities_count", 0),
                "profiles_count": profiles_count,
                "entity_types": state_data.get("entity_types", []),
                "config_generated": config_generated,
                "created_at": state_data.get("created_at"),
                "updated_at": state_data.get("updated_at"),
                "existing_files": existing_files
            }
        else:
            logger.warning(f"Simulation {simulation_id} Detection result: Has notPreparation complete (status={status}, config_generated={config_generated})")
            return False, {
                "reason": f"Status not in prepared list or config_generated is false: status={status}, config_generated={config_generated}",
                "status": status,
                "config_generated": config_generated
            }
            
    except Exception as e:
        return False, {"reason": f"Failed to read state file: {str(e)}"}


@simulation_bp.route('/prepare', methods=['POST'])
def prepare_simulation():
    """
    Prepare simulation environment (async task with LLM intelligent configuration generation).

    This is a time-consuming operation. The interface returns immediately with a task_id.
    Use GET /api/simulation/prepare/status to query progress.

    Features:
    - Automatically detect completed preparations to avoid duplicate generation
    - If already prepared, return existing results directly
    - Support forced regeneration (force_regenerate=true)

    Steps:
    1. Check if preparation is already complete
    2. Read and filter entities from knowledge graph
    3. Generate OASIS Agent Profile for each entity (with retry mechanism)
    4. LLM intelligently generates simulation configuration (with retry mechanism)
    5. Save configuration files and preset scripts
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx",                   // Required，Simulation ID
            "entity_types": ["Student", "PublicFigure"],  // Optional，Specified entity type
            "use_llm_for_profiles": true,                 // Optional，IsOtherwise useLLMGeneratepersona
            "parallel_profile_count": 5,                  // Optional, number of personas to generate in parallel, default 5
            "force_regenerate": false                     // Optional，ForceGenerate，Defaultfalse
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",           // Return for new tasks
                "status": "preparing|ready",
                "message": "Preparation task started|Preparation already completed",
                "already_prepared": true|false    // Is preparation complete
            }
        }
    """
    import threading
    import os
    from ..models.task import TaskManager, TaskStatus
    from ..config import Config
    
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400
        
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        # Check if forced regeneration
        force_regenerate = data.get('force_regenerate', False)
        logger.info(f"Start processing /prepare Request: simulation_id={simulation_id}, force_regenerate={force_regenerate}")
        
        # Check if already prepared（Avoid duplicatesGenerate）
        if not force_regenerate:
            logger.debug(f"Check simulation {simulation_id} Is preparation complete...")
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            logger.debug(f"Check result: is_prepared={is_prepared}, prepare_info={prepare_info}")
            if is_prepared:
                logger.info(f"Simulation {simulation_id} has preparation complete, no need to regenerate")
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "message": "Preparation already completed，No need to repeatGenerate",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
            else:
                logger.info(f"Simulation {simulation_id} has no preparation complete, preparing now")
        
        # Get necessary information from project
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project does not exist: {state.project_id}"
            }), 404
        
        # Get simulation requirements
        simulation_requirement = project.simulation_requirement or ""
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "Project missing simulation requirement description (simulation_requirement)"
            }), 400
        
        # Get document text
        document_text = ProjectManager.get_extracted_text(state.project_id) or ""
        
        entity_types_list = data.get('entity_types')
        use_llm_for_profiles = data.get('use_llm_for_profiles', True)
        parallel_profile_count = data.get('parallel_profile_count', 5)
        agents_per_batch = int(data.get('agents_per_batch', 15))
        
        # ========== Get GraphStorage（Capture reference before background task starts） ==========
        storage = current_app.extensions.get('neo4j_storage')
        if not storage:
            raise ValueError("GraphStorage not initialized — check Neo4j connection")

        # ========== Synchronously get entity count（Before background task starts） ==========
        # This way frontend when callingprepareCan immediately getExpected total agents
        try:
            logger.info(f"Synchronously get entity count: graph_id={state.graph_id}")
            reader = EntityReader(storage)
            # Quickly read entities (no edge information, only statistics required)
            filtered_preview = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=entity_types_list,
                enrich_with_edges=False  # No edge information，Speed up
            )
            # Save entity count to status（For frontend to get immediately）
            state.entities_count = filtered_preview.filtered_count
            state.entity_types = list(filtered_preview.entity_types)
            logger.info(f"Expected entity count: {filtered_preview.filtered_count}, [type][model]: {filtered_preview.entity_types}")
        except Exception as e:
            logger.warning(f"Synchronously get entity countFailed（Will retry in background task）: {e}")
            # Failure does not affect subsequent process，Background task will retry
        
        # Create async task
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="simulation_prepare",
            metadata={
                "simulation_id": simulation_id,
                "project_id": state.project_id
            }
        )
        
        # Update simulation status（Include pre-fetched entity count）
        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state)
        
        # Define background task
        def run_prepare():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message="Start preparing simulation environment..."
                )
                
                # PrepareSimulation（With progress callback）
                # Store stage progress details
                stage_details = {}
                
                def progress_callback(stage, progress, message, **kwargs):
                    # Calculate total progress
                    stage_weights = {
                        "reading": (0, 20),           # 0-20%
                        "generating_profiles": (20, 70),  # 20-70%
                        "generating_config": (70, 90),    # 70-90%
                        "copying_scripts": (90, 100)       # 90-100%
                    }
                    
                    start, end = stage_weights.get(stage, (0, 100))
                    current_progress = int(start + (end - start) * progress / 100)
                    
                    # Build detailed progress information
                    stage_names = {
                        "reading": "Read knowledge graph entities",
                        "generating_profiles": "GenerateAgentpersona",
                        "generating_config": "Generate simulation configuration",
                        "copying_scripts": "Prepare simulation scripts"
                    }
                    
                    stage_index = list(stage_weights.keys()).index(stage) + 1 if stage in stage_weights else 1
                    total_stages = len(stage_weights)
                    
                    # Update stage details
                    stage_details[stage] = {
                        "stage_name": stage_names.get(stage, stage),
                        "stage_progress": progress,
                        "current": kwargs.get("current", 0),
                        "total": kwargs.get("total", 0),
                        "item_name": kwargs.get("item_name", "")
                    }
                    
                    # Build detailed progress information
                    detail = stage_details[stage]
                    progress_detail_data = {
                        "current_stage": stage,
                        "current_stage_name": stage_names.get(stage, stage),
                        "stage_index": stage_index,
                        "total_stages": total_stages,
                        "stage_progress": progress,
                        "current_item": detail["current"],
                        "total_items": detail["total"],
                        "item_description": message
                    }
                    
                    # Build concise message
                    if detail["total"] > 0:
                        detailed_message = (
                            f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: "
                            f"{detail['current']}/{detail['total']} - {message}"
                        )
                    else:
                        detailed_message = f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: {message}"
                    
                    task_manager.update_task(
                        task_id,
                        progress=current_progress,
                        message=detailed_message,
                        progress_detail=progress_detail_data
                    )
                
                result_state = manager.prepare_simulation(
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    defined_entity_types=entity_types_list,
                    use_llm_for_profiles=use_llm_for_profiles,
                    progress_callback=progress_callback,
                    parallel_profile_count=parallel_profile_count,
                    agents_per_batch=agents_per_batch,
                    storage=storage,
                )
                
                # Task complete
                task_manager.complete_task(
                    task_id,
                    result=result_state.to_simple_dict()
                )
                
            except Exception as e:
                logger.error(f"Failed to prepare simulation: {str(e)}")
                task_manager.fail_task(task_id, str(e))
                
                # Update simulation status to failed
                state = manager.get_simulation(simulation_id)
                if state:
                    state.status = SimulationStatus.FAILED
                    state.error = str(e)
                    manager._save_simulation_state(state)
        
        # Start background thread
        thread = threading.Thread(target=run_prepare, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "task_id": task_id,
                "status": "preparing",
                "message": "Preparation task started，Please via /api/simulation/prepare/status Query progress",
                "already_prepared": False,
                "expected_entities_count": state.entities_count,  # Expected number of entities to process
                "entity_types": state.entity_types  # Entity type list
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"Failed to start preparation task: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/prepare/status', methods=['POST'])
def get_prepare_status():
    """
    Query preparation task progress
    
    Support two query methods:
    1. Query via task_id to check ongoing task progress
    2. Check via simulation_id to verify if preparation is already completed
    
    Request (JSON):
        {
            "task_id": "task_xxxx",          // Optional, from previous /prepare call
            "simulation_id": "sim_xxxx"      // Optional，Simulation ID（For checking completedPrepare）
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|ready",
                "progress": 45,
                "message": "...",
                "already_prepared": true|false,  // Is there completed preparation
                "prepare_info": {...}            // Detailed information when preparation complete
            }
        }
    """
    from ..models.task import TaskManager
    
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # If simulation_id is provided, check if preparation is complete
        if simulation_id:
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            if is_prepared:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "progress": 100,
                        "message": "Preparation already completed",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
        
        # If no task_id，ReturnError
        if not task_id:
            if simulation_id:
                # Have simulation_idBut notPreparation complete
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "not_started",
                        "progress": 0,
                        "message": "Preparation not started yet, please call /api/simulation/prepare",
                        "already_prepared": False
                    }
                })
            return jsonify({
                "success": False,
                "error": "Please provide task_id Or simulation_id"
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            # Task does not exist, but if simulation_id is provided, check if preparation is complete
            if simulation_id:
                is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
                if is_prepared:
                    return jsonify({
                        "success": True,
                        "data": {
                            "simulation_id": simulation_id,
                            "task_id": task_id,
                            "status": "ready",
                            "progress": 100,
                            "message": "Task complete（PrepareWork already exists）",
                            "already_prepared": True,
                            "prepare_info": prepare_info
                        }
                    })
            
            return jsonify({
                "success": False,
                "error": f"Task does not exist: {task_id}"
            }), 404
        
        task_dict = task.to_dict()
        task_dict["already_prepared"] = False
        
        return jsonify({
            "success": True,
            "data": task_dict
        })
        
    except Exception as e:
        logger.error(f"Failed to query task status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """Get simulation status"""
    try:
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        result = state.to_dict()
        
        # If simulation is ready，Additional runtime instructions
        if state.status == SimulationStatus.READY:
            result["run_instructions"] = manager.get_run_instructions(simulation_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Failed to get simulation status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/list', methods=['GET'])
def list_simulations():
    """
    List all simulations
    
    Query parameters:
        project_id: By projectIDFilter（Optional）
    """
    try:
        project_id = request.args.get('project_id')
        
        manager = SimulationManager()
        simulations = manager.list_simulations(project_id=project_id)
        
        return jsonify({
            "success": True,
            "data": [s.to_dict() for s in simulations],
            "count": len(simulations)
        })
        
    except Exception as e:
        logger.error(f"Failed to list simulations: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/relationships', methods=['GET'])
def get_simulation_relationships(simulation_id: str):
    """
    Generate (or load from cache) AI-driven agent relationships for a simulation.

    Query parameters:
        force: set to 'true' to regenerate even if cached (default false)

    Returns:
        {
            "success": true,
            "data": {
                "edges": [{src_id, tgt_id, type, label}, ...],
                "count": N
            }
        }
    """
    import json as _json

    try:
        force = request.args.get('force', 'false').lower() == 'true'

        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if not state:
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404

        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)

        # Load profiles
        profiles_path = os.path.join(sim_dir, "reddit_profiles.json")
        if not os.path.exists(profiles_path):
            return jsonify({
                "success": False,
                "error": "reddit_profiles.json not found — run prepare first"
            }), 404

        with open(profiles_path, "r", encoding="utf-8") as f:
            profiles = _json.load(f)
        if not isinstance(profiles, list):
            profiles = []

        # Load groups from scenario_definition.json
        groups = []
        scenario_path = os.path.join(sim_dir, "scenario_definition.json")
        if os.path.exists(scenario_path):
            try:
                with open(scenario_path, "r", encoding="utf-8") as f:
                    scenario = _json.load(f)
                groups = scenario.get("groups", [])
            except Exception as e:
                logger.warning(f"Could not read scenario_definition.json: {e}")

        def _rel_progress(agent_current: int, agent_total: int, rel_count: int) -> None:
            if state:
                state.relationship_agent_current = agent_current
                state.relationship_agent_total = agent_total
                state.relationship_count = rel_count
                manager._save_simulation_state(state)

        gen = RelationshipGenerator()
        edges = gen.generate(sim_dir, profiles, groups, force=force, progress_callback=_rel_progress)

        return jsonify({
            "success": True,
            "data": {
                "edges": edges,
                "count": len(edges),
            }
        })

    except Exception as e:
        logger.error(f"Failed to generate relationships for {simulation_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['DELETE'])
def delete_simulation(simulation_id: str):
    """Permanently delete a simulation and all its files."""
    try:
        manager = SimulationManager()
        manager.delete_simulation(simulation_id)
        return jsonify({"success": True, "simulation_id": simulation_id})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.error(f"Failed to delete simulation {simulation_id}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def _get_report_id_for_simulation(simulation_id: str) -> str:
    """
    Get simulation Corresponding latest report_id
    
    Traverse reports directory and find the report matching the simulation_id.
    If multiple exist, return the latest one (by created_at timestamp).
    
    Args:
        simulation_id: Simulation ID
        
    Returns:
        report_id Or None
    """
    import json
    from datetime import datetime
    
    # reports Directory path：backend/uploads/reports
    # __file__ Is app/api/simulation.py，Need to go up two levels to backend/
    reports_dir = os.path.join(os.path.dirname(__file__), '../../uploads/reports')
    if not os.path.exists(reports_dir):
        return None
    
    matching_reports = []
    
    try:
        for report_folder in os.listdir(reports_dir):
            report_path = os.path.join(reports_dir, report_folder)
            if not os.path.isdir(report_path):
                continue
            
            meta_file = os.path.join(report_path, "meta.json")
            if not os.path.exists(meta_file):
                continue
            
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                if meta.get("simulation_id") == simulation_id:
                    matching_reports.append({
                        "report_id": meta.get("report_id"),
                        "created_at": meta.get("created_at", ""),
                        "status": meta.get("status", "")
                    })
            except Exception:
                continue
        
        if not matching_reports:
            return None
        
        # Sort by creation time descending，ReturnLatest
        matching_reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return matching_reports[0].get("report_id")
        
    except Exception as e:
        logger.warning(f"Failed to find report for simulation {simulation_id}: {e}")
        return None


@simulation_bp.route('/history', methods=['GET'])
def get_simulation_history():
    """
    Get historical simulation list（With project details）
    
    For homepage historical project display. Returns project name and other information about the simulation.
    
    Query parameters:
        limit: Return count limit（Default20）
    
    Returns:
        {
            "success": true,
            "data": [
                {
                    "simulation_id": "sim_xxxx",
                    "project_id": "proj_xxxx",
                    "project_name": "WDU Opinion Analysis",
                    "simulation_requirement": "If Wuhan University publishes...",
                    "status": "completed",
                    "entities_count": 68,
                    "profiles_count": 68,
                    "entity_types": ["Student", "Professor", ...],
                    "created_at": "2024-12-10",
                    "updated_at": "2024-12-10",
                    "total_rounds": 120,
                    "current_round": 120,
                    "report_id": "report_xxxx",
                    "version": "v1.0.2"
                },
                ...
            ],
            "count": 7
        }
    """
    try:
        limit = request.args.get('limit', 20, type=int)
        
        manager = SimulationManager()
        simulations = manager.list_simulations()[:limit]
        
        # Enhance simulation data，Only from Simulation FileRead
        enriched_simulations = []
        for sim in simulations:
            sim_dict = sim.to_dict()
            
            # Get simulation configuration information（From simulation_config.json Read simulation_requirement）
            config = manager.get_simulation_config(sim.simulation_id)
            if config:
                sim_dict["simulation_requirement"] = config.get("simulation_requirement", "")
                time_config = config.get("time_config", {})
                sim_dict["total_simulation_hours"] = time_config.get("total_simulation_hours", 0)
                # Recommended rounds（Fallback value）
                recommended_rounds = int(
                    time_config.get("total_simulation_hours", 0) * 60 / 
                    max(time_config.get("minutes_per_round", 60), 1)
                )
            else:
                sim_dict["simulation_requirement"] = ""
                sim_dict["total_simulation_hours"] = 0
                recommended_rounds = 0
            
            # Get running status (from run_state.json)
            import json as _json
            _run_state_path = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim.simulation_id, "run_state.json")
            if os.path.exists(_run_state_path):
                try:
                    with open(_run_state_path, 'r', encoding='utf-8') as _f:
                        _rs = _json.load(_f)
                    sim_dict["current_round"] = _rs.get("current_round", 0)
                    sim_dict["runner_status"] = _rs.get("runner_status", "idle")
                    sim_dict["total_rounds"] = _rs.get("total_rounds", 0) or recommended_rounds
                except Exception:
                    sim_dict["current_round"] = 0
                    sim_dict["runner_status"] = "idle"
                    sim_dict["total_rounds"] = recommended_rounds
            else:
                sim_dict["current_round"] = 0
                sim_dict["runner_status"] = "idle"
                sim_dict["total_rounds"] = recommended_rounds
            
            # Get associated project file list（At most3items）
            project = ProjectManager.get_project(sim.project_id)
            if project and hasattr(project, 'files') and project.files:
                sim_dict["files"] = [
                    {"filename": f.get("filename", "Unknown file")} 
                    for f in project.files[:3]
                ]
            else:
                sim_dict["files"] = []
            
            # Get associated report_id（FindThis simulation Latest report）
            sim_dict["report_id"] = _get_report_id_for_simulation(sim.simulation_id)
            
            # Add version number
            sim_dict["version"] = "v1.0.2"
            
            # Format date
            try:
                created_date = sim_dict.get("created_at", "")[:10]
                sim_dict["created_date"] = created_date
            except:
                sim_dict["created_date"] = ""
            
            enriched_simulations.append(sim_dict)
        
        return jsonify({
            "success": True,
            "data": enriched_simulations,
            "count": len(enriched_simulations)
        })
        
    except Exception as e:
        logger.error(f"Failed to get historical simulations: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles', methods=['GET'])
def get_simulation_profiles(simulation_id: str):
    """
    Get simulation'sAgent Profile
    
    Query parameters:
        platform: Platform type（reddit/twitter，Defaultreddit）
    """
    try:
        platform = request.args.get('platform', 'reddit')
        
        manager = SimulationManager()
        profiles = manager.get_profiles(simulation_id, platform=platform)
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "count": len(profiles),
                "profiles": profiles
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"GetProfileFailed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles/realtime', methods=['GET'])
def get_simulation_profiles_realtime(simulation_id: str):
    """
    Real-time get simulation's Agent Profile (for viewing during generation).

    Difference from /profiles endpoint:
    - Reads file directly, bypasses SimulationManager
    - For real-time viewing during generation
    - Returns additional metadata (such as file modification time, whether generation is in progress, etc.)
    
    Query parameters:
        platform: Platform type（reddit/twitter，Defaultreddit）
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "platform": "reddit",
                "count": 15,
                "total_expected": 93,  // Expected total（IfHas）
                "is_generating": true,  // Is generating
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "profiles": [...]
            }
        }
    """
    import json
    from datetime import datetime

    try:
        platform = request.args.get('platform', 'reddit')
        
        # Get simulation directory
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        # Profiles are stored as JSON (reddit format)
        profiles_file = os.path.join(sim_dir, "reddit_profiles.json")

        # Check if files exist
        file_exists = os.path.exists(profiles_file)
        profiles = []
        file_modified_at = None

        if file_exists:
            # Get file modification time
            file_stat = os.stat(profiles_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()

            try:
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to read profiles file: {e}")
                profiles = []
        
        # Check if generation is in progress (through state.json status field)
        is_generating = False
        total_expected = None
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    total_expected = state_data.get("entities_count")
            except Exception:
                pass
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "platform": platform,
                "count": len(profiles),
                "total_expected": total_expected,
                "is_generating": is_generating,
                "file_exists": file_exists,
                "file_modified_at": file_modified_at,
                "profiles": profiles
            }
        })
        
    except Exception as e:
        logger.error(f"Real-time getProfileFailed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/realtime', methods=['GET'])
def get_simulation_config_realtime(simulation_id: str):
    """
    Real-time get simulation configuration (for viewing during generation).

    Difference from /config endpoint:
    - Reads file directly, bypasses SimulationManager
    - For real-time viewing during generation
    - Returns additional metadata (such as file modification time, whether generation is in progress, etc.)
    - Returns partial information even if config not fully generated
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "is_generating": true,  // Is generating
                "generation_stage": "generating_config",  // Current generation stage
                "config": {...}  // Configuration content（IfExists）
            }
        }
    """
    import json
    from datetime import datetime
    
    try:
        # Get simulation directory
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"Simulation does not exist: {simulation_id}"
            }), 404
        
        # Config file path
        config_file = os.path.join(sim_dir, "simulation_config.json")
        
        # Check if files exist
        file_exists = os.path.exists(config_file)
        config = None
        file_modified_at = None
        
        if file_exists:
            # Get file modification time
            file_stat = os.stat(config_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to read config file: {e}")
                config = None
        
        # Check if generation is in progress (through state.json status field)
        is_generating = False
        generation_stage = None
        config_generated = False
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    config_generated = state_data.get("config_generated", False)
                    
                    # Judge current stage
                    if is_generating:
                        if state_data.get("profiles_generated", False):
                            generation_stage = "generating_config"
                        else:
                            generation_stage = "generating_profiles"
                    elif status == "ready":
                        generation_stage = "completed"
            except Exception:
                pass
        
        # Build return data
        response_data = {
            "simulation_id": simulation_id,
            "file_exists": file_exists,
            "file_modified_at": file_modified_at,
            "is_generating": is_generating,
            "generation_stage": generation_stage,
            "config_generated": config_generated,
            "config": config
        }
        
        # If configuration exists，Extract key statistics
        if config:
            response_data["summary"] = {
                "total_agents": len(config.get("agent_configs", [])),
                "simulation_hours": config.get("time_config", {}).get("total_simulation_hours"),
                "initial_posts_count": len(config.get("event_config", {}).get("initial_posts", [])),
                "hot_topics_count": len(config.get("event_config", {}).get("hot_topics", [])),
                "generated_at": config.get("generated_at"),
                "llm_model": config.get("llm_model")
            }
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except Exception as e:
        logger.error(f"Real-time getConfigFailed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config', methods=['GET'])
def get_simulation_config(simulation_id: str):
    """
    Get simulation configuration (generated with LLM intelligence).

    Returns:
        - time_config: Time configuration (simulation duration, start time, end time, etc.)
        - agent_configs: Activity configuration for each agent (behavior patterns, interaction styles, etc.)
        - event_config: Event configuration (initial posts, event sequences, etc.)
        - platform_configs: Platform configuration
        - generation_reasoning: LLM configuration reasoning explanation
    """
    try:
        manager = SimulationManager()
        config = manager.get_simulation_config(simulation_id)
        
        if not config:
            return jsonify({
                "success": False,
                "error": f"Simulation configuration does not exist. Please call /prepare first"
            }), 404
        
        return jsonify({
            "success": True,
            "data": config
        })
        
    except Exception as e:
        logger.error(f"Failed to get configuration: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/download', methods=['GET'])
def download_simulation_config(simulation_id: str):
    """Download simulation configuration file"""
    try:
        manager = SimulationManager()
        sim_dir = manager._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return jsonify({
                "success": False,
                "error": "Configuration file does not exist. Please call /prepare first"
            }), 404
        
        return send_file(
            config_path,
            as_attachment=True,
            download_name="simulation_config.json"
        )
        
    except Exception as e:
        logger.error(f"Failed to download configuration: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/script/<script_name>/download', methods=['GET'])
def download_simulation_script(script_name: str):
    """
    Download simulation run script file (general scripts from backend/scripts/)
    
    script_nameOptional values：
        - run_twitter_simulation.py
        - run_reddit_simulation.py
        - run_parallel_simulation.py
        - action_logger.py
    """
    try:
        # Scripts located at backend/scripts/ Directory
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        # Verify script name
        allowed_scripts = [
            "action_logger.py"
        ]
        
        if script_name not in allowed_scripts:
            return jsonify({
                "success": False,
                "error": f"Unknown script: {script_name}，Optional: {allowed_scripts}"
            }), 400
        
        script_path = os.path.join(scripts_dir, script_name)
        
        if not os.path.exists(script_path):
            return jsonify({
                "success": False,
                "error": f"Script file does not exist: {script_name}"
            }), 404
        
        return send_file(
            script_path,
            as_attachment=True,
            download_name=script_name
        )
        
    except Exception as e:
        logger.error(f"Failed to download script: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== ProfileGeneration interface（StandaloneUse） ==============

@simulation_bp.route('/generate-profiles', methods=['POST'])
def generate_profiles():
    """
    Generate directly from knowledge graphOASIS Agent Profile（Do not createSimulation）
    
    Request (JSON):
        {
            "graph_id": "mirofish_xxxx",     // Required
            "entity_types": ["Student"],      // Optional
            "use_llm": true,                  // Optional
            "platform": "reddit"              // Optional
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "Please provide graph_id"
            }), 400
        
        entity_types = data.get('entity_types')
        use_llm = data.get('use_llm', True)
        platform = data.get('platform', 'reddit')
        
        storage = current_app.extensions.get('neo4j_storage')
        if not storage:
            raise ValueError("GraphStorage not initialized")
        reader = EntityReader(storage)
        filtered = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=True
        )
        
        if filtered.filtered_count == 0:
            return jsonify({
                "success": False,
                "error": "No matching entities found"
            }), 400
        
        generator = OasisProfileGenerator()
        profiles = generator.generate_profiles_from_entities(
            entities=filtered.entities,
            use_llm=use_llm
        )
        
        if platform == "reddit":
            profiles_data = [p.to_reddit_format() for p in profiles]
        elif platform == "twitter":
            profiles_data = [p.to_twitter_format() for p in profiles]
        else:
            profiles_data = [p.to_dict() for p in profiles]
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "entity_types": list(filtered.entity_types),
                "count": len(profiles_data),
                "profiles": profiles_data
            }
        })
        
    except Exception as e:
        logger.error(f"GenerateProfileFailed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Simulation execution control interface ==============

@simulation_bp.route('/start', methods=['POST'])
def start_simulation():
    """
    Start running simulation

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",          // Required，Simulation ID
            "platform": "parallel",                // Optional: twitter / reddit / parallel (Default)
            "max_rounds": 100,                     // Optional: Maximum simulation rounds, default unlimited
            "enable_graph_memory_update": false,   // Optional: Whether to enable knowledge graph memory updates for agents
            "force": false                         // Optional: Force restart (stop running simulation and clean runtime files)
        }

    About force Parameters:
        - After enabling, if simulation is running or completed, clean runtime logs
        - Cleanup includes：run_state.json, actions.jsonl, simulation.log And so on
        - Will not clean configuration files（simulation_config.json）And profile File
        - For scenarios that need to rerun simulation

    About enable_graph_memory_update:
        - After enabling, all agents in the simulation will update the knowledge graph with their actions (posts, comments, follows, etc.)
        - This allows the knowledge graph to "remember" the simulation, improving context understanding and AI decision-making
        - Requires associated project to have valid graph_id
        - Uses batch update mechanism to reduce API overhead

    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "process_pid": 12345,
                "twitter_running": true,
                "reddit_running": true,
                "started_at": "2025-12-01T10:00:00",
                "graph_memory_update_enabled": true,  // Whether knowledge graph memory update enabled
                "force_restarted": true               // Whether is forced restart
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        simulation_mode = data.get('simulation_mode', 'oasis')  # "oasis" | "sms"
        platform = data.get('platform', 'parallel')
        max_rounds = data.get('max_rounds')  # Optional: Maximum simulation rounds
        enable_graph_memory_update = data.get('enable_graph_memory_update', False)  # Optional：IsFalseEnable knowledge graph memory update
        force = data.get('force', False)  # Optional：Force restart

        # SMS simulation mode: short-circuit to dedicated runner
        if simulation_mode == 'sms':
            manager = SimulationManager()
            max_rounds = data.get("max_rounds")
            try:
                result = manager.start_sms_simulation(simulation_id, max_rounds=max_rounds, force=force)
            except ValueError as e:
                return jsonify({"success": False, "error": str(e)}), 400
            return jsonify({"success": True, "data": result})

        return jsonify({
            "success": False,
            "error": "Only SMS simulation mode is supported. Use simulation_mode='sms'."
        }), 400

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except Exception as e:
        logger.error(f"Failed to start simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/stop', methods=['POST'])
def stop_simulation():
    """
    Stop simulation
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx"  // Required，Simulation ID
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "stopped",
                "completed_at": "2025-12-01T12:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        # Write SMS stop flag
        from ..services.sms_simulation_runner import _get_stop_flag_path
        try:
            with open(_get_stop_flag_path(simulation_id), "w") as _sf:
                _sf.write("stopped")
        except Exception as _e:
            logger.warning("Could not write SMS stop flag for %s: %s", simulation_id, _e)

        # Update simulation status
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.PAUSED
            manager._save_simulation_state(state)

        return jsonify({
            "success": True,
            "data": {"simulation_id": simulation_id, "runner_status": "stopped"}
        })

    except Exception as e:
        logger.error(f"Failed to stop simulation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Real-time status monitoring interface ==============

@simulation_bp.route('/<simulation_id>/run-status', methods=['GET'])
def get_run_status(simulation_id: str):
    """
    Get simulation real-time running status（For frontend polling）
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                "total_rounds": 144,
                "progress_percent": 3.5,
                "simulated_hours": 2,
                "total_simulation_hours": 72,
                "twitter_running": true,
                "reddit_running": true,
                "twitter_actions_count": 150,
                "reddit_actions_count": 200,
                "total_actions_count": 350,
                "started_at": "2025-12-01T10:00:00",
                "updated_at": "2025-12-01T10:30:00"
            }
        }
    """
    try:
        import json as _json
        run_state_path = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id, "run_state.json")

        if not os.path.exists(run_state_path):
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "current_round": 0,
                    "total_rounds": 0,
                    "progress_percent": 0,
                    "total_actions_count": 0,
                }
            })

        with open(run_state_path, 'r', encoding='utf-8') as f:
            run_state = _json.load(f)

        run_state["simulation_id"] = simulation_id
        return jsonify({"success": True, "data": run_state})

    except Exception as e:
        logger.error(f"Failed to get running status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/run-status/detail', methods=['GET'])
def get_run_status_detail(simulation_id: str):
    """
    Get simulation detailed running status（Include all actions）
    
    For frontend to display real-time dynamics
    
    Query parameters:
        platform: Filter platform（twitter/reddit，Optional）
    
    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                ...
                "all_actions": [
                    {
                        "round_num": 5,
                        "timestamp": "2025-12-01T10:30:00",
                        "platform": "twitter",
                        "agent_id": 3,
                        "agent_name": "Agent Name",
                        "action_type": "CREATE_POST",
                        "action_args": {"content": "..."},
                        "result": null,
                        "success": true
                    },
                    ...
                ],
                "twitter_actions": [...],  # Twitter All actions of platform
                "reddit_actions": [...]    # Reddit All actions of platform
            }
        }
    """
    try:
        import json as _json
        run_state_path = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id, "run_state.json")

        if not os.path.exists(run_state_path):
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "all_actions": [],
                }
            })

        with open(run_state_path, 'r', encoding='utf-8') as f:
            result = _json.load(f)

        result["simulation_id"] = simulation_id
        result.setdefault("all_actions", [])

        return jsonify({"success": True, "data": result})

    except Exception as e:
        logger.error(f"Failed to get detailed status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/actions', methods=['GET'])
def get_simulation_actions(simulation_id: str):
    """
    Get from simulationAgentAction history
    
    Query parameters:
        limit: Return count（Default100）
        offset: Offset（Default0）
        platform: Filter platform（twitter/reddit）
        agent_id: FilterAgent ID
        round_num: Filter round
    
    Returns:
        {
            "success": true,
            "data": {
                "count": 100,
                "actions": [...]
            }
        }
    """
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        platform = request.args.get('platform')
        agent_id = request.args.get('agent_id', type=int)
        round_num = request.args.get('round_num', type=int)
        
        return jsonify({
            "success": True,
            "data": {
                "count": 0,
                "actions": []
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get action history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/timeline', methods=['GET'])
def get_simulation_timeline(simulation_id: str):
    """
    Get simulation timeline（Summarized by round）
    
    For frontend to display progress bar and timeline view
    
    Query parameters:
        start_round: Start round（Default0）
        end_round: End round（Default all）
    
    Return summary information per round
    """
    try:
        return jsonify({
            "success": True,
            "data": {
                "rounds_count": 0,
                "timeline": []
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get timeline: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/agent-stats', methods=['GET'])
def get_agent_stats(simulation_id: str):
    """
    Get eachAgentStatistics
    
    For frontend display of agent activity ranking and statistics.
    """
    try:
        return jsonify({
            "success": True,
            "data": {
                "agents_count": 0,
                "stats": []
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get agent statistics: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Database query interface ==============

@simulation_bp.route('/<simulation_id>/posts', methods=['GET'])
def get_simulation_posts(simulation_id: str):
    """
    Get posts in simulation
    
    Query parameters:
        platform: Platform type（twitter/reddit）
        limit: Return count（Default50）
        offset: Offset
    
    Return post list (read from SQLite database)
    """
    try:
        platform = request.args.get('platform', 'reddit')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )
        
        db_file = f"{platform}_simulation.db"
        db_path = os.path.join(sim_dir, db_file)
        
        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "platform": platform,
                    "count": 0,
                    "posts": [],
                    "message": "Database does not exist，SimulationMay not have run yet"
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM post 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            posts = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT COUNT(*) FROM post")
            total = cursor.fetchone()[0]
            
        except sqlite3.OperationalError:
            posts = []
            total = 0
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "total": total,
                "count": len(posts),
                "posts": posts
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get posts: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/comments', methods=['GET'])
def get_simulation_comments(simulation_id: str):
    """
    Get comments in simulation（OnlyReddit）
    
    Query parameters:
        post_id: Filter postsID（Optional）
        limit: Return count
        offset: Offset
    """
    try:
        post_id = request.args.get('post_id')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )
        
        db_path = os.path.join(sim_dir, "reddit_simulation.db")
        
        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "count": 0,
                    "comments": []
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if post_id:
                cursor.execute("""
                    SELECT * FROM comment 
                    WHERE post_id = ?
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (post_id, limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM comment 
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            
            comments = [dict(row) for row in cursor.fetchall()]
            
        except sqlite3.OperationalError:
            comments = []
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "count": len(comments),
                "comments": comments
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get comments: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interview Interview interface ==============

@simulation_bp.route('/interview', methods=['POST'])
def interview_agent():
    """
    Interview individualAgent

    Note: This feature requires simulation to be in a running or completed state (run the simulation and wait for it to progress).

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",       // Required，Simulation ID
            "agent_id": 0,                     // Required，Agent ID
            "prompt": "What do you think about this？",  // Required，Interview question
            "platform": "twitter",             // Optional，Specified platform（twitter/reddit）
                                               // When not specified: Both platforms in dual-platform simulations
            "timeout": 60                      // Optional, timeout in seconds, default 60
        }

    Return (when platform not specified, returns results from both platforms):
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "What do you think about this？",
                "result": {
                    "agent_id": 0,
                    "prompt": "...",
                    "platforms": {
                        "twitter": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit": {"agent_id": 0, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }

    Return（Specifiedplatform）：
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "What do you think about this？",
                "result": {
                    "agent_id": 0,
                    "response": "I think...",
                    "platform": "twitter",
                    "timestamp": "2025-12-08T10:00:00"
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        agent_id = data.get('agent_id')
        prompt = data.get('prompt')
        timeout = data.get('timeout', 60)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        if agent_id is None:
            return jsonify({
                "success": False,
                "error": "Please provide agent_id"
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": "Please provide prompt"
            }), 400

        # Route to SMS interview handler
        manager_for_mode = SimulationManager()
        optimized_prompt = optimize_interview_prompt(prompt)
        result = _interview_sms_agents(
            simulation_id,
            [{"agent_id": agent_id, "prompt": optimized_prompt}],
            manager_for_mode,
        )
        # Return the single agent's result directly
        single = next(iter(result.get("results", {}).values()), result)
        return jsonify({"success": True, "data": single})
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"WaitInterviewResponse timeout: {str(e)}"
        }), 504
        
    except Exception as e:
        logger.error(f"InterviewFailed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/batch', methods=['POST'])
def interview_agents_batch():
    """
    Batch interview multipleAgent

    Note: This feature requires simulation to be in a running or completed state.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",       // Required，Simulation ID
            "interviews": [                    // Required，Interview list
                {
                    "agent_id": 0,
                    "prompt": "Your opinion onAWhat do you think？",
                    "platform": "twitter"      // Optional, interview this agent on specified platform
                },
                {
                    "agent_id": 1,
                    "prompt": "Your opinion onBWhat do you think？"  // Not specifiedplatform[then]UseDefaultValue
                }
            ],
            "platform": "reddit",              // Optional, Default platform (overridden by each item's platform)
                                               // When not specified: Both platforms in dual-platform simulations, single platform in single-platform simulations
            "timeout": 120                     // Optional, timeout in seconds, default 120
        }

    Returns:
        {
            "success": true,
            "data": {
                "interviews_count": 2,
                "result": {
                    "interviews_count": 4,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        "twitter_1": {"agent_id": 1, "response": "...", "platform": "twitter"},
                        "reddit_1": {"agent_id": 1, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        interviews = data.get('interviews')
        platform = data.get('platform')  # Optional：twitter/reddit/None
        timeout = data.get('timeout', 120)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        if not interviews or not isinstance(interviews, list):
            return jsonify({
                "success": False,
                "error": "Please provide interviews（Interview list）"
            }), 400

        # Verify each interview item
        for i, interview in enumerate(interviews):
            if 'agent_id' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"Interview list item {i+1} missing agent_id"
                }), 400
            if 'prompt' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"Interview list item {i+1} missing prompt"
                }), 400

        manager_for_mode = SimulationManager()
        result = _interview_sms_agents(simulation_id, interviews, manager_for_mode)
        return jsonify({"success": True, "data": result})

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"Wait for batchInterviewResponse timeout: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"BatchInterviewFailed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/all', methods=['POST'])
def interview_all_agents():
    """
    Global interview - UseInterview all with same questionAgent

    Note: This feature requires simulation to be in a running or completed state.

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",            // Required，Simulation ID
            "prompt": "What is your overall view on this?",  // Required, interview question (avoid enabling agent to use tools)
            "platform": "reddit",                   // Optional, Specified platform (twitter/reddit)
                                                    // When not specified: Both platforms in dual-platform simulations, single platform in single-platform simulations
            "timeout": 180                          // Optional, timeout in seconds, default 180
        }

    Returns:
        {
            "success": true,
            "data": {
                "interviews_count": 50,
                "result": {
                    "interviews_count": 100,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        ...
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        prompt = data.get('prompt')

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": "Please provide prompt"
            }), 400

        # Load all agent IDs from profiles, then batch-interview them all
        import json as _json
        import os as _os
        manager_for_all = SimulationManager()
        sim_dir = manager_for_all._get_simulation_dir(simulation_id)
        profiles_path = _os.path.join(sim_dir, "reddit_profiles.json")
        profiles = []
        if _os.path.exists(profiles_path):
            with open(profiles_path, "r", encoding="utf-8") as _f:
                profiles = _json.load(_f)

        optimized_prompt = optimize_interview_prompt(prompt)
        interviews = [
            {"agent_id": p.get("user_id", i), "prompt": optimized_prompt}
            for i, p in enumerate(profiles)
        ]
        result = _interview_sms_agents(simulation_id, interviews, manager_for_all)
        return jsonify({"success": True, "data": result})

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"Wait for globalInterviewResponse timeout: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"GlobalInterviewFailed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/history', methods=['POST'])
def get_interview_history():
    """
    GetInterviewHistorical records

    Read all from simulation databaseInterviewRecord

    Request (JSON):
        {
            "simulation_id": "sim_xxxx",  // Required，Simulation ID
            "platform": "reddit",          // Optional，Platform type（reddit/twitter）
                                           // If not specified, return all history of both platforms
            "agent_id": 0,                 // Optional, Get interview history for only this agent
            "limit": 100                   // Optional，Return count，Default100
        }

    Returns:
        {
            "success": true,
            "data": {
                "count": 10,
                "history": [
                    {
                        "agent_id": 0,
                        "response": "I think...",
                        "prompt": "What do you think about this？",
                        "timestamp": "2025-12-08T10:00:00",
                        "platform": "reddit"
                    },
                    ...
                ]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        platform = data.get('platform')  # If not specified, return history of both platforms
        agent_id = data.get('agent_id')
        limit = data.get('limit', 100)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        return jsonify({
            "success": True,
            "data": {
                "count": 0,
                "history": []
            }
        })

    except Exception as e:
        logger.error(f"Failed to get interview history: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/env-status', methods=['POST'])
def get_env_status():
    """
    Get simulation environment status

    Check if simulation environment is alive (can receive interview requests).

    Request (JSON):
        {
            "simulation_id": "sim_xxxx"  // Required，Simulation ID
        }

    Returns:
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "env_alive": true,
                "twitter_available": true,
                "reddit_available": true,
                "message": "Environment running, ready to receive interview requests"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        manager_env = SimulationManager()
        state_env = manager_env.get_simulation(simulation_id)
        env_alive = state_env is not None and state_env.status.value in ("running", "completed")

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "env_alive": env_alive,
                "message": "SMS simulation ready for interviews" if env_alive else "Simulation not running"
            }
        })

    except Exception as e:
        logger.error(f"Failed to get environment status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/close-env', methods=['POST'])
def close_simulation_env():
    """
    Close simulation environment
    
    Send close environment command to simulation to gracefully exit and wait for completion.

    Note: This is different from /stop. /stop terminates the simulation abruptly.
    This interface lets the simulation gracefully close the environment and exit.
    
    Request (JSON):
        {
            "simulation_id": "sim_xxxx",  // Required，Simulation ID
            "timeout": 30                  // Optional, timeout in seconds, default 30
        }
    
    Returns:
        {
            "success": true,
            "data": {
                "message": "Environment close command sent",
                "result": {...},
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        timeout = data.get('timeout', 30)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_id"
            }), 400

        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.COMPLETED
            manager._save_simulation_state(state)

        return jsonify({
            "success": True,
            "data": {"message": "Simulation marked as completed", "simulation_id": simulation_id}
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"Failed to close environment: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
