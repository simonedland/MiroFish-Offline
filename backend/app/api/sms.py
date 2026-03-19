import os
import json
from flask import Blueprint, request, jsonify
import logging

from ..services.sms_db import (
    get_thread,
    get_all_threads_for_agent,
    get_messages_by_round,
)

logger = logging.getLogger("mirofish.sms")

sms_bp = Blueprint("sms", __name__)


def _get_sim_id():
    """Extract simulation_id from query string or JSON body."""
    sim_id = request.args.get("simulation_id")
    if not sim_id and request.is_json:
        sim_id = request.get_json(silent=True, force=True).get("simulation_id")
    return sim_id


def _agents_db_path(simulation_id: str) -> str:
    return os.path.join("uploads", "simulations", simulation_id, "sms.db")


@sms_bp.route("/agents", methods=["GET"])
def get_sms_agents():
    """GET /api/simulation/sms/agents?simulation_id=<id>"""
    import sqlite3
    simulation_id = _get_sim_id()
    if not simulation_id:
        return jsonify({"success": False, "error": "simulation_id required"}), 400

    db_path = _agents_db_path(simulation_id)
    if not os.path.exists(db_path):
        return jsonify({"success": True, "data": []})

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id, name, phone_number, persona FROM sms_agents WHERE simulation_id = ? ORDER BY agent_id",
            (simulation_id,)
        )
        agents = [dict(row) for row in cursor.fetchall()]
        return jsonify({"success": True, "data": agents})
    except Exception as e:
        logger.exception("Error fetching SMS agents")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@sms_bp.route("/threads/<phone>", methods=["GET"])
def get_agent_threads(phone):
    """GET /api/simulation/sms/threads/<phone>?simulation_id=<id>"""
    simulation_id = _get_sim_id()
    if not simulation_id:
        return jsonify({"success": False, "error": "simulation_id required"}), 400

    try:
        threads = get_all_threads_for_agent(simulation_id, phone)
        return jsonify({"success": True, "data": threads})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Error fetching SMS threads")
        return jsonify({"success": False, "error": str(e)}), 500


@sms_bp.route("/thread/<phone_a>/<phone_b>", methods=["GET"])
def get_thread_between(phone_a, phone_b):
    """GET /api/simulation/sms/thread/<phone_a>/<phone_b>?simulation_id=<id>&round=<N>"""
    simulation_id = _get_sim_id()
    if not simulation_id:
        return jsonify({"success": False, "error": "simulation_id required"}), 400

    round_num = request.args.get("round", type=int)

    try:
        if round_num is not None:
            messages = get_messages_by_round(simulation_id, phone_a, phone_b, round_num)
        else:
            messages = get_thread(simulation_id, phone_a, phone_b, limit=200)
        return jsonify({"success": True, "data": messages})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Error fetching SMS thread")
        return jsonify({"success": False, "error": str(e)}), 500


@sms_bp.route("/events", methods=["GET"])
def get_sms_events():
    """GET /api/simulation/sms/events?simulation_id=<id>&since=<timestamp>"""
    simulation_id = _get_sim_id()
    if not simulation_id:
        return jsonify({"success": False, "error": "simulation_id required"}), 400

    since = request.args.get("since", type=float, default=0.0)
    events_path = os.path.join("uploads", "simulations", simulation_id, "sms_events.jsonl")

    if not os.path.exists(events_path):
        return jsonify({"success": True, "data": []})

    events = []
    try:
        with open(events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("timestamp", 0) > since:
                        events.append(event)
                except json.JSONDecodeError:
                    continue
        return jsonify({"success": True, "data": events})
    except Exception as e:
        logger.exception("Error fetching SMS events")
        return jsonify({"success": False, "error": str(e)}), 500
