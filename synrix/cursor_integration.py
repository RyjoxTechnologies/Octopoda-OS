"""
Cursor AI IDE Integration for SYNRIX
=====================================
Use this module directly in Cursor AI to access SYNRIX memory.

Example usage in Cursor:
    from synrix.cursor_integration import synrix
    
    # Store what you learned
    synrix.remember("fix_syntax_error", "Add colon after if statements")
    
    # Recall what you learned
    fix = synrix.recall("fix_syntax_error")
    
    # Query related memories
    all_fixes = synrix.search("fix_")
"""
import logging

logger = logging.getLogger(__name__)


import os
import sys
from typing import Optional, Dict, Any, List
from .agent_backend import get_synrix_backend

# Global backend instance (lazy initialization)
_backend_instance = None


def _get_backend():
    """Get or create the global backend instance"""
    global _backend_instance
    if _backend_instance is None:
        _backend_instance = get_synrix_backend(collection="cursor_ai_memory")
    return _backend_instance


class SynrixMemory:
    """
    Simple memory interface for Cursor AI.
    
    Usage:
        from synrix.cursor_integration import synrix
        
        synrix.remember("key", "value")
        value = synrix.recall("key")
        results = synrix.search("prefix")
    """
    
    def remember(self, key: str, value: Any, metadata: Optional[Dict] = None) -> bool:
        """
        Remember something.
        
        Args:
            key: Memory key (e.g., "fix_syntax_error")
            value: Value to remember (any JSON-serializable object)
            metadata: Optional metadata (e.g., {"file": "main.py", "line": 42})
        
        Returns:
            True if successful
        """
        try:
            backend = _get_backend()
            node_id = backend.write(key, value, metadata)
            return node_id is not None
        except Exception as e:
            logger.warning(f"Failed to remember '{key}': {e}", file=sys.stderr)
            return False
    
    def recall(self, key: str) -> Optional[Any]:
        """
        Recall something from memory.
        
        Args:
            key: Memory key to recall
        
        Returns:
            Stored value, or None if not found
        """
        try:
            backend = _get_backend()
            result = backend.read(key)
            if result:
                data = result.get('data', {})
                value = data.get('value') if isinstance(data, dict) else data
                return value
            return None
        except Exception as e:
            logger.warning(f"Failed to recall '{key}': {e}", file=sys.stderr)
            return None
    
    def search(self, prefix: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search memories by prefix.
        
        Args:
            prefix: Prefix to search for (e.g., "fix_")
            limit: Maximum results
        
        Returns:
            List of matching memories
        """
        try:
            backend = _get_backend()
            results = backend.query_prefix(prefix, limit=limit)
            return results
        except Exception as e:
            logger.warning(f"Failed to search '{prefix}': {e}", file=sys.stderr)
            return []
    
    def get_task_memory(self, task_type: str, limit: int = 20) -> Dict[str, Any]:
        """
        Get all memory for a specific task type.
        
        Args:
            task_type: Task type (e.g., "fix_bug")
            limit: Maximum results
        
        Returns:
            Dict with last_attempts, failures, successes, most_common_failure
        """
        try:
            backend = _get_backend()
            return backend.get_task_memory(task_type, limit=limit)
        except Exception as e:
            logger.warning(f"Failed to get task memory for '{task_type}': {e}", file=sys.stderr)
            return {
                "last_attempts": [],
                "failures": [],
                "successes": [],
                "most_common_failure": None,
                "failure_patterns": []
            }
    
    def forget(self, key: str) -> bool:
        """
        Forget a specific memory (by key).
        
        Note: This is a soft delete - the node remains but is marked.
        For true deletion, you'd need to use the raw backend.
        
        Args:
            key: Memory key to forget
        
        Returns:
            True if successful
        """
        # For now, we'll just overwrite with None
        # True deletion would require direct lattice access
        return self.remember(key, None, {"deleted": True})
    
    def status(self) -> Dict[str, Any]:
        """
        Get backend status.
        
        Returns:
            Dict with backend type and status
        """
        try:
            backend = _get_backend()
            return {
                "backend_type": backend.backend_type,
                "collection": backend.collection,
                "status": "connected"
            }
        except Exception as e:
            return {
                "backend_type": "unknown",
                "status": "error",
                "error": str(e)
            }
    
    def close(self):
        """Close the backend connection"""
        global _backend_instance
        if _backend_instance:
            _backend_instance.close()
            _backend_instance = None


# Global instance for easy access
synrix = SynrixMemory()

