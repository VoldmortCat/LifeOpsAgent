"""Database models for User and Conversation management.
SQLite-based persistence for users, conversations, and messages.
"""

import sqlite3
import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("lifeops.db")

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "lifeops.db")


def _get_db() -> sqlite3.Connection:
    """Get a database connection (creates tables if needed)."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_tables(conn)
    return conn


def _init_tables(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            thread_id TEXT NOT NULL,
            title TEXT DEFAULT '新对话',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, thread_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            msg_type TEXT DEFAULT 'text',
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_user
            ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id);
    """)
    conn.commit()


# ====================== User Operations ======================


def create_user(username: str, password_hash: str, display_name: str = "") -> Optional[int]:
    """Create a new user. Returns user_id or None on conflict."""
    conn = _get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
            (username, password_hash, display_name or username),
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        logger.warning("User already exists: %s", username)
        return None
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Get a user by username."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash, display_name, avatar, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Get a user by id."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, username, display_name, avatar, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


# ====================== Conversation Operations ======================


def create_conversation(user_id: int, thread_id: str, title: str = "新对话") -> Optional[int]:
    """Create a new conversation. Returns conversation_id or None."""
    conn = _get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO conversations (user_id, thread_id, title) VALUES (?, ?, ?)",
            (user_id, thread_id, title),
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Thread ID already exists, get it
        row = conn.execute(
            "SELECT id FROM conversations WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def get_user_conversations(user_id: int) -> List[Dict[str, Any]]:
    """Get all conversations for a user."""
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT c.id, c.thread_id, c.title, c.created_at, c.updated_at,
                      (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) as msg_count
               FROM conversations c
               WHERE c.user_id = ?
               ORDER BY c.updated_at DESC""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation(conversation_id: int) -> Optional[Dict[str, Any]]:
    """Get a conversation by id."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, user_id, thread_id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_conversation_by_thread(user_id: int, thread_id: str) -> Optional[Dict[str, Any]]:
    """Get a conversation by user_id and thread_id."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, user_id, thread_id, title, created_at, updated_at FROM conversations WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_conversation_title(conversation_id: int, title: str) -> bool:
    """Update conversation title."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = datetime('now') WHERE id = ?",
            (title, conversation_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("Failed to update conversation title: %s", e)
        return False
    finally:
        conn.close()


def delete_conversation(conversation_id: int, user_id: int) -> bool:
    """Delete a conversation (only if it belongs to the user)."""
    conn = _get_db()
    try:
        conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("Failed to delete conversation: %s", e)
        return False
    finally:
        conn.close()


# ====================== Message Operations ======================


def save_message(conversation_id: int, role: str, content: str, msg_type: str = "text", metadata: dict = None) -> int:
    """Save a message to a conversation. Returns message_id."""
    conn = _get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, msg_type, metadata) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, msg_type, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        # Update conversation's updated_at
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_conversation_messages(conversation_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Get messages for a conversation."""
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT id, role, content, msg_type, metadata, created_at
               FROM messages
               WHERE conversation_id = ?
               ORDER BY id ASC
               LIMIT ?""",
            (conversation_id, limit),
        ).fetchall()
        result = []
        for r in rows:
            msg = dict(r)
            try:
                msg["metadata"] = json.loads(msg["metadata"])
            except (json.JSONDecodeError, TypeError):
                msg["metadata"] = {}
            result.append(msg)
        return result
    finally:
        conn.close()


def get_or_create_conversation(user_id: int, thread_id: str, title: str = "新对话") -> Dict[str, Any]:
    """Get existing conversation or create a new one."""
    existing = get_conversation_by_thread(user_id, thread_id)
    if existing:
        return existing

    conv_id = create_conversation(user_id, thread_id, title)
    conv = get_conversation(conv_id)
    return conv or {"id": conv_id, "thread_id": thread_id, "title": title}
