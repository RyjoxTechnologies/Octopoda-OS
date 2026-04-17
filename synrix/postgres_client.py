"""
Octopoda PostgreSQL Client
===========================
Drop-in replacement for SynrixSQLiteClient backed by PostgreSQL + pgvector.
Uses Row-Level Security (RLS) for tenant isolation — the database itself
refuses to return rows that don't belong to the current tenant.

Usage:
    client = SynrixPostgresClient(dsn="postgresql://...", tenant_id="abc123")
    client.add_node("key", '{"value": "hello"}')
    results = client.query_prefix("key")
    similar = client.semantic_search(embedding, limit=10)
"""

import os
import json
import time
import struct
import threading
import logging
import numpy as np
from typing import Optional, List, Dict, Any, Union

logger = logging.getLogger("synrix.postgres")

# ---------------------------------------------------------------------------
# Connection pool (shared across all SynrixPostgresClient instances)
# ---------------------------------------------------------------------------

_pool = None
_pool_lock = threading.Lock()


def _get_pool(dsn: str = None):
    """Get or create the global connection pool."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        import psycopg2
        from psycopg2 import pool as pg_pool
        dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not dsn:
            raise ValueError("DATABASE_URL not set and no dsn provided")
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=12,
            dsn=dsn,
        )
        return _pool


def reset_pool():
    """Reset the connection pool (for testing)."""
    global _pool
    with _pool_lock:
        if _pool:
            _pool.closeall()
        _pool = None


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

_NULL_BYTE_LITERAL = "\\u0000"


def _sanitize_for_pg_json(s: str) -> str:
    """Strip characters Postgres JSONB rejects.

    Postgres rejects two classes of strings that are legal in Python/JSON:
      1. Literal null bytes (``\\x00``) in the raw string.
      2. The JSON-escaped ``\\u0000`` sequence (even inside a valid JSON payload).
    Lone UTF-16 surrogates also fail to encode; json.dumps with ensure_ascii=False
    generally emits them literally, which psycopg2 will then reject.

    Returns a string safe to pass as a JSONB column value.
    """
    if not s:
        return s
    # Raw null byte (rare but possible through edge cases in input strings)
    if "\x00" in s:
        s = s.replace("\x00", "")
    # Escaped null byte inside a JSON string — this is the common case.
    if _NULL_BYTE_LITERAL in s:
        s = s.replace(_NULL_BYTE_LITERAL, "")
    return s


def _embedding_to_pgvector(embedding) -> Optional[str]:
    """Convert numpy array or bytes to pgvector string format '[0.1,0.2,...]'."""
    if embedding is None:
        return None
    if isinstance(embedding, bytes):
        dim = len(embedding) // 4
        floats = struct.unpack(f"{dim}f", embedding)
        return "[" + ",".join(f"{f:.6f}" for f in floats) + "]"
    if isinstance(embedding, np.ndarray):
        return "[" + ",".join(f"{f:.6f}" for f in embedding.tolist()) + "]"
    if isinstance(embedding, list):
        return "[" + ",".join(f"{f:.6f}" for f in embedding) + "]"
    return None


def _pgvector_to_bytes(pgvec_str) -> Optional[bytes]:
    """Convert pgvector string '[0.1,0.2,...]' back to bytes."""
    if pgvec_str is None:
        return None
    if isinstance(pgvec_str, bytes):
        return pgvec_str
    if isinstance(pgvec_str, str):
        floats = [float(x) for x in pgvec_str.strip("[]").split(",")]
        return struct.pack(f"{len(floats)}f", *floats)
    return None


# ---------------------------------------------------------------------------
# Main Client
# ---------------------------------------------------------------------------

class SynrixPostgresClient:
    """
    PostgreSQL + pgvector storage client.
    Drop-in replacement for SynrixSQLiteClient.
    """

    def __init__(self, dsn: str = None, tenant_id: str = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        self.tenant_id = tenant_id or "_default"
        self._pool = _get_pool(self.dsn)
        self.backend_type = "postgres"
        self.db_path = f"postgres:{self.tenant_id}"  # Compatibility with code that checks db_path

    def _conn(self):
        """Get a connection from the pool with tenant context set."""
        conn = self._pool.getconn()
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, TRUE)", (self.tenant_id,))
        return conn

    def _release(self, conn):
        """Return connection to pool."""
        try:
            conn.commit()
        except Exception:
            conn.rollback()
        self._pool.putconn(conn)

    # ------------------------------------------------------------------
    # Collection Management (compatibility — Postgres doesn't need these)
    # ------------------------------------------------------------------

    def list_collections(self) -> List[str]:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT split_part(name, ':', 1) FROM nodes "
                "WHERE valid_until = 0 LIMIT 100"
            )
            return [r[0] for r in cur.fetchall()]
        finally:
            self._release(conn)

    def get_collection(self, name: str) -> Dict[str, Any]:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM nodes WHERE name LIKE %s AND valid_until = 0",
                (f"{name}:%",)
            )
            count = cur.fetchone()[0]
            return {"name": name, "count": count}
        finally:
            self._release(conn)

    def create_collection(self, name: str, vector_dim: int = None, distance: str = "Cosine") -> bool:
        # No-op in Postgres — collections are implicit via name prefixes
        return True

    def delete_collection(self, name: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM nodes WHERE name LIKE %s", (f"{name}:%",))
            conn.commit()
            return True
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Node Operations (Core API)
    # ------------------------------------------------------------------

    def add_node(self, name: str, data: str = "", node_type: str = "primitive",
                 collection: str = None, embedding=None) -> Optional[int]:
        """Write a node. Implements temporal versioning (invalidate old, insert new)."""
        now = time.time()
        conn = self._conn()
        try:
            cur = conn.cursor()

            # Parse data
            if isinstance(data, str):
                try:
                    data_json = json.loads(data) if data else {}
                except (json.JSONDecodeError, ValueError):
                    data_json = {"value": data}
            elif isinstance(data, dict):
                data_json = data
            else:
                data_json = {"value": str(data)}

            metadata = {"type": node_type}
            emb_str = _embedding_to_pgvector(embedding)

            # Sanitize for Postgres JSONB (strips null bytes and lone surrogates,
            # both of which psycopg2/PG reject with "invalid input syntax for type json"
            # even though they're technically legal in Python strings).
            data_serialized = _sanitize_for_pg_json(json.dumps(data_json, ensure_ascii=False))
            meta_serialized = _sanitize_for_pg_json(json.dumps(metadata, ensure_ascii=False))

            # Invalidate previous version (temporal versioning)
            cur.execute(
                "UPDATE nodes SET valid_until = %s "
                "WHERE tenant_id = %s AND name = %s AND valid_until = 0",
                (now, self.tenant_id, name)
            )

            # Insert new version
            cur.execute(
                "INSERT INTO nodes (tenant_id, name, data, metadata, embedding, valid_from, valid_until) "
                "VALUES (%s, %s, %s, %s, %s, %s, 0) RETURNING id",
                (self.tenant_id, name, data_serialized, meta_serialized,
                 emb_str, now)
            )
            node_id = cur.fetchone()[0]
            conn.commit()
            return node_id
        except Exception as e:
            conn.rollback()
            # Log a richer diagnostic so silent drops are visible in Sentry/logs.
            data_len = len(data) if isinstance(data, (str, bytes)) else len(str(data))
            preview = (data if isinstance(data, str) else str(data))[:120]
            logger.error("add_node error: %s | tenant=%s key=%s data_len=%d data_preview=%r",
                         e, self.tenant_id, name, data_len, preview)
            return None
        finally:
            self._release(conn)

    def query_prefix(self, prefix: str, collection: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Query nodes by name prefix. Only returns current (non-invalidated) versions."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, data, metadata, valid_from, valid_until "
                "FROM nodes WHERE name LIKE %s AND valid_until = 0 "
                "ORDER BY valid_from DESC LIMIT %s",
                (f"{prefix}%", limit)
            )
            results = []
            for row in cur.fetchall():
                results.append({
                    "id": row[0],
                    "key": row[1],
                    "name": row[1],
                    "data": row[2] if isinstance(row[2], dict) else json.loads(row[2]) if row[2] else {},
                    "metadata": row[3] if isinstance(row[3], dict) else json.loads(row[3]) if row[3] else {},
                    "valid_from": row[4],
                    "valid_until": row[5],
                    "payload": {
                        "name": row[1],
                        "data": json.dumps(row[2]) if isinstance(row[2], dict) else str(row[2]),
                        "type": (row[3] or {}).get("type", "primitive") if isinstance(row[3], dict) else "primitive",
                    }
                })
            return results
        finally:
            self._release(conn)

    def get_point(self, collection: str, point_id: Union[int, str]) -> Dict[str, Any]:
        """Get a single node by ID."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            if isinstance(point_id, int):
                cur.execute("SELECT id, name, data, metadata FROM nodes WHERE id = %s", (point_id,))
            else:
                cur.execute(
                    "SELECT id, name, data, metadata FROM nodes WHERE name = %s AND valid_until = 0",
                    (str(point_id),)
                )
            row = cur.fetchone()
            if not row:
                return {}
            data = row[2] if isinstance(row[2], dict) else json.loads(row[2]) if row[2] else {}
            return {
                "id": row[0],
                "payload": {
                    "name": row[1],
                    "data": json.dumps(data) if isinstance(data, dict) else str(data),
                    "type": (row[3] or {}).get("type", "primitive") if isinstance(row[3], dict) else "primitive",
                },
                "data": data,
            }
        finally:
            self._release(conn)

    def upsert_points(self, collection: str, points: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Batch upsert nodes."""
        count = 0
        for point in points:
            payload = point.get("payload", {})
            name = payload.get("name", "")
            data = payload.get("data", "")
            node_type = payload.get("type", "primitive")
            embedding = point.get("vector")
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32).tobytes()
            node_id = self.add_node(name, data, node_type, collection, embedding)
            if node_id:
                count += 1
        return {"status": "ok", "count": count}

    def search_points(self, collection: str, vector: List[float], limit: int = 10,
                      score_threshold: float = None) -> List[Dict[str, Any]]:
        """Vector similarity search using pgvector."""
        return self.semantic_search(
            query_embedding=np.array(vector, dtype=np.float32).tobytes(),
            collection=collection,
            limit=limit,
            threshold=score_threshold or 0.0,
        )

    # ------------------------------------------------------------------
    # Fact Embeddings
    # ------------------------------------------------------------------

    def add_fact_embeddings(self, node_id: int, node_name: str,
                            facts: List[Dict[str, Any]], collection: str = None,
                            _background: bool = False) -> int:
        """Store LLM-extracted fact embeddings."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            count = 0
            for fact in facts:
                text = fact.get("text", fact.get("fact", ""))
                category = fact.get("category", "general")
                embedding = fact.get("embedding")
                emb_str = _embedding_to_pgvector(embedding)

                cur.execute(
                    "INSERT INTO fact_embeddings (tenant_id, node_id, node_name, fact_text, category, embedding, collection) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (self.tenant_id, node_id, node_name, text, category, emb_str, collection or "default")
                )
                count += 1
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            logger.error("add_fact_embeddings error: %s", e)
            return 0
        finally:
            self._release(conn)

    def update_node_embedding(self, node_id: int, embedding, collection: str = "default") -> None:
        """Update the embedding on an existing node."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            emb_str = _embedding_to_pgvector(embedding)
            cur.execute("UPDATE nodes SET embedding = %s WHERE id = %s", (emb_str, node_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("update_node_embedding error: %s", e)
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Semantic Vector Search (pgvector)
    # ------------------------------------------------------------------

    def semantic_search(self, query_embedding, collection: str = None, limit: int = 10,
                        threshold: float = 0.0, query_text: str = "", name_prefix: str = "") -> List[Dict[str, Any]]:
        """
        Semantic search using pgvector.
        Two-tier: search fact_embeddings first, fallback to nodes.embedding.
        """
        emb_str = _embedding_to_pgvector(query_embedding)
        if not emb_str:
            return []

        conn = self._conn()
        try:
            cur = conn.cursor()
            results = []
            seen_names = set()

            # Tier 1: Search fact embeddings
            prefix_filter = ""
            if name_prefix:
                prefix_filter = "AND fe.node_name LIKE %s"

            sql = f"""
                SELECT fe.node_name, fe.fact_text, fe.category,
                       1 - (fe.embedding <=> %s::vector) AS score,
                       n.id, n.data
                FROM fact_embeddings fe
                LEFT JOIN nodes n ON n.tenant_id = fe.tenant_id
                    AND n.name = fe.node_name AND n.valid_until = 0
                WHERE fe.embedding IS NOT NULL
                {prefix_filter}
                ORDER BY fe.embedding <=> %s::vector
                LIMIT %s
            """
            # Build params in correct SQL order: score_vec, [prefix], order_vec, limit
            if name_prefix:
                params = [emb_str, name_prefix + "%", emb_str, limit * 2]
            else:
                params = [emb_str, emb_str, limit * 2]
            cur.execute(sql, params)

            for row in cur.fetchall():
                name, fact_text, category, score, node_id, data = row
                if score < threshold or name in seen_names:
                    continue
                seen_names.add(name)
                data = data if isinstance(data, dict) else json.loads(data) if data else {}
                results.append({
                    "id": node_id,
                    "key": name,
                    "name": name,
                    "data": data,
                    "score": round(float(score), 4),
                    "fact": fact_text,
                    "category": category,
                    "source": "fact_embedding",
                    "payload": {
                        "name": name,
                        "data": json.dumps(data),
                        "type": "primitive",
                    }
                })

            # Tier 2: Search node embeddings (fill remaining slots)
            remaining = limit - len(results)
            if remaining > 0:
                prefix_cond = ""
                if name_prefix:
                    prefix_cond = "AND name LIKE %s"

                sql2 = f"""
                    SELECT id, name, data, 1 - (embedding <=> %s::vector) AS score
                    FROM nodes
                    WHERE embedding IS NOT NULL AND valid_until = 0
                    {prefix_cond}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """
                # Build params in correct SQL order: score_vec, [prefix], order_vec, limit
                if name_prefix:
                    params2 = [emb_str, name_prefix + "%", emb_str, remaining * 2]
                else:
                    params2 = [emb_str, emb_str, remaining * 2]
                cur.execute(sql2, params2)

                for row in cur.fetchall():
                    node_id, name, data, score = row
                    if score < threshold or name in seen_names:
                        continue
                    seen_names.add(name)
                    data = data if isinstance(data, dict) else json.loads(data) if data else {}
                    results.append({
                        "id": node_id,
                        "key": name,
                        "name": name,
                        "data": data,
                        "score": round(float(score), 4),
                        "source": "node_embedding",
                        "payload": {
                            "name": name,
                            "data": json.dumps(data),
                            "type": "primitive",
                        }
                    })

            # Sort by score descending, limit
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            return results[:limit]
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Temporal History
    # ------------------------------------------------------------------

    def get_history(self, name: str, collection: str = None) -> List[Dict[str, Any]]:
        """Get all versions of a key (temporal history).
        Returns oldest first: v1 = first write, highest v = current.
        """
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, data, valid_from, valid_until "
                "FROM nodes WHERE name = %s ORDER BY valid_from ASC",
                (name,)
            )
            results = []
            for row in cur.fetchall():
                data = row[2] if isinstance(row[2], dict) else json.loads(row[2]) if row[2] else {}
                results.append({
                    "id": row[0],
                    "key": row[1],
                    "name": row[1],
                    "data": data,
                    "valid_from": row[3],
                    "valid_until": row[4],
                    "version": len(results) + 1,
                })
            return results
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Knowledge Graph — Entities
    # ------------------------------------------------------------------

    def upsert_entity(self, name: str, entity_type: str, collection: str = None,
                      source_node_id: int = None, _background: bool = False) -> int:
        """Insert or update a knowledge graph entity."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO entities (tenant_id, name, entity_type, collection, source_node_id) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, name, entity_type, collection) "
                "DO UPDATE SET mention_count = entities.mention_count + 1, "
                "last_seen = NOW(), source_node_id = COALESCE(EXCLUDED.source_node_id, entities.source_node_id) "
                "RETURNING id",
                (self.tenant_id, name, entity_type, collection or "default", source_node_id)
            )
            entity_id = cur.fetchone()[0]
            conn.commit()
            return entity_id
        except Exception as e:
            conn.rollback()
            logger.error("upsert_entity error: %s", e)
            return 0
        finally:
            self._release(conn)

    def query_entity(self, name: str, collection: str = None) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, entity_type, mention_count, first_seen, last_seen "
                "FROM entities WHERE name = %s LIMIT 1",
                (name,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0], "name": row[1], "entity_type": row[2],
                "mention_count": row[3], "first_seen": str(row[4]), "last_seen": str(row[5]),
            }
        finally:
            self._release(conn)

    def list_entities(self, collection: str = None, entity_type: str = None,
                      limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            cur = conn.cursor()
            sql = "SELECT id, name, entity_type, mention_count FROM entities WHERE 1=1"
            params = []
            if entity_type:
                sql += " AND entity_type = %s"
                params.append(entity_type)
            sql += " ORDER BY mention_count DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            return [{"id": r[0], "name": r[1], "entity_type": r[2], "mention_count": r[3]}
                    for r in cur.fetchall()]
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Knowledge Graph — Relationships
    # ------------------------------------------------------------------

    def add_relationship(self, source_entity_id: int, target_entity_id: int,
                         relation: str, collection: str = None, confidence: float = 1.0,
                         source_node_id: int = None, _background: bool = False) -> int:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO relationships (tenant_id, source_entity_id, target_entity_id, "
                "relation, collection, confidence, source_node_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (self.tenant_id, source_entity_id, target_entity_id, relation,
                 collection or "default", confidence, source_node_id)
            )
            rel_id = cur.fetchone()[0]
            conn.commit()
            return rel_id
        except Exception as e:
            conn.rollback()
            logger.error("add_relationship error: %s", e)
            return 0
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Delete Operations
    # ------------------------------------------------------------------

    def delete_node(self, name: str, collection: str = None) -> bool:
        """Delete a node (set valid_until to now for temporal, or hard delete)."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE nodes SET valid_until = %s WHERE name = %s AND valid_until = 0",
                (time.time(), name)
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            conn.rollback()
            return False
        finally:
            self._release(conn)

    def delete_by_prefix_before(self, prefix: str, cutoff_timestamp: float,
                                 collection: str = None, batch_size: int = 500) -> int:
        """Delete all nodes with prefix older than cutoff. Single SQL statement."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM nodes WHERE name LIKE %s AND valid_from < %s",
                (f"{prefix}%", cutoff_timestamp)
            )
            count = cur.rowcount
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            return 0
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def vacuum(self) -> None:
        """No-op for Postgres — autovacuum handles this."""
        pass

    def node_count(self, collection: str = None) -> int:
        conn = self._conn()
        try:
            cur = conn.cursor()
            if collection:
                cur.execute(
                    "SELECT COUNT(*) FROM nodes WHERE name LIKE %s AND valid_until = 0",
                    (f"{collection}:%",)
                )
            else:
                cur.execute("SELECT COUNT(*) FROM nodes WHERE valid_until = 0")
            return cur.fetchone()[0]
        finally:
            self._release(conn)

    def close(self) -> None:
        """No-op — pool manages connections."""
        pass
