import sqlite3
import os
import time
from typing import Optional

def _get_db_path(simulation_id: str) -> str:
    if not simulation_id or '..' in simulation_id or '/' in simulation_id or '\\' in simulation_id:
        raise ValueError(f"Invalid simulation_id: {simulation_id!r}")
    sim_dir = os.path.join("uploads", "simulations", simulation_id)
    os.makedirs(sim_dir, exist_ok=True)
    return os.path.join(sim_dir, "sms.db")

def init_db(simulation_id: str) -> None:
    """Create SMS tables if they don't exist."""
    db_path = _get_db_path(simulation_id)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS sms_agents (
                simulation_id TEXT NOT NULL,
                agent_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                persona TEXT,
                PRIMARY KEY (simulation_id, agent_id)
            );

            CREATE TABLE IF NOT EXISTS sms_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulation_id TEXT NOT NULL,
                sender_phone TEXT NOT NULL,
                receiver_phone TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                receiver_name TEXT NOT NULL,
                content TEXT NOT NULL,
                round_num INTEGER NOT NULL,
                timestamp REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_thread
                ON sms_messages(simulation_id, sender_phone, receiver_phone);
        """)
        conn.commit()
    finally:
        conn.close()

def register_agents(simulation_id: str, profiles: list) -> None:
    """Populate sms_agents from a list of OasisAgentProfile objects."""
    db_path = _get_db_path(simulation_id)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        for profile in profiles:
            cursor.execute(
                "INSERT OR REPLACE INTO sms_agents (simulation_id, agent_id, name, phone_number, persona) VALUES (?, ?, ?, ?, ?)",
                (simulation_id, profile.user_id, profile.name, getattr(profile, 'phone_number', ''), profile.persona)
            )
        conn.commit()
    finally:
        conn.close()

def insert_message(simulation_id: str, msg: dict) -> None:
    """Store a single SMS message."""
    db_path = _get_db_path(simulation_id)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO sms_messages
               (simulation_id, sender_phone, receiver_phone, sender_name, receiver_name, content, round_num, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                simulation_id,
                msg['sender_phone'],
                msg['receiver_phone'],
                msg['sender_name'],
                msg['receiver_name'],
                msg['content'],
                msg['round_num'],
                msg.get('timestamp', time.time())
            )
        )
        conn.commit()
    finally:
        conn.close()

def get_thread(simulation_id: str, phone_a: str, phone_b: str, limit: int = 20) -> list:
    """Get rolling window of messages between two agents (most recent N, ordered chronologically)."""
    db_path = _get_db_path(simulation_id)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        # Get most recent N messages in either direction between these two phones
        cursor.execute(
            """SELECT * FROM (
                SELECT * FROM sms_messages
                WHERE simulation_id = ?
                  AND ((sender_phone = ? AND receiver_phone = ?)
                       OR (sender_phone = ? AND receiver_phone = ?))
                ORDER BY timestamp DESC
                LIMIT ?
            ) ORDER BY timestamp ASC""",
            (simulation_id, phone_a, phone_b, phone_b, phone_a, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_recent_community_messages(simulation_id: str, limit: int = 8) -> list:
    """Recent messages from all agents across all threads, newest first."""
    db_path = _get_db_path(simulation_id)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT sender_name, receiver_name, content FROM sms_messages
               WHERE simulation_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (simulation_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_agent_recent_messages(simulation_id: str, phone: str, limit: int = 5) -> list:
    """Recent messages where this agent is sender or receiver, across all threads."""
    db_path = _get_db_path(simulation_id)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT sender_name, receiver_name, content FROM sms_messages
               WHERE simulation_id = ?
                 AND (sender_phone = ? OR receiver_phone = ?)
               ORDER BY timestamp DESC LIMIT ?""",
            (simulation_id, phone, phone, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_all_threads_for_agent(simulation_id: str, phone: str) -> list:
    """Get all conversation partners for a given phone number with last message."""
    db_path = _get_db_path(simulation_id)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        # Get distinct partners
        cursor.execute(
            """SELECT
                CASE WHEN sender_phone = ? THEN receiver_phone ELSE sender_phone END as other_phone,
                CASE WHEN sender_phone = ? THEN receiver_name ELSE sender_name END as other_name,
                COUNT(*) as message_count,
                MAX(timestamp) as last_timestamp
               FROM sms_messages
               WHERE simulation_id = ? AND (sender_phone = ? OR receiver_phone = ?)
               GROUP BY other_phone""",
            (phone, phone, simulation_id, phone, phone)
        )
        rows = [dict(row) for row in cursor.fetchall()]
        # Fetch last message content for each partner
        for row in rows:
            cursor.execute(
                """SELECT content FROM sms_messages
                   WHERE simulation_id = ?
                     AND ((sender_phone = ? AND receiver_phone = ?)
                          OR (sender_phone = ? AND receiver_phone = ?))
                   ORDER BY timestamp DESC LIMIT 1""",
                (simulation_id, phone, row['other_phone'], row['other_phone'], phone)
            )
            result = cursor.fetchone()
            row['last_message'] = result['content'] if result else ''
        return rows
    finally:
        conn.close()

def get_messages_by_round(simulation_id: str, phone_a: str, phone_b: str, round_num: int) -> list:
    """Get messages between two agents filtered by round number."""
    db_path = _get_db_path(simulation_id)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT * FROM sms_messages
               WHERE simulation_id = ?
                 AND ((sender_phone = ? AND receiver_phone = ?)
                      OR (sender_phone = ? AND receiver_phone = ?))
                 AND round_num = ?
               ORDER BY timestamp ASC""",
            (simulation_id, phone_a, phone_b, phone_b, phone_a, round_num)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_all_messages(simulation_id: str, limit: int = 500) -> list:
    """All messages for a simulation, ordered chronologically (for report analysis)."""
    db_path = _get_db_path(simulation_id)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT sender_name, receiver_name, content, round_num
               FROM sms_messages
               WHERE simulation_id = ?
               ORDER BY timestamp ASC
               LIMIT ?""",
            (simulation_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_message_stats(simulation_id: str) -> dict:
    """Per-agent message counts, total messages, and round range (for report analysis)."""
    db_path = _get_db_path(simulation_id)
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sender_name, COUNT(*) as sent FROM sms_messages WHERE simulation_id = ? GROUP BY sender_name ORDER BY sent DESC",
            (simulation_id,)
        )
        sent_counts = {row['sender_name']: row['sent'] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT receiver_name, COUNT(*) as received FROM sms_messages WHERE simulation_id = ? GROUP BY receiver_name ORDER BY received DESC",
            (simulation_id,)
        )
        recv_counts = {row['receiver_name']: row['received'] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT COUNT(*) as total, MIN(round_num) as min_round, MAX(round_num) as max_round FROM sms_messages WHERE simulation_id = ?",
            (simulation_id,)
        )
        row = cursor.fetchone()
        total = row['total'] if row else 0
        min_round = row['min_round'] if row else 0
        max_round = row['max_round'] if row else 0

        all_agents = set(sent_counts) | set(recv_counts)
        per_agent = {
            name: {"sent": sent_counts.get(name, 0), "received": recv_counts.get(name, 0)}
            for name in all_agents
        }
        return {"total_messages": total, "rounds": {"min": min_round, "max": max_round}, "per_agent": per_agent}
    finally:
        conn.close()
