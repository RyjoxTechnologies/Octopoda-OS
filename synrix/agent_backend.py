"""
SYNRIX Agent Backend - Unified Storage for AI Agents
=====================================================
Automatically detects and uses the best available backend:
1. Lattice binary (fastest, ACID, if libsynrix available)
2. SQLite (portable, ACID, always available)
3. Direct shared memory (if server running)
4. HTTP client (remote server)
5. Mock (testing only)

Usage:
    from synrix.agent_backend import get_synrix_backend

    # Auto-detect best backend (lattice -> sqlite -> mock)
    backend = get_synrix_backend()

    # Explicitly choose backend
    backend = get_synrix_backend(backend="sqlite")
    backend = get_synrix_backend(backend="lattice")
    backend = get_synrix_backend(backend="mock")

    backend.write("task:fix_bug", {"error": "SyntaxError", "fix": "add colon"})
    memory = backend.read("task:fix_bug")
"""
import logging

logger = logging.getLogger(__name__)


import os
import json
from typing import Optional, Dict, Any, List

try:
    from .direct_client import SynrixDirectClient
    DIRECT_CLIENT_AVAILABLE = True
except ImportError:
    SynrixDirectClient = None
    DIRECT_CLIENT_AVAILABLE = False

from .client import SynrixClient
from .mock import SynrixMockClient


