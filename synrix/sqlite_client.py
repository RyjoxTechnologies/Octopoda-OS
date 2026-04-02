"""
SYNRIX SQLite Client - Persistent Backend
==========================================
Drop-in replacement for SynrixMockClient that persists data to SQLite.
ACID-compliant with WAL mode for concurrent reads and crash safety.

Features:
    - Semantic vector search (optional, requires sentence-transformers)
    - Temporal versioning (track how memories change over time)
    - Knowledge graph (entities + relationships in SQLite)
    - Garbage collection with prefix-based TTL

Usage:
    from synrix.sqlite_client import SynrixSQLiteClient

    client = SynrixSQLiteClient("~/.synrix/data/synrix.db")
    client.create_collection("agent_memory")
    node_id = client.add_node("agents:a1:key", '{"value": "hello"}', collection="agent_memory")
    results = client.query_prefix("agents:a1:", collection="agent_memory")
"""
import logging

logger = logging.getLogger(__name__)


import os
import json
import time
import struct
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional, Dict, List, Any, Union, Tuple

try:
    from synrix.vector_index import VectorIndex, FactIndex, HAS_FAISS
    HAS_VECTOR_INDEX = True
except ImportError:
    HAS_VECTOR_INDEX = False
    HAS_FAISS = False


@contextmanager
def _combined_lock(lock, conn_cm):
    """Acquire a threading lock and a connection context manager together.

    Used by foreground write paths: ``with _combined_lock(self._write_lock, self._conn()) as conn:``
    Background paths skip the lock and use ``self._conn()`` directly, relying on
    SQLite WAL + busy_timeout for write serialization.
    """
    with lock:
        with conn_cm as conn:
            yield conn


