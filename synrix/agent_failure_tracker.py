#!/usr/bin/env python3
"""
AI Agent Failure Tracker
========================
Automatically records failures for learning and avoiding repetition.

This module provides automatic failure tracking for AI agents:
- Records failures with context and "avoid" patterns
- Stores as FAILURE: nodes in SYNRIX memory
- Enables querying failures to avoid repeating mistakes

Usage:
    from synrix.agent_failure_tracker import record_failure
    record_failure(
        "wal_corruption",
        "WAL recovery failed with 'Failed to apply operation 2'",
        "During full codebase indexing",
        "Check if node exists before updating in apply_update_node_cb"
    )
"""
import logging

logger = logging.getLogger(__name__)


import os
import json
import sys
from typing import Optional
from datetime import datetime

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
python_sdk_dir = os.path.dirname(script_dir)
if python_sdk_dir not in sys.path:
    sys.path.insert(0, python_sdk_dir)

try:
    from synrix.raw_backend import RawSynrixBackend
except ImportError:
    RawSynrixBackend = None


def record_failure(error_type: str,
                   error_description: str,
                   context: str,
                   avoid_pattern: str,
                   memory_path: Optional[str] = None,
                   additional_data: Optional[dict] = None) -> bool:
    """
    Record a failure in SYNRIX memory.
    
    Args:
        error_type: Type/category of error (e.g., "wal_corruption", "segfault", "test_failure")
        error_description: Detailed description of what went wrong
        context: Context where error occurred (e.g., "During full codebase indexing")
        avoid_pattern: What to avoid doing (e.g., "Don't update nodes without checking existence")
        memory_path: Path to memory lattice file (default: ~/.cursor_ai_memory.lattice)
        additional_data: Optional additional metadata
    
    Returns:
        True if successfully recorded, False otherwise
    """
    if memory_path is None:
        memory_path = os.path.expanduser("~/.cursor_ai_memory.lattice")
    
    if RawSynrixBackend is None:
        logger.warning(f"WARNING: RawSynrixBackend not available, cannot record failure: {error_type}")
        return False
    
    backend = None
    try:
        # Create memory file if it doesn't exist
        if not os.path.exists(memory_path):
            backend = RawSynrixBackend(memory_path, max_nodes=100000, evaluation_mode=False)
        else:
            backend = RawSynrixBackend(memory_path, max_nodes=100000, evaluation_mode=False)
        
        # Build failure data
        failure_data = {
            "error_type": error_type,
            "error": error_description,
            "context": context,
            "avoid": avoid_pattern,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": datetime.now().isoformat()
        }
        
        if additional_data:
            failure_data.update(additional_data)
        
        # Store as FAILURE: node
        node_name = f"FAILURE:{error_type}"
        node_data = json.dumps(failure_data, separators=(',', ':'))
        
        # Use chunked storage if data exceeds 511 bytes
        if len(node_data) > 511:
            data_bytes = node_data.encode('utf-8')
            node_id = backend.add_node_chunked(node_name, data_bytes, node_type=6)  # LATTICE_NODE_ANTI_PATTERN
            success = (node_id != 0)
        else:
            backend.add_node(node_name, node_data, node_type=6)  # LATTICE_NODE_ANTI_PATTERN
            success = True
        
        if success:
            backend.save()  # Persist immediately
        
        return success
    
    except Exception as e:
        logger.error(f"ERROR: Failed to record failure {error_type}: {e}")
        return False
    
    finally:
        if backend:
            backend.close()


def get_failures_by_type(error_type: str, memory_path: Optional[str] = None) -> list:
    """
    Get all failures of a specific type.
    
    Args:
        error_type: Type of error to query
        memory_path: Path to memory lattice file (default: ~/.cursor_ai_memory.lattice)
    
    Returns:
        List of failure nodes matching the type
    """
    if memory_path is None:
        memory_path = os.path.expanduser("~/.cursor_ai_memory.lattice")
    
    if not os.path.exists(memory_path) or RawSynrixBackend is None:
        return []
    
    backend = None
    try:
        backend = RawSynrixBackend(memory_path, max_nodes=100000, evaluation_mode=False)
        failures = backend.find_by_prefix(f"FAILURE:{error_type}", limit=100)
        
        result = []
        for f in failures:
            try:
                data = json.loads(f.get('data', '{}'))
            except (json.JSONDecodeError, ValueError):
                data = {'error': f.get('data', '')}
            result.append({
                'name': f['name'],
                'data': data,
                'node_id': f.get('node_id', 0)
            })
        
        return result
    
    except Exception as e:
        logger.error(f"ERROR: Failed to get failures: {e}")
        return []
    
    finally:
        if backend:
            backend.close()


def get_all_failures(memory_path: Optional[str] = None, limit: int = 50) -> list:
    """
    Get all recorded failures.
    
    Args:
        memory_path: Path to memory lattice file (default: ~/.cursor_ai_memory.lattice)
        limit: Maximum number of failures to return
    
    Returns:
        List of all failure nodes
    """
    if memory_path is None:
        memory_path = os.path.expanduser("~/.cursor_ai_memory.lattice")
    
    if not os.path.exists(memory_path) or RawSynrixBackend is None:
        return []
    
    backend = None
    try:
        backend = RawSynrixBackend(memory_path, max_nodes=100000, evaluation_mode=False)
        failures = backend.find_by_prefix("FAILURE:", limit=limit)
        
        result = []
        for f in failures:
            try:
                data = json.loads(f.get('data', '{}'))
            except (json.JSONDecodeError, ValueError):
                data = {'error': f.get('data', '')}
            result.append({
                'name': f['name'].replace("FAILURE:", ""),
                'data': data,
                'node_id': f.get('node_id', 0)
            })
        
        # Sort by date (most recent first)
        result.sort(key=lambda x: x.get('data', {}).get('date', ''), reverse=True)
        
        return result
    
    except Exception as e:
        logger.error(f"ERROR: Failed to get failures: {e}")
        return []
    
    finally:
        if backend:
            backend.close()


if __name__ == "__main__":
    # Test failure recording
    logger.error("Testing failure tracker...")
    
    # Record a test failure
    success = record_failure(
        "test_failure",
        "Test error description",
        "During testing",
        "Don't do this in production"
    )
    
    logger.error(f"Recorded test failure: {success}")
    
    # Get all failures
    failures = get_all_failures(limit=10)
    logger.error(f"\nFound {len(failures)} failures:")
    for f in failures[:5]:
        logger.error(f"  - {f['name']}: {f.get('data', {}).get('error', 'N/A')[:50]}...")