class SynrixAgentBackend:
    """
    Unified backend interface for AI agents to use SYNRIX.

    Supports multiple storage backends:
    - "auto"    : Auto-detect best available (default)
    - "sqlite"  : SQLite persistent storage (ACID, portable)
    - "lattice" : Native C binary (sub-microsecond, ACID)
    - "mock"    : In-memory dict (testing only, no persistence)
    - "direct"  : Shared memory IPC (requires running server)
    - "http"    : HTTP client (remote server)
    """

    def __init__(self,
                 use_direct: bool = True,
                 use_mock: bool = False,
                 server_url: Optional[str] = None,
                 collection: str = "agent_memory",
                 backend: str = "auto",
                 sqlite_path: Optional[str] = None,
                 lattice_path: Optional[str] = None,
                 dsn: Optional[str] = None,
                 tenant_id: Optional[str] = None):
        """
        Initialize SYNRIX backend.

        Args:
            backend: Backend type - "auto", "sqlite", "lattice", "mock", "direct", "http", "postgres"
            collection: Collection name for storing data
            sqlite_path: Path to SQLite database file
            lattice_path: Path to lattice file
            dsn: PostgreSQL connection string (for backend="postgres")
            tenant_id: Tenant ID for PostgreSQL RLS isolation
            use_direct: Try direct shared memory (legacy parameter)
            use_mock: Use mock client (legacy parameter, same as backend="mock")
            server_url: HTTP server URL (legacy parameter)
        """
        self.collection = collection
        self.client = None

        # PostgreSQL backend (multi-tenant cloud API with RLS)
        if backend == "postgres" and dsn:
            from .postgres_client import SynrixPostgresClient
            self.client = SynrixPostgresClient(dsn=dsn, tenant_id=tenant_id or "_default")
            self.collection = tenant_id or collection
            self.backend_type = "postgres"
            return

        self._init_client(backend, use_direct, use_mock, server_url, sqlite_path, lattice_path)

    def _init_client(self, backend: str, use_direct: bool, use_mock: bool,
                     server_url: Optional[str], sqlite_path: Optional[str],
                     lattice_path: Optional[str]):
        """Initialize the best available client based on backend selection."""

        # Legacy parameter support
        if use_mock:
            backend = "mock"

        if backend == "mock":
            self.client = SynrixMockClient()
            self.backend_type = "mock"
            return

        if backend == "sqlite":
            self._init_sqlite(sqlite_path)
            return

        if backend == "lattice":
            self._init_lattice(lattice_path)
            return

        if backend == "auto":
            # Try lattice -> sqlite -> direct -> http -> mock
            if self._try_lattice(lattice_path):
                return
            if self._try_sqlite(sqlite_path):
                return
            if use_direct and self._try_direct():
                return
            if self._try_http(server_url):
                return
            # Final fallback: mock
            self.client = SynrixMockClient()
            self.backend_type = "mock"
            return

        if backend == "direct":
            if self._try_direct():
                return
            raise RuntimeError("Direct client not available")

        if backend == "http":
            if self._try_http(server_url):
                return
            raise RuntimeError("HTTP client connection failed")

        # Unknown backend
        raise ValueError(f"Unknown backend: {backend}. Use: auto, sqlite, lattice, mock, direct, http")

    def _init_sqlite(self, sqlite_path: Optional[str]):
        """Initialize SQLite backend."""
        from .sqlite_client import SynrixSQLiteClient
        self.client = SynrixSQLiteClient(db_path=sqlite_path)
        self.backend_type = "sqlite"
        try:
            self.client.create_collection(self.collection)
        except Exception:
            pass

    def _init_lattice(self, lattice_path: Optional[str]):
        """Initialize lattice backend."""
        from .lattice_client import SynrixLatticeClient
        self.client = SynrixLatticeClient(lattice_path=lattice_path)
        self.backend_type = "lattice"
        try:
            self.client.create_collection(self.collection)
        except Exception:
            pass

    def _try_lattice(self, lattice_path: Optional[str]) -> bool:
        """Try to initialize lattice backend. Returns True on success."""
        try:
            from .raw_backend import _find_synrix_lib
            if _find_synrix_lib():
                self._init_lattice(lattice_path)
                return True
        except Exception:
            pass
        return False

    def _try_sqlite(self, sqlite_path: Optional[str]) -> bool:
        """Try to initialize SQLite backend. Returns True on success."""
        try:
            self._init_sqlite(sqlite_path)
            return True
        except Exception:
            pass
        return False

    def _try_direct(self) -> bool:
        """Try to initialize direct shared memory client."""
        if not DIRECT_CLIENT_AVAILABLE:
            return False
        try:
            self.client = SynrixDirectClient()
            self.backend_type = "direct"
            try:
                self.client.create_collection(self.collection)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _try_http(self, server_url: Optional[str]) -> bool:
        """Try to initialize HTTP client."""
        try:
            if server_url:
                from urllib.parse import urlparse
                parsed = urlparse(server_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 6334
                self.client = SynrixClient(host=host, port=port)
            else:
                self.client = SynrixClient(host="localhost", port=6334)
            self.backend_type = "http"
            try:
                self.client.create_collection(self.collection)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def write(self, key: str, value: Any, metadata: Optional[Dict] = None,
              embedding: Optional[bytes] = None) -> Optional[int]:
        """
        Write data to SYNRIX.

        Args:
            key: Key/name for the data (e.g., "task:fix_bug")
            value: Data to store (will be JSON serialized)
            metadata: Optional metadata dict
            embedding: Optional pre-computed embedding bytes

        Returns:
            Node ID if successful, None otherwise
        """
        data = {
            "value": value,
            "metadata": metadata or {},
            "timestamp": self._get_timestamp()
        }
        data_str = json.dumps(data, default=str)

        try:
            kwargs = dict(
                name=key,
                data=data_str,
                collection=self.collection,
            )
            if embedding is not None:
                kwargs["embedding"] = embedding
            node_id = self.client.add_node(**kwargs)
            return node_id
        except Exception as e:
            logger.warning(f"Failed to write to SYNRIX ({self.backend_type}): {e}")
            return None

    def read(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Read data from SYNRIX by exact key.

        Args:
            key: Key/name to retrieve

        Returns:
            Dict with data, or None if not found
        """
        results = self.query_prefix(key, limit=1)
        if results:
            return results[0]
        return None

    def get_by_id(self, node_id: int) -> Optional[Dict[str, Any]]:
        """
        Get node by ID (O(1) lookup).

        Args:
            node_id: Node ID

        Returns:
            Node data or None
        """
        if hasattr(self.client, 'get_node_by_id'):
            try:
                return self.client.get_node_by_id(node_id)
            except Exception:
                pass
        return None

    def query_prefix(self, prefix: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Query by prefix (O(k) semantic search).

        Args:
            prefix: Prefix to search for (e.g., "task:")
            limit: Maximum results

        Returns:
            List of matching nodes
        """
        try:
            results = self.client.query_prefix(
                prefix=prefix,
                collection=self.collection,
                limit=limit
            )
            # Parse JSON data from results
            parsed = []
            for result in results:
                payload = result.get("payload", {})
                data_str = payload.get("data", "{}")
                try:
                    data = json.loads(data_str)
                    entry = {
                        "key": payload.get("name", ""),
                        "data": data,
                        "id": result.get("id"),
                        "score": result.get("score", 0.0),
                    }
                except json.JSONDecodeError:
                    entry = {
                        "key": payload.get("name", ""),
                        "data": {"value": data_str},
                        "id": result.get("id"),
                        "score": result.get("score", 0.0),
                    }
                # Preserve metadata and temporal fields from backends that provide them
                if "metadata" in result:
                    entry["metadata"] = result["metadata"]
                if "valid_from" in result:
                    entry["valid_from"] = result["valid_from"]
                if "valid_until" in result:
                    entry["valid_until"] = result["valid_until"]
                parsed.append(entry)
            return parsed
        except Exception as e:
            logger.warning(f"Failed to query SYNRIX ({self.backend_type}): {e}")
            return []

    def get_task_memory(self, task_type: str, limit: int = 20) -> Dict[str, Any]:
        """Get all memory for a task type."""
        prefix = f"task:{task_type}:"
        results = self.query_prefix(prefix, limit=limit * 3)

        attempts = []
        failures = []
        successes = []
        failure_patterns = set()

        for result in results:
            data = result.get("data", {})
            value = str(data.get("value", "")).lower()
            entry = {
                "key": result.get("key", ""),
                "data": data,
                "id": result.get("id"),
                "timestamp": data.get("timestamp", 0)
            }
            attempts.append(entry)

            if any(word in value for word in ["fail", "error", "timeout"]):
                failures.append(entry)
                error = data.get("metadata", {}).get("error")
                if error:
                    failure_patterns.add(error)
            elif "success" in value:
                successes.append(entry)

        attempts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        failures.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        successes.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        most_common_failure = None
        if failures:
            error_counts = {}
            for failure in failures:
                error = failure.get("data", {}).get("metadata", {}).get("error")
                if error:
                    error_counts[error] = error_counts.get(error, 0) + 1
            if error_counts:
                most_common_error = max(error_counts, key=error_counts.get)
                most_common_failure = next(
                    (f for f in failures
                     if f.get("data", {}).get("metadata", {}).get("error") == most_common_error),
                    None
                )

        return {
            "last_attempts": attempts[:limit],
            "failures": failures[:limit],
            "successes": successes[:limit],
            "most_common_failure": most_common_failure,
            "failure_patterns": list(failure_patterns)
        }

    def store_fact_embeddings(
        self, node_id: int, node_name: str, facts: List[Dict[str, Any]],
        _background: bool = False,
    ) -> int:
        """Store extracted fact embeddings for a memory node.

        Args:
            node_id: The parent node ID.
            node_name: The parent node's key name.
            facts: List of {"text": str, "embedding": bytes}.
            _background: If True, skip Python write lock (for background enrichment).

        Returns:
            Number of facts stored.
        """
        if not hasattr(self.client, "add_fact_embeddings"):
            return 0
        try:
            return self.client.add_fact_embeddings(
                node_id=node_id,
                node_name=node_name,
                facts=facts,
                collection=self.collection,
                _background=_background,
            )
        except Exception:
            return 0

    def semantic_search(
        self, query_text: str, limit: int = 10, threshold: float = 0.0,
        name_prefix: str = "",
    ) -> List[Dict[str, Any]]:
        """Search memories by semantic similarity (requires sentence-transformers).

        Returns list of {key, data, id, score} sorted by relevance.
        Returns empty list if embedding model is not available.

        Args:
            name_prefix: If set, only search within nodes whose name starts with this.
        """
        try:
            from .embeddings import EmbeddingModel
            model = EmbeddingModel.get()
            if model is None:
                return []
        except ImportError:
            return []

        query_embedding = model.encode(query_text)

        if not hasattr(self.client, "semantic_search"):
            return []

        try:
            results = self.client.semantic_search(
                query_embedding=query_embedding,
                collection=self.collection,
                limit=limit,
                threshold=threshold,
                query_text=query_text,
                name_prefix=name_prefix,
            )
            parsed = []
            for result in results:
                payload = result.get("payload", {})
                data_str = payload.get("data", "{}")
                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, TypeError):
                    data = {"value": data_str}
                entry = {
                    "key": payload.get("name", ""),
                    "data": data,
                    "id": result.get("id"),
                    "score": result.get("score", 0.0),
                }
                if "matched_fact" in result:
                    entry["matched_fact"] = result["matched_fact"]
                parsed.append(entry)
            return parsed
        except Exception as e:
            logger.warning(f"Semantic search failed ({self.backend_type}): {e}")
            return []

    def get_history(self, key: str) -> List[Dict[str, Any]]:
        """Get all versions of a key (temporal history).

        Returns list of {key, data, id, version, valid_from, valid_until}.
        """
        if not hasattr(self.client, "get_history"):
            return []

        try:
            results = self.client.get_history(
                name=key, collection=self.collection
            )
            parsed = []
            for result in results:
                # Support both formats: postgres_client returns data directly,
                # lattice/sqlite may wrap in "payload"
                payload = result.get("payload", result)
                raw_data = payload.get("data", {})
                if isinstance(raw_data, str):
                    try:
                        data = json.loads(raw_data)
                    except (json.JSONDecodeError, TypeError):
                        data = {"value": raw_data}
                elif isinstance(raw_data, dict):
                    data = raw_data
                else:
                    data = {"value": raw_data}
                parsed.append({
                    "key": payload.get("name", payload.get("key", "")),
                    "data": data,
                    "id": result.get("id"),
                    "version": result.get("version", 1),
                    "valid_from": result.get("valid_from"),
                    "valid_until": result.get("valid_until"),
                })
            return parsed
        except Exception as e:
            logger.warning(f"History query failed ({self.backend_type}): {e}")
            return []

    def add_entity(
        self,
        name: str,
        entity_type: str,
        source_node_id: Optional[int] = None,
        _background: bool = False,
    ) -> Optional[int]:
        """Add or update an entity in the knowledge graph. Returns entity ID."""
        if not hasattr(self.client, "upsert_entity"):
            return None
        try:
            return self.client.upsert_entity(
                name=name,
                entity_type=entity_type,
                collection=self.collection,
                source_node_id=source_node_id,
                _background=_background,
            )
        except Exception:
            return None

    def add_relationship(
        self,
        source_entity_id: int,
        target_entity_id: int,
        relation: str,
        confidence: float = 1.0,
        source_node_id: Optional[int] = None,
        _background: bool = False,
    ) -> Optional[int]:
        """Add a relationship between entities. Returns relationship ID."""
        if not hasattr(self.client, "add_relationship"):
            return None
        try:
            return self.client.add_relationship(
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relation=relation,
                collection=self.collection,
                confidence=confidence,
                source_node_id=source_node_id,
                _background=_background,
            )
        except Exception:
            return None

    def query_entity(self, name: str) -> Optional[Dict[str, Any]]:
        """Query the knowledge graph for an entity and its relationships."""
        if not hasattr(self.client, "query_entity"):
            return None
        try:
            return self.client.query_entity(name=name, collection=self.collection)
        except Exception:
            return None

    def list_entities(
        self, entity_type: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List entities in the knowledge graph."""
        if not hasattr(self.client, "list_entities"):
            return []
        try:
            return self.client.list_entities(
                collection=self.collection,
                entity_type=entity_type,
                limit=limit,
            )
        except Exception:
            return []

    def delete(self, key: str) -> bool:
        """Delete a key from storage. Returns True if deleted."""
        if hasattr(self.client, 'delete_node'):
            try:
                return self.client.delete_node(name=key, collection=self.collection)
            except Exception:
                return False
        return False

    def delete_prefix_before(self, prefix: str, cutoff_timestamp: float) -> int:
        """Delete keys matching prefix updated before cutoff. Returns count deleted."""
        if hasattr(self.client, 'delete_by_prefix_before'):
            try:
                return self.client.delete_by_prefix_before(
                    prefix=prefix,
                    cutoff_timestamp=cutoff_timestamp,
                    collection=self.collection,
                )
            except Exception:
                return 0
        return 0

    def vacuum(self):
        """Reclaim disk space after large deletes (SQLite only)."""
        if hasattr(self.client, 'vacuum'):
            try:
                self.client.vacuum()
            except Exception:
                pass

    def close(self):
        """Close the backend connection"""
        if hasattr(self.client, 'close'):
            self.client.close()

    def _get_timestamp(self) -> int:
        """Get current timestamp in microseconds"""
        import time
        return int(time.time() * 1000000)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self):
        return f"SynrixAgentBackend(backend_type='{self.backend_type}')"


def get_synrix_backend(**kwargs) -> SynrixAgentBackend:
    """
    Get a SYNRIX backend instance (factory function).

    Auto-detects the best available backend by default.

    Usage:
        # Auto-detect (lattice -> sqlite -> mock)
        backend = get_synrix_backend()

        # Explicit backend
        backend = get_synrix_backend(backend="sqlite")
        backend = get_synrix_backend(backend="sqlite", sqlite_path="/data/synrix.db")
        backend = get_synrix_backend(backend="mock")  # testing

        backend.write("key", {"data": "value"})
        memory = backend.read("key")
    """
    return SynrixAgentBackend(**kwargs)