class SynrixSQLiteClient:
    """
    SQLite-backed persistent client for Synrix.

    Implements the same interface as SynrixMockClient so it can be used
    as a drop-in replacement anywhere the mock is used.

    Features:
        - ACID guarantees via SQLite WAL mode
        - O(k) prefix queries via indexed LIKE
        - Thread-safe with write locking
        - Data survives process restarts
        - Temporal versioning with history
        - Knowledge graph (entities + relationships)
        - Semantic vector search (when numpy available)
        - Zero required external dependencies
    """

    # Class-level shared index cache: (db_path, collection) -> index
    # Multiple SynrixSQLiteClient instances pointing to the same DB share
    # cached FAISS indices, avoiding expensive index rebuilds per-thread.
    _shared_node_indices: Dict[str, Dict[str, Any]] = {}
    _shared_fact_indices: Dict[str, Dict[str, Any]] = {}
    _shared_index_lock = threading.Lock()

    def __init__(self, db_path: str = None):
        if db_path is None:
            data_dir = os.path.expanduser("~/.synrix/data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "synrix.db")
        else:
            db_path = os.path.expanduser(db_path)
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        self.db_path = os.path.abspath(db_path)
        self._write_lock = threading.Lock()

        # Compatibility attributes
        self.host = "sqlite"
        self.port = 0
        self.timeout = 30
        self.base_url = f"sqlite://{db_path}"

        # Instance references to shared index cache for this db_path
        self._index_lock = self._shared_index_lock
        if self.db_path not in self._shared_node_indices:
            self._shared_node_indices[self.db_path] = {}
        if self.db_path not in self._shared_fact_indices:
            self._shared_fact_indices[self.db_path] = {}
        self._node_indices = self._shared_node_indices[self.db_path]
        self._fact_indices = self._shared_fact_indices[self.db_path]

        self._init_db()

    def _init_db(self):
        """Create tables and configure SQLite for performance."""
        with self._conn() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA cache_size=-8000;
                PRAGMA temp_store=MEMORY;

                CREATE TABLE IF NOT EXISTS collections (
                    name TEXT PRIMARY KEY,
                    vector_dim INTEGER DEFAULT 128,
                    distance TEXT DEFAULT 'Cosine',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    id INTEGER PRIMARY KEY,
                    collection TEXT NOT NULL DEFAULT 'nodes',
                    name TEXT NOT NULL,
                    data TEXT DEFAULT '',
                    node_type TEXT DEFAULT 'primitive',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_col_name
                    ON nodes(collection, name);

                CREATE INDEX IF NOT EXISTS idx_nodes_name
                    ON nodes(name);

                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL DEFAULT 'nodes',
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    source_node_id INTEGER,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    mention_count INTEGER DEFAULT 1,
                    UNIQUE(collection, name, entity_type)
                );

                CREATE TABLE IF NOT EXISTS relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL DEFAULT 'nodes',
                    source_entity_id INTEGER NOT NULL,
                    target_entity_id INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    source_node_id INTEGER,
                    valid_from REAL NOT NULL,
                    valid_until REAL,
                    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
                    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
                    UNIQUE(collection, source_entity_id, target_entity_id, relation)
                );

                CREATE INDEX IF NOT EXISTS idx_entities_name
                    ON entities(collection, name);

                CREATE INDEX IF NOT EXISTS idx_entities_type
                    ON entities(collection, entity_type);

                CREATE INDEX IF NOT EXISTS idx_rel_source
                    ON relationships(source_entity_id);

                CREATE INDEX IF NOT EXISTS idx_rel_target
                    ON relationships(target_entity_id);

                CREATE TABLE IF NOT EXISTS fact_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL DEFAULT 'nodes',
                    node_id INTEGER NOT NULL,
                    node_name TEXT NOT NULL,
                    fact_text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_fact_emb_collection
                    ON fact_embeddings(collection);

                CREATE INDEX IF NOT EXISTS idx_fact_emb_node
                    ON fact_embeddings(collection, node_name);
            """)
            conn.commit()

            # Run migrations for columns added after v1
            self._migrate_schema(conn)

            # Create FTS5 full-text search index (for hybrid search)
            self._init_fts(conn)

    def _migrate_schema(self, conn):
        """Add new columns if they don't exist (backward compatible)."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()}

        migrations = []
        if "embedding" not in existing:
            migrations.append("ALTER TABLE nodes ADD COLUMN embedding BLOB DEFAULT NULL")
        if "valid_from" not in existing:
            migrations.append("ALTER TABLE nodes ADD COLUMN valid_from REAL DEFAULT NULL")
        if "valid_until" not in existing:
            migrations.append("ALTER TABLE nodes ADD COLUMN valid_until REAL DEFAULT NULL")
        if "version" not in existing:
            migrations.append("ALTER TABLE nodes ADD COLUMN version INTEGER DEFAULT 1")

        if migrations:
            for sql in migrations:
                conn.execute(sql)
            conn.commit()

    def _init_fts(self, conn):
        """Create FTS5 full-text search index for hybrid search.

        Standalone FTS5 table (not external content) to avoid column
        mapping issues. Stores its own copy of tokenized text.
        The rowid matches nodes.id for easy JOINs.
        """
        try:
            conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    name,
                    data,
                    collection UNINDEXED,
                    tokenize='porter unicode61'
                );
            """)
            conn.commit()
            self._has_fts = True
        except Exception:
            # FTS5 not available in this SQLite build (rare)
            self._has_fts = False

    def _sync_fts(self, conn, node_id: int, name: str, data: str, collection: str):
        """Insert or update the FTS index for a node."""
        if not getattr(self, '_has_fts', False):
            return
        try:
            # Remove any existing entry with this rowid
            conn.execute(
                "DELETE FROM nodes_fts WHERE rowid = ?", (node_id,)
            )
        except Exception:
            pass
        try:
            conn.execute(
                "INSERT INTO nodes_fts(rowid, name, data, collection) VALUES(?, ?, ?, ?)",
                (node_id, name, data, collection),
            )
        except Exception:
            pass  # FTS sync failure shouldn't break writes

    def _keyword_search(
        self, query: str, collection: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Full-text keyword search using FTS5.

        Returns results with BM25 relevance scores (lower = more relevant
        in SQLite FTS5, so we negate to make higher = better).
        """
        if not getattr(self, '_has_fts', False):
            return []

        try:
            # Tokenize query: split into words
            words = query.strip().split()
            if not words:
                return []

            # Build FTS5 query: each word OR'd, porter stemmer handles
            # morphological variants (allergies -> allergi, allergic -> allergi)
            fts_terms = []
            for word in words:
                clean = ''.join(c for c in word if c.isalnum())
                if clean and len(clean) >= 3:  # Skip very short words
                    fts_terms.append(clean)

            if not fts_terms:
                return []

            fts_query = " OR ".join(fts_terms)

            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT nodes_fts.rowid as fts_rowid,
                              n.id, n.name, n.data, n.node_type,
                              bm25(nodes_fts) as rank
                       FROM nodes_fts
                       JOIN nodes n ON nodes_fts.rowid = n.id
                       WHERE nodes_fts MATCH ?
                         AND nodes_fts.collection = ?
                         AND (n.valid_until IS NULL OR n.valid_until = 0)
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, collection, limit),
                ).fetchall()

            results = []
            for row in rows:
                bm25_score = -float(row["rank"])
                results.append({
                    "id": row["id"],
                    "bm25_score": bm25_score,
                    "payload": {
                        "name": row["name"],
                        "data": row["data"],
                        "type": row["node_type"],
                    },
                })

            return results
        except Exception:
            return []

    def _get_conn(self) -> sqlite3.Connection:
        """Get a new connection (SQLite connections are not thread-safe)."""
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.row_factory = sqlite3.Row
        # WAL mode: allows concurrent reads while writing, prevents lock conflicts
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        return conn

    @contextmanager
    def _conn(self):
        """Context manager that guarantees connection cleanup."""
        conn = self._get_conn()
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def list_collections(self) -> List[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT name FROM collections").fetchall()
            return [r["name"] for r in rows]

    def get_collection(self, name: str) -> Dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM collections WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                from .exceptions import SynrixNotFoundError
                raise SynrixNotFoundError(f"Collection '{name}' not found")

            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM nodes WHERE collection = ? AND (valid_until IS NULL OR valid_until = 0)",
                (name,),
            ).fetchone()["cnt"]

            return {
                "result": {
                    "name": row["name"],
                    "config": {
                        "params": {
                            "vectors": {
                                "size": row["vector_dim"],
                                "distance": row["distance"],
                            }
                        }
                    },
                    "points_count": count,
                }
            }

    def create_collection(
        self, name: str, vector_dim: Optional[int] = None, distance: str = "Cosine"
    ) -> bool:
        if vector_dim is None:
            vector_dim = 128
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO collections (name, vector_dim, distance, created_at)
                   VALUES (?, ?, ?, ?)""",
                (name, vector_dim, distance, time.time()),
            )
            conn.commit()
            return True

    def delete_collection(self, name: str) -> bool:
        with self._write_lock, self._conn() as conn:
            conn.execute("DELETE FROM fact_embeddings WHERE collection = ?", (name,))
            conn.execute("DELETE FROM nodes WHERE collection = ?", (name,))
            conn.execute("DELETE FROM entities WHERE collection = ?", (name,))
            conn.execute("DELETE FROM relationships WHERE collection = ?", (name,))
            conn.execute("DELETE FROM collections WHERE name = ?", (name,))
            conn.commit()
            return True

    # ------------------------------------------------------------------
    # Node operations (primary API used by SynrixAgentBackend)
    # ------------------------------------------------------------------

    def add_node(
        self,
        name: str,
        data: str = "",
        node_type: str = "primitive",
        collection: Optional[str] = None,
        embedding: Optional[bytes] = None,
    ) -> Optional[int]:
        """Add or update a node with temporal versioning.

        When a node with the same name already exists in the collection,
        the old version is invalidated (valid_until set) and a new version
        is inserted.  This preserves full history.

        Returns the ID of the new (current) node.
        """
        if collection is None:
            collection = "nodes"

        now = time.time()

        with self._write_lock, self._conn() as conn:
            try:
                # Ensure collection exists
                conn.execute(
                    """INSERT OR IGNORE INTO collections (name, vector_dim, distance, created_at)
                       VALUES (?, 128, 'Cosine', ?)""",
                    (collection, now),
                )

                # Check for existing current version
                existing = conn.execute(
                    """SELECT id, version FROM nodes
                       WHERE collection = ? AND name = ?
                         AND (valid_until IS NULL OR valid_until = 0)
                       ORDER BY version DESC LIMIT 1""",
                    (collection, name),
                ).fetchone()

                if existing:
                    old_id = existing["id"]
                    new_version = existing["version"] + 1

                    # Invalidate old version
                    conn.execute(
                        "UPDATE nodes SET valid_until = ? WHERE id = ?",
                        (now, old_id),
                    )

                    # Generate new ID for new version
                    node_id = hash(f"{collection}:{name}:v{new_version}") % (2**63)
                    if node_id < 0:
                        node_id = -node_id

                    conn.execute(
                        """INSERT OR REPLACE INTO nodes
                           (id, collection, name, data, node_type, created_at, updated_at,
                            embedding, valid_from, valid_until, version)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                        (node_id, collection, name, data, node_type, now, now,
                         embedding, now, new_version),
                    )

                    # Sync FTS: remove old version, add new
                    self._sync_fts(conn, node_id, name, data, collection)
                else:
                    # First version
                    node_id = hash(f"{collection}:{name}") % (2**63)
                    if node_id < 0:
                        node_id = -node_id

                    conn.execute(
                        """INSERT OR REPLACE INTO nodes
                           (id, collection, name, data, node_type, created_at, updated_at,
                            embedding, valid_from, valid_until, version)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)""",
                        (node_id, collection, name, data, node_type, now, now,
                         embedding, now),
                    )

                    # Sync FTS
                    self._sync_fts(conn, node_id, name, data, collection)

                conn.commit()

                # Invalidate cached search index for this collection
                self._invalidate_index(collection)

                return node_id
            except Exception as e:
                conn.rollback()
                logger.warning(f"SQLite write failed: {e}")
                return None

    def query_prefix(
        self,
        prefix: str,
        collection: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query current (non-invalidated) nodes by name prefix."""
        if collection is None:
            collection = "nodes"

        with self._conn() as conn:
            if prefix:
                escaped = prefix.replace("%", "\\%").replace("_", "\\_")
                rows = conn.execute(
                    """SELECT id, name, data, node_type
                       FROM nodes
                       WHERE collection = ? AND name LIKE ? ESCAPE '\\'
                         AND (valid_until IS NULL OR valid_until = 0)
                       ORDER BY updated_at DESC
                       LIMIT ?""",
                    (collection, escaped + "%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, name, data, node_type
                       FROM nodes
                       WHERE collection = ?
                         AND (valid_until IS NULL OR valid_until = 0)
                       ORDER BY updated_at DESC
                       LIMIT ?""",
                    (collection, limit),
                ).fetchall()

            return [
                {
                    "id": row["id"],
                    "payload": {
                        "name": row["name"],
                        "data": row["data"],
                        "type": row["node_type"],
                    },
                }
                for row in rows
            ]

    def get_point(
        self, collection: str, point_id: Union[int, str]
    ) -> Dict[str, Any]:
        """Get a node by ID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, name, data, node_type FROM nodes WHERE id = ? AND collection = ?",
                (point_id, collection),
            ).fetchone()

            if not row:
                from .exceptions import SynrixNotFoundError
                raise SynrixNotFoundError(f"Point {point_id} not found")

            return {
                "result": {
                    "id": row["id"],
                    "vector": [],
                    "payload": {
                        "name": row["name"],
                        "data": row["data"],
                        "type": row["node_type"],
                    },
                }
            }

    def upsert_points(
        self, collection: str, points: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Upsert points (compatibility with vector-style API)."""
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO collections (name, vector_dim, distance, created_at)
                   VALUES (?, 128, 'Cosine', ?)""",
                (collection, time.time()),
            )
            now = time.time()
            for point in points:
                pid = point.get("id", hash(str(now)) % (2**63))
                payload = point.get("payload", {})
                conn.execute(
                    """INSERT OR REPLACE INTO nodes
                       (id, collection, name, data, node_type, created_at, updated_at,
                        valid_from, valid_until, version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)""",
                    (
                        pid,
                        collection,
                        payload.get("name", ""),
                        payload.get("data", ""),
                        payload.get("type", "primitive"),
                        now,
                        now,
                        now,
                    ),
                )
            conn.commit()
            return {"status": "ok"}

    def search_points(
        self,
        collection: str,
        vector: List[float],
        limit: int = 10,
        score_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Search points (returns all in collection, no vector similarity)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, name, data, node_type FROM nodes
                   WHERE collection = ? AND (valid_until IS NULL OR valid_until = 0)
                   LIMIT ?""",
                (collection, limit),
            ).fetchall()
            results = []
            for i, row in enumerate(rows):
                score = 0.95 - (i * 0.05)
                if score_threshold is None or score >= score_threshold:
                    results.append(
                        {
                            "id": row["id"],
                            "score": score,
                            "payload": {
                                "name": row["name"],
                                "data": row["data"],
                                "type": row["node_type"],
                            },
                        }
                    )
            return results

    # ------------------------------------------------------------------
    # Fact embeddings (LLM-extracted facts for better semantic search)
    # ------------------------------------------------------------------

    def add_fact_embeddings(
        self,
        node_id: int,
        node_name: str,
        facts: List[Dict[str, Any]],
        collection: Optional[str] = None,
        _background: bool = False,
    ) -> int:
        """Store extracted fact embeddings for a node.

        Each fact dict has: {"text": str, "embedding": bytes}
        Old facts for the same node_name are replaced.
        Returns number of facts stored.

        Args:
            _background: If True, skip Python-level write lock and rely on
                         SQLite WAL + busy_timeout for concurrency. Use this
                         for background enrichment to avoid blocking foreground writes.
        """
        if collection is None:
            collection = "nodes"

        now = time.time()

        if _background:
            # Background path: rely on SQLite WAL locking, don't block foreground
            with self._conn() as conn:
                conn.execute(
                    "DELETE FROM fact_embeddings WHERE collection = ? AND node_name = ?",
                    (collection, node_name),
                )
                for fact in facts:
                    conn.execute(
                        """INSERT INTO fact_embeddings
                           (collection, node_id, node_name, fact_text, embedding, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (collection, node_id, node_name, fact["text"],
                         fact["embedding"], now),
                    )
                conn.commit()
                return len(facts)

        with self._write_lock, self._conn() as conn:
            # Remove old facts for this node_name (handles version updates)
            conn.execute(
                "DELETE FROM fact_embeddings WHERE collection = ? AND node_name = ?",
                (collection, node_name),
            )

            for fact in facts:
                conn.execute(
                    """INSERT INTO fact_embeddings
                       (collection, node_id, node_name, fact_text, embedding, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (collection, node_id, node_name, fact["text"],
                     fact["embedding"], now),
                )

            conn.commit()
            return len(facts)

    def update_node_embedding(self, node_id: int, embedding, collection: str = "default"):
        """Update a node's embedding without acquiring the foreground write lock.

        Designed for background enrichment — uses SQLite WAL + busy_timeout
        for concurrency instead of the Python-level _write_lock. This prevents
        background embedding updates from blocking foreground memory writes.
        """
        with self._conn() as conn:
            conn.execute(
                "UPDATE nodes SET embedding = ? WHERE id = ?",
                (embedding, node_id),
            )
            conn.commit()
        self._invalidate_index(collection)

    # ------------------------------------------------------------------
    # Index cache management
    # ------------------------------------------------------------------

    def _invalidate_index(self, collection: str):
        """Mark cached indices as dirty after a write."""
        with self._index_lock:
            if collection in self._node_indices:
                self._node_indices[collection].mark_dirty()
            if collection in self._fact_indices:
                self._fact_indices[collection].mark_dirty()

    def _ensure_node_index(self, collection: str, dim: int):
        """Build or rebuild the node embedding index if needed."""
        import numpy as np

        with self._index_lock:
            idx = self._node_indices.get(collection)
            if idx is not None and not idx.is_dirty:
                return idx

            # Build from SQLite
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT id, name, data, node_type, embedding
                       FROM nodes
                       WHERE collection = ? AND embedding IS NOT NULL
                         AND (valid_until IS NULL OR valid_until = 0)""",
                    (collection,),
                ).fetchall()

            ids, names, datas, types, embeddings = [], [], [], [], []
            for row in rows:
                vec = np.frombuffer(row["embedding"], dtype=np.float32)
                if len(vec) == dim:
                    ids.append(row["id"])
                    names.append(row["name"])
                    datas.append(row["data"])
                    types.append(row["node_type"])
                    embeddings.append(vec)

            if HAS_VECTOR_INDEX:
                if idx is None:
                    idx = VectorIndex(dim=dim)
                    self._node_indices[collection] = idx
                idx.build(ids, names, datas, types, embeddings)
            else:
                # Lightweight fallback: store as dict
                idx = {
                    "ids": ids, "names": names, "datas": datas,
                    "types": types, "matrix": np.stack(embeddings) if embeddings else None,
                    "dirty": False,
                }
                self._node_indices[collection] = idx

            return idx

    def _ensure_fact_index(self, collection: str, dim: int):
        """Build or rebuild the fact embedding index if needed."""
        import numpy as np

        with self._index_lock:
            idx = self._fact_indices.get(collection)
            if idx is not None and not idx.is_dirty:
                return idx

            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT fe.node_name, fe.fact_text, fe.embedding,
                              n.id as node_id, n.data, n.node_type
                       FROM fact_embeddings fe
                       JOIN nodes n ON fe.node_id = n.id
                       WHERE fe.collection = ?
                         AND (n.valid_until IS NULL OR n.valid_until = 0)""",
                    (collection,),
                ).fetchall()

            node_ids, node_names, fact_texts = [], [], []
            datas, types, embeddings = [], [], []
            for row in rows:
                vec = np.frombuffer(row["embedding"], dtype=np.float32)
                if len(vec) == dim:
                    node_ids.append(row["node_id"])
                    node_names.append(row["node_name"])
                    fact_texts.append(row["fact_text"])
                    datas.append(row["data"])
                    types.append(row["node_type"])
                    embeddings.append(vec)

            if HAS_VECTOR_INDEX:
                if idx is None:
                    idx = FactIndex(dim=dim)
                    self._fact_indices[collection] = idx
                idx.build(node_ids, node_names, fact_texts, datas, types, embeddings)
            else:
                idx = None  # No fact index without vector_index module
                self._fact_indices[collection] = idx

            return idx

    # ------------------------------------------------------------------
    # Semantic vector search
    # ------------------------------------------------------------------

    def semantic_search(
        self,
        query_embedding: bytes,
        collection: Optional[str] = None,
        limit: int = 10,
        threshold: float = 0.0,
        query_text: str = "",
        name_prefix: str = "",
    ) -> List[Dict[str, Any]]:
        """Hybrid search: vector similarity + keyword matching.

        Three-tier approach:
          1. If fact_embeddings exist -> search those (highest quality)
          2. Fall back to nodes.embedding (raw text embeddings)
          3. Merge with FTS5 keyword results (boosts exact term matches)

        Uses cached in-memory index (FAISS or numpy) for fast vector lookups.
        Index is rebuilt automatically when writes invalidate it.

        Args:
            name_prefix: If set, only return results whose name starts with this prefix.
                         Used for agent-scoped search.
        """
        if collection is None:
            collection = "nodes"

        try:
            import numpy as np
        except ImportError:
            return []

        query_vec = np.frombuffer(query_embedding, dtype=np.float32).copy()
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec /= norm

        dim = len(query_vec)

        # If name_prefix is set, do a direct scoped search instead of using the global index
        if name_prefix:
            # Scoped search: vector-only, no keyword merge (keyword search is unscoped)
            return self._scoped_vector_search(
                query_vec, collection, limit, threshold, dim, name_prefix
            )

        # Global search: search BOTH fact embeddings and node embeddings, merge results
        fact_results = self._search_fact_embeddings(query_vec, collection, limit, threshold, dim)
        node_results = self._search_node_embeddings(query_vec, collection, limit, threshold, dim)

        # Merge: deduplicate by node id, keep highest score
        seen_ids = {}
        for r in fact_results + node_results:
            rid = r.get("id")
            if rid not in seen_ids or r.get("score", 0) > seen_ids[rid].get("score", 0):
                seen_ids[rid] = r
        vector_results = sorted(seen_ids.values(), key=lambda x: x.get("score", 0), reverse=True)[:limit]

        # Keyword search: FTS5 full-text matching
        keyword_results = []
        if query_text and getattr(self, '_has_fts', False):
            keyword_results = self._keyword_search(query_text, collection, limit=limit * 3)

        # If no keyword results, return vector results as-is
        if not keyword_results:
            return vector_results

        # Merge: combine vector and keyword scores
        return self._merge_hybrid_results(
            vector_results, keyword_results, limit, threshold,
            query_vec=query_vec, collection=collection, dim=dim,
        )

    def _scoped_vector_search(
        self, query_vec, collection: str, limit: int, threshold: float,
        dim: int, name_prefix: str,
    ) -> List[Dict[str, Any]]:
        """Search ONLY nodes/facts matching a name prefix (agent-scoped).

        Bypasses the global index and queries SQLite directly for this agent's data,
        then computes similarity in-memory. Fast for per-agent queries (typically <1000 nodes).
        """
        import numpy as np

        results = []

        # Search node embeddings for this agent
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, name, data, node_type, embedding
                   FROM nodes
                   WHERE collection = ? AND embedding IS NOT NULL
                     AND name LIKE ?
                     AND (valid_until IS NULL OR valid_until = 0)""",
                (collection, name_prefix + "%"),
            ).fetchall()

        if rows:
            for row in rows:
                vec = np.frombuffer(row["embedding"], dtype=np.float32)
                if len(vec) != dim:
                    continue
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                score = float(np.dot(vec, query_vec))
                if score >= threshold:
                    results.append({
                        "id": row["id"],
                        "score": score,
                        "payload": {
                            "name": row["name"],
                            "data": row["data"],
                            "type": row["node_type"],
                        },
                    })

        # Also search fact embeddings for this agent
        with self._conn() as conn:
            fact_rows = conn.execute(
                """SELECT fe.node_id, fe.node_name, fe.fact_text, fe.embedding, n.data
                   FROM fact_embeddings fe
                   LEFT JOIN nodes n ON fe.node_id = n.id
                   WHERE fe.collection = ? AND fe.node_name LIKE ?""",
                (collection, name_prefix + "%"),
            ).fetchall()

        if fact_rows:
            for row in fact_rows:
                vec = np.frombuffer(row["embedding"], dtype=np.float32)
                if len(vec) != dim:
                    continue
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                score = float(np.dot(vec, query_vec))
                if score >= threshold:
                    nid = row["node_id"]
                    # Only keep if higher score than existing entry for same node
                    existing = next((r for r in results if r["id"] == nid), None)
                    if existing and existing["score"] >= score:
                        continue
                    if existing:
                        results.remove(existing)
                    results.append({
                        "id": nid,
                        "score": score,
                        "payload": {
                            "name": row["node_name"],
                            "data": row.get("data", "{}"),
                            "type": "memory",
                        },
                        "matched_fact": row["fact_text"],
                    })

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]

    def _search_fact_embeddings(
        self, query_vec, collection: str, limit: int, threshold: float, dim: int,
    ) -> List[Dict[str, Any]]:
        """Search fact_embeddings table using cached index."""
        idx = self._ensure_fact_index(collection, dim)

        if idx is None:
            return []

        if HAS_VECTOR_INDEX and hasattr(idx, 'search'):
            return idx.search(query_vec, limit=limit, threshold=threshold)

        # Fallback: no cached fact index
        return []

    def _search_node_embeddings(
        self, query_vec, collection: str, limit: int, threshold: float, dim: int,
    ) -> List[Dict[str, Any]]:
        """Search nodes.embedding using cached index."""
        import numpy as np

        idx = self._ensure_node_index(collection, dim)

        if idx is None:
            return []

        if HAS_VECTOR_INDEX and hasattr(idx, 'search'):
            return idx.search(query_vec, limit=limit, threshold=threshold)

        # Dict fallback (when vector_index module not available)
        if isinstance(idx, dict) and idx.get("matrix") is not None:
            matrix = idx["matrix"]
            # Normalize
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            normed = matrix / norms
            scores = np.dot(normed, query_vec)

            if len(scores) <= limit * 2:
                ranked = np.argsort(scores)[::-1]
            else:
                k = min(limit * 2, len(scores))
                top_k_idx = np.argpartition(scores, -k)[-k:]
                ranked = top_k_idx[np.argsort(scores[top_k_idx])[::-1]]

            results = []
            for i in ranked[:limit]:
                score = float(scores[i])
                if score < threshold:
                    break
                results.append({
                    "id": idx["ids"][i],
                    "score": score,
                    "payload": {
                        "name": idx["names"][i],
                        "data": idx["datas"][i],
                        "type": idx["types"][i],
                    },
                })
            return results

        return []

    def _merge_hybrid_results(
        self,
        vector_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        limit: int,
        threshold: float,
        query_vec=None,
        collection: Optional[str] = None,
        dim: int = 384,
    ) -> List[Dict[str, Any]]:
        """Merge vector and keyword search results with weighted scoring.

        Strategy:
          - Vector score (0-1): weighted 0.7
          - Keyword BM25 (normalized 0-1): weighted 0.3
          - If a result appears in BOTH, scores are combined (big boost)
          - If only in keyword results, compute its actual vector score
            (don't assume 0 — that would cap keyword-only results at 0.3)
        """
        VECTOR_WEIGHT = 0.7
        KEYWORD_WEIGHT = 0.3

        # Build lookup by node name for vector results
        merged: Dict[str, Dict[str, Any]] = {}

        for r in vector_results:
            name = r.get("payload", {}).get("name", "")
            merged[name] = {
                "id": r["id"],
                "vector_score": r.get("score", 0),
                "keyword_score": 0.0,
                "payload": r["payload"],
                "matched_fact": r.get("matched_fact"),
            }

        # Normalize BM25 scores to 0-1 range
        if keyword_results:
            max_bm25 = max(r.get("bm25_score", 0) for r in keyword_results)
            if max_bm25 <= 0:
                max_bm25 = 1.0

            # Collect keyword-only results that need vector scoring
            keyword_only_ids = []

            for r in keyword_results:
                name = r.get("payload", {}).get("name", "")
                norm_bm25 = r.get("bm25_score", 0) / max_bm25

                if name in merged:
                    # Already in vector results — boost with keyword score
                    merged[name]["keyword_score"] = norm_bm25
                else:
                    # Only in keyword results — we'll compute vector score below
                    merged[name] = {
                        "id": r["id"],
                        "vector_score": 0.0,
                        "keyword_score": norm_bm25,
                        "payload": r["payload"],
                        "matched_fact": None,
                    }
                    keyword_only_ids.append((r["id"], name))

            # Compute actual vector scores for keyword-only results
            # (prevents them being capped at 0.3 max)
            if keyword_only_ids and query_vec is not None:
                self._fill_vector_scores(
                    merged, keyword_only_ids, query_vec, collection, dim
                )

        # Compute final hybrid score
        results = []
        for name, entry in merged.items():
            hybrid_score = (
                VECTOR_WEIGHT * entry["vector_score"]
                + KEYWORD_WEIGHT * entry["keyword_score"]
            )

            if hybrid_score < threshold:
                continue

            result = {
                "id": entry["id"],
                "score": hybrid_score,
                "payload": entry["payload"],
            }
            if entry.get("matched_fact"):
                result["matched_fact"] = entry["matched_fact"]

            results.append(result)

        # Sort by hybrid score, return top-K
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def _fill_vector_scores(
        self,
        merged: Dict[str, Dict[str, Any]],
        keyword_only_ids: List[Tuple[int, str]],
        query_vec,
        collection: Optional[str],
        dim: int,
    ):
        """Compute actual vector scores for keyword-only results.

        When FTS5 finds results that vector search missed (because they
        weren't in the top-K), we need their real vector score so the
        hybrid score is accurate. Without this, keyword-only results are
        capped at 0.3 and can never outrank mediocre vector results.
        """
        try:
            import numpy as np
        except ImportError:
            return

        if collection is None:
            collection = "nodes"

        # Fetch embeddings for each keyword-only result
        node_ids = [nid for nid, _ in keyword_only_ids]
        if not node_ids:
            return

        placeholders = ",".join("?" * len(node_ids))
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    f"SELECT id, embedding FROM nodes WHERE id IN ({placeholders}) "
                    f"AND embedding IS NOT NULL",
                    node_ids,
                ).fetchall()
        except Exception:
            return

        # Compute cosine similarity for each
        for row in rows:
            node_id = row["id"]
            emb_blob = row["embedding"]
            if not emb_blob:
                continue

            emb_vec = np.frombuffer(emb_blob, dtype=np.float32).copy()
            norm = np.linalg.norm(emb_vec)
            if norm > 0:
                emb_vec /= norm

            score = float(np.dot(query_vec, emb_vec))

            # Find the name for this node_id and update its vector_score
            for nid, name in keyword_only_ids:
                if nid == node_id and name in merged:
                    merged[name]["vector_score"] = max(score, 0.0)
                    break

    # ------------------------------------------------------------------
    # Temporal history
    # ------------------------------------------------------------------

    def get_history(
        self,
        name: str,
        collection: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get all versions of a node (including invalidated ones)."""
        if collection is None:
            collection = "nodes"

        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, name, data, node_type, version, valid_from, valid_until,
                          created_at, updated_at
                   FROM nodes
                   WHERE collection = ? AND name = ?
                   ORDER BY version DESC""",
                (collection, name),
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "version": row["version"] or 1,
                    "valid_from": row["valid_from"],
                    "valid_until": row["valid_until"],
                    "created_at": row["created_at"],
                    "payload": {
                        "name": row["name"],
                        "data": row["data"],
                        "type": row["node_type"],
                    },
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # Knowledge graph — entities
    # ------------------------------------------------------------------

    def upsert_entity(
        self,
        name: str,
        entity_type: str,
        collection: Optional[str] = None,
        source_node_id: Optional[int] = None,
        _background: bool = False,
    ) -> int:
        """Insert or update an entity.  Returns the entity ID.

        Args:
            _background: If True, skip Python write lock (for background enrichment).
        """
        if collection is None:
            collection = "nodes"

        now = time.time()

        ctx = self._conn() if _background else _combined_lock(self._write_lock, self._conn())
        with ctx as conn:
            existing = conn.execute(
                "SELECT id, mention_count FROM entities WHERE collection = ? AND name = ? AND entity_type = ?",
                (collection, name, entity_type),
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE entities SET last_seen = ?, mention_count = ?, source_node_id = COALESCE(?, source_node_id) WHERE id = ?",
                    (now, existing["mention_count"] + 1, source_node_id, existing["id"]),
                )
                conn.commit()
                return existing["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO entities (collection, name, entity_type, source_node_id, first_seen, last_seen, mention_count)
                       VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (collection, name, entity_type, source_node_id, now, now),
                )
                conn.commit()
                return cursor.lastrowid

    def add_relationship(
        self,
        source_entity_id: int,
        target_entity_id: int,
        relation: str,
        collection: Optional[str] = None,
        confidence: float = 1.0,
        source_node_id: Optional[int] = None,
        _background: bool = False,
    ) -> int:
        """Add or update a relationship between entities.  Returns relationship ID.

        Args:
            _background: If True, skip Python write lock (for background enrichment).
        """
        if collection is None:
            collection = "nodes"

        now = time.time()

        ctx = self._conn() if _background else _combined_lock(self._write_lock, self._conn())
        with ctx as conn:
            existing = conn.execute(
                """SELECT id FROM relationships
                   WHERE collection = ? AND source_entity_id = ? AND target_entity_id = ? AND relation = ?""",
                (collection, source_entity_id, target_entity_id, relation),
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE relationships SET confidence = ?, source_node_id = ?, valid_from = ? WHERE id = ?",
                    (confidence, source_node_id, now, existing["id"]),
                )
                conn.commit()
                return existing["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO relationships
                       (collection, source_entity_id, target_entity_id, relation, confidence, source_node_id, valid_from)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (collection, source_entity_id, target_entity_id, relation,
                     confidence, source_node_id, now),
                )
                conn.commit()
                return cursor.lastrowid

    def query_entity(
        self,
        name: str,
        collection: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get an entity and all its relationships."""
        if collection is None:
            collection = "nodes"

        with self._conn() as conn:
            entity = conn.execute(
                "SELECT * FROM entities WHERE collection = ? AND name = ? LIMIT 1",
                (collection, name),
            ).fetchone()

            if not entity:
                return None

            eid = entity["id"]

            # Get relationships where this entity is source or target
            rels = conn.execute(
                """SELECT r.relation, r.confidence, r.valid_from, r.valid_until,
                          es.name as source_name, es.entity_type as source_type,
                          et.name as target_name, et.entity_type as target_type
                   FROM relationships r
                   JOIN entities es ON r.source_entity_id = es.id
                   JOIN entities et ON r.target_entity_id = et.id
                   WHERE (r.source_entity_id = ? OR r.target_entity_id = ?)
                     AND r.collection = ?
                     AND (r.valid_until IS NULL OR r.valid_until = 0)""",
                (eid, eid, collection),
            ).fetchall()

            relationships = []
            for r in rels:
                if r["source_name"] == name:
                    relationships.append({
                        "relation": r["relation"],
                        "target": r["target_name"],
                        "target_type": r["target_type"],
                        "confidence": r["confidence"],
                    })
                else:
                    relationships.append({
                        "relation": r["relation"],
                        "target": r["source_name"],
                        "target_type": r["source_type"],
                        "confidence": r["confidence"],
                        "direction": "incoming",
                    })

            return {
                "id": entity["id"],
                "name": entity["name"],
                "entity_type": entity["entity_type"],
                "mention_count": entity["mention_count"],
                "first_seen": entity["first_seen"],
                "last_seen": entity["last_seen"],
                "relationships": relationships,
            }

    def list_entities(
        self,
        collection: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List entities, optionally filtered by type."""
        if collection is None:
            collection = "nodes"

        with self._conn() as conn:
            if entity_type:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE collection = ? AND entity_type = ? ORDER BY last_seen DESC LIMIT ?",
                    (collection, entity_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE collection = ? ORDER BY last_seen DESC LIMIT ?",
                    (collection, limit),
                ).fetchall()

            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "entity_type": row["entity_type"],
                    "mention_count": row["mention_count"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # Delete operations (used by garbage collection)
    # ------------------------------------------------------------------

    def delete_node(self, name: str, collection: Optional[str] = None) -> bool:
        """Delete a node by name. Returns True if a row was deleted."""
        if collection is None:
            collection = "nodes"
        with self._write_lock, self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM nodes WHERE collection = ? AND name = ?",
                (collection, name),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_by_prefix_before(
        self,
        prefix: str,
        cutoff_timestamp: float,
        collection: Optional[str] = None,
        batch_size: int = 500,
    ) -> int:
        """Delete nodes matching prefix updated before cutoff_timestamp.

        Returns the total number of rows deleted.
        """
        if collection is None:
            collection = "nodes"
        escaped = prefix.replace("%", "\\%").replace("_", "\\_")
        total_deleted = 0

        with self._write_lock, self._conn() as conn:
            while True:
                cursor = conn.execute(
                    """DELETE FROM nodes WHERE rowid IN (
                        SELECT rowid FROM nodes
                        WHERE collection = ? AND name LIKE ? ESCAPE '\\'
                          AND updated_at < ?
                        LIMIT ?
                    )""",
                    (collection, escaped + "%", cutoff_timestamp, batch_size),
                )
                conn.commit()
                deleted = cursor.rowcount
                total_deleted += deleted
                if deleted < batch_size:
                    break
            return total_deleted

    def vacuum(self):
        """Run VACUUM to reclaim disk space after large deletes."""
        with self._conn() as conn:
            conn.execute("VACUUM")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def node_count(self, collection: str = None) -> int:
        """Get total node count (current versions only)."""
        with self._conn() as conn:
            if collection:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM nodes WHERE collection = ? AND (valid_until IS NULL OR valid_until = 0)",
                    (collection,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM nodes WHERE (valid_until IS NULL OR valid_until = 0)"
                ).fetchone()
            return row["cnt"]

    def close(self):
        """Close client (connections are per-call, so this is mostly a no-op)."""
        pass

    def __repr__(self):
        return f"SynrixSQLiteClient(db_path='{self.db_path}')"
