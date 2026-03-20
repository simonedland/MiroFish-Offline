"""
Scenario API — description-based simulation flow.

Endpoints:
  POST /api/scenario/parse          — parse description → ScenarioDefinition preview
  POST /api/scenario/create         — create simulation from description (async)
  GET  /api/simulation/<sim_id>/groups — return scenario_definition.json for a simulation
"""

import os
import json
import traceback

from flask import request, jsonify

from . import scenario_bp
from ..services.scenario_parser import ScenarioParser
from ..services.simulation_manager import SimulationManager
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.scenario')


@scenario_bp.route('/scenario/parse', methods=['POST'])
def parse_scenario():
    """
    Synchronously parse a free-form scenario description.

    Request body:
        { "description": "<text>" }

    Response:
        { "success": true, "data": <ScenarioDefinition dict> }
    """
    try:
        body = request.get_json(silent=True) or {}
        description = body.get('description', '').strip()

        if not description:
            return jsonify({'success': False, 'error': 'description is required'}), 400

        logger.info(f"Parsing scenario description ({len(description)} chars)...")
        parser = ScenarioParser()
        scenario = parser.parse(description)

        return jsonify({
            'success': True,
            'data': scenario.to_dict(),
        })

    except Exception as exc:
        logger.error(f"Scenario parse failed: {exc}")
        return jsonify({
            'success': False,
            'error': str(exc),
            'traceback': traceback.format_exc(),
        }), 500


@scenario_bp.route('/scenario/create', methods=['POST'])
def create_scenario():
    """
    Create a simulation from a free-form scenario description (non-blocking).

    The background thread parses the description, generates profiles and config,
    then transitions the simulation to READY.  Poll GET /api/simulation/<id>
    to track progress.

    Request body:
        {
          "description": "<text>"
        }

    Response:
        { "success": true, "data": { "simulation_id": "...", "status": "preparing" } }
    """
    try:
        body = request.get_json(silent=True) or {}
        description = body.get('description', '').strip()

        if not description:
            return jsonify({'success': False, 'error': 'description is required'}), 400

        agents_per_batch = int(body.get('agents_per_batch', 15))

        manager = SimulationManager()
        simulation_id = manager.create_from_description(
            description=description,
            agents_per_batch=agents_per_batch,
        )

        logger.info(f"Created description-based simulation: {simulation_id}")
        return jsonify({
            'success': True,
            'data': {
                'simulation_id': simulation_id,
                'status': 'preparing',
            },
        })

    except Exception as exc:
        logger.error(f"Scenario create failed: {exc}")
        return jsonify({
            'success': False,
            'error': str(exc),
            'traceback': traceback.format_exc(),
        }), 500


@scenario_bp.route('/simulation/<simulation_id>/groups', methods=['GET'])
def get_simulation_groups(simulation_id: str):
    """
    Return the scenario_definition.json for a description-based simulation.

    Response:
        { "success": true, "data": <ScenarioDefinition dict> }
    """
    try:
        manager = SimulationManager()
        sim_dir = manager._get_simulation_dir(simulation_id)
        scenario_path = os.path.join(sim_dir, 'scenario_definition.json')

        if not os.path.exists(scenario_path):
            # May still be in-flight; fall back to state.scenario_definition
            state = manager.get_simulation(simulation_id)
            if state and state.scenario_definition:
                return jsonify({'success': True, 'data': state.scenario_definition})
            return jsonify({
                'success': False,
                'error': f'No scenario definition found for simulation {simulation_id}',
            }), 404

        with open(scenario_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return jsonify({'success': True, 'data': data})

    except Exception as exc:
        logger.error(f"Get simulation groups failed: {exc}")
        return jsonify({
            'success': False,
            'error': str(exc),
            'traceback': traceback.format_exc(),
        }), 500
