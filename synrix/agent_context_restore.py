#!/usr/bin/env python3
"""
AI Agent Context Restoration
============================
Automatically restores agent context from SYNRIX memory at session start.

This module provides automatic context restoration for AI agents, loading:
- Project constraints (CONSTRAINT: nodes)
- Recent patterns (PATTERN: nodes)
- Recent failures (FAILURE: nodes)
- Recent tasks (TASK: nodes)

Usage:
    from synrix.agent_context_restore import restore_agent_context
    context = restore_agent_context()
    # context = {
    #     'constraints': [...],
    #     'patterns': [...],
    #     'failures': [...],
    #     'recent_tasks': [...]
    # }
"""
import logging

logger = logging.getLogger(__name__)


import os
import json
import sys
from typing import Dict, List, Optional
from datetime import datetime, timedelta

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
python_sdk_dir = os.path.dirname(script_dir)
if python_sdk_dir not in sys.path:
    sys.path.insert(0, python_sdk_dir)

try:
    from synrix.raw_backend import RawSynrixBackend
except ImportError:
    RawSynrixBackend = None


def restore_agent_context(memory_path: Optional[str] = None, 
                          max_patterns: int = 50,
                          max_failures: int = 20,
                          max_tasks: int = 20) -> Dict:
    """
    Restore agent context from SYNRIX memory.
    
    Args:
        memory_path: Path to memory lattice file (default: ~/.cursor_ai_memory.lattice)
        max_patterns: Maximum number of recent patterns to load
        max_failures: Maximum number of recent failures to load
        max_tasks: Maximum number of recent tasks to load
    
    Returns:
        Dictionary with:
        - constraints: List of constraint nodes
        - patterns: List of pattern nodes (sorted by recency/success rate)
        - failures: List of failure nodes
        - recent_tasks: List of recent task nodes
        - stats: Statistics about loaded context
    """
    if memory_path is None:
        memory_path = os.path.expanduser("~/.cursor_ai_memory.lattice")
    
    if not os.path.exists(memory_path):
        return {
            'constraints': [],
            'patterns': [],
            'failures': [],
            'recent_tasks': [],
            'stats': {
                'memory_file_exists': False,
                'total_loaded': 0
            }
        }
    
    if RawSynrixBackend is None:
        return {
            'constraints': [],
            'patterns': [],
            'failures': [],
            'recent_tasks': [],
            'stats': {
                'error': 'RawSynrixBackend not available',
                'total_loaded': 0
            }
        }
    
    backend = None
    try:
        backend = RawSynrixBackend(memory_path, max_nodes=100000, evaluation_mode=False)
        
        # Load constraints (all of them)
        constraints = backend.find_by_prefix("CONSTRAINT:", limit=200, raw=True)  # AI-first: use bytes
        constraints_list = []
        for c in constraints:
            # Decode only when needed (lazy decoding for AI performance)
            name_bytes = c.get('name', b'')
            data_bytes = c.get('data', b'{}')
            
            # Decode name (needed for string operations)
            name_str = name_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(name_bytes, bytes) else name_bytes
            
            # Decode data only when parsing JSON (lazy)
            try:
                data_str = data_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(data_bytes, bytes) else data_bytes
                data = json.loads(data_str)
            except (json.JSONDecodeError, ValueError):
                data = {'description': data_str if isinstance(data_bytes, bytes) else data_bytes}
            
            constraints_list.append({
                'name': name_str.replace("CONSTRAINT:", ""),
                'data': data,
                'node_id': c.get('node_id', 0)
            })
        
        # Load patterns (sorted by recency, prioritize high success rate)
        patterns = backend.find_by_prefix("PATTERN:", limit=max_patterns * 2, raw=True)  # AI-first: use bytes
        patterns_list = []
        for p in patterns:
            # Decode only when needed (lazy decoding for AI performance)
            name_bytes = p.get('name', b'')
            data_bytes = p.get('data', b'{}')
            
            name_str = name_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(name_bytes, bytes) else name_bytes
            
            try:
                data_str = data_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(data_bytes, bytes) else data_bytes
                data = json.loads(data_str)
                success_rate = data.get('success_rate', 0.5)
            except (json.JSONDecodeError, ValueError):
                data = {'description': data_str if isinstance(data_bytes, bytes) else data_bytes}
                success_rate = 0.5
            
            patterns_list.append({
                'name': name_str.replace("PATTERN:", ""),
                'data': data,
                'success_rate': success_rate,
                'node_id': p.get('node_id', 0)
            })
        
        # Sort patterns by success rate (descending), then by recency
        patterns_list.sort(key=lambda x: (x['success_rate'], x.get('data', {}).get('date', '')), reverse=True)
        patterns_list = patterns_list[:max_patterns]
        
        # Load failures (all of them, sorted by recency)
        failures = backend.find_by_prefix("FAILURE:", limit=max_failures * 2, raw=True)  # AI-first: use bytes
        failures_list = []
        for f in failures:
            # Decode only when needed (lazy decoding for AI performance)
            name_bytes = f.get('name', b'')
            data_bytes = f.get('data', b'{}')
            
            name_str = name_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(name_bytes, bytes) else name_bytes
            
            try:
                data_str = data_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(data_bytes, bytes) else data_bytes
                data = json.loads(data_str)
            except (json.JSONDecodeError, ValueError):
                data = {'error': data_str if isinstance(data_bytes, bytes) else data_bytes}
            
            failures_list.append({
                'name': name_str.replace("FAILURE:", ""),
                'data': data,
                'node_id': f.get('node_id', 0)
            })
        
        # Sort failures by date (most recent first)
        failures_list.sort(key=lambda x: x.get('data', {}).get('date', ''), reverse=True)
        failures_list = failures_list[:max_failures]
        
        # Load recent tasks
        tasks = backend.find_by_prefix("TASK:", limit=max_tasks * 2, raw=True)  # AI-first: use bytes
        tasks_list = []
        for t in tasks:
            # Decode only when needed (lazy decoding for AI performance)
            name_bytes = t.get('name', b'')
            data_bytes = t.get('data', b'{}')
            
            name_str = name_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(name_bytes, bytes) else name_bytes
            
            try:
                data_str = data_bytes.decode('utf-8', errors='ignore').rstrip('\x00') if isinstance(data_bytes, bytes) else data_bytes
                data = json.loads(data_str)
            except (json.JSONDecodeError, ValueError):
                data = {'description': data_str if isinstance(data_bytes, bytes) else data_bytes}
            
            tasks_list.append({
                'name': name_str.replace("TASK:", ""),
                'data': data,
                'node_id': t.get('node_id', 0)
            })
        
        # Sort tasks by date (most recent first)
        tasks_list.sort(key=lambda x: x.get('data', {}).get('date', ''), reverse=True)
        tasks_list = tasks_list[:max_tasks]
        
        total_loaded = len(constraints_list) + len(patterns_list) + len(failures_list) + len(tasks_list)
        
        return {
            'constraints': constraints_list,
            'patterns': patterns_list,
            'failures': failures_list,
            'recent_tasks': tasks_list,
            'stats': {
                'memory_file_exists': True,
                'constraints_count': len(constraints_list),
                'patterns_count': len(patterns_list),
                'failures_count': len(failures_list),
                'tasks_count': len(tasks_list),
                'total_loaded': total_loaded
            }
        }
    
    except Exception as e:
        return {
            'constraints': [],
            'patterns': [],
            'failures': [],
            'recent_tasks': [],
            'stats': {
                'error': str(e),
                'total_loaded': 0
            }
        }
    
    finally:
        if backend:
            backend.close()


def find_by_tag(tag: str, memory_path: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """
    Find nodes by tag using TAG_INDEX queries.
    
    Args:
        tag: Tag to search for (e.g., "wal", "memory", "lattice")
        memory_path: Path to memory lattice file (default: ~/.cursor_ai_memory.lattice)
        limit: Maximum number of results
    
    Returns:
        List of nodes matching the tag
    """
    if memory_path is None:
        memory_path = os.path.expanduser("~/.cursor_ai_memory.lattice")
    
    if not os.path.exists(memory_path) or RawSynrixBackend is None:
        return []
    
    backend = None
    try:
        backend = RawSynrixBackend(memory_path, max_nodes=100000, evaluation_mode=False)
        
        # Query TAG_INDEX nodes
        normalized_tag = tag.lower().strip().replace(' ', '_')
        tag_nodes = backend.find_by_prefix(f"TAG_INDEX:{normalized_tag}", limit=limit * 2, raw=True)  # AI-first: use bytes
        
        result = []
        seen_nodes = set()
        
        for tag_node in tag_nodes:
            try:
                data = json.loads(tag_node.get('data', '{}'))
                node_name = data.get('node_name', '')
                node_type = data.get('node_type', '')
                
                if node_name and node_name not in seen_nodes:
                    # Get the actual node
                    node_data = backend.get_node_by_name(node_name)
                    if node_data:
                        try:
                            node_content = json.loads(node_data.get('data', '{}'))
                        except (json.JSONDecodeError, ValueError):
                            node_content = {'description': node_data.get('data', '')}
                        
                        result.append({
                            'name': node_name,
                            'type': node_type,
                            'data': node_content,
                            'tag': normalized_tag,
                            'node_id': node_data.get('node_id', 0)
                        })
                        seen_nodes.add(node_name)
            except Exception:
                continue
        
        return result[:limit]
    
    except Exception as e:
        logger.error(f"ERROR: Failed to find by tag: {e}")
        return []
    
    finally:
        if backend:
            backend.close()


def format_context_summary(context: Dict) -> str:
    """
    Format context summary as a readable string.
    
    Args:
        context: Context dictionary from restore_agent_context()
    
    Returns:
        Formatted string summary
    """
    stats = context.get('stats', {})
    
    if not stats.get('memory_file_exists', False):
        return "No memory file found. Starting with empty context."
    
    if 'error' in stats:
        return f"Error loading context: {stats['error']}"
    
    lines = [
        "=== Agent Context Restored ===",
        f"Constraints: {stats.get('constraints_count', 0)}",
        f"Patterns: {stats.get('patterns_count', 0)}",
        f"Failures: {stats.get('failures_count', 0)}",
        f"Recent Tasks: {stats.get('tasks_count', 0)}",
        f"Total: {stats.get('total_loaded', 0)} items loaded"
    ]
    
    # Show top 3 constraints
    constraints = context.get('constraints', [])
    if constraints:
        lines.append("\nTop Constraints:")
        for c in constraints[:3]:
            name = c.get('name', 'unknown')
            lines.append(f"  - {name}")
    
    # Show top 3 patterns
    patterns = context.get('patterns', [])
    if patterns:
        lines.append("\nTop Patterns (by success rate):")
        for p in patterns[:3]:
            name = p.get('name', 'unknown')
            success = p.get('success_rate', 0.0)
            lines.append(f"  - {name} ({success*100:.0f}% success)")
    
    # Show recent failures
    failures = context.get('failures', [])
    if failures:
        lines.append("\nRecent Failures to Avoid:")
        for f in failures[:3]:
            name = f.get('name', 'unknown')
            avoid = f.get('data', {}).get('avoid', 'N/A')[:50]
            lines.append(f"  - {name}: {avoid}...")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Test context restoration
    context = restore_agent_context()
    logger.info(format_context_summary(context))
    
    # Print detailed stats
    logger.info("\n=== Detailed Stats ===")
    logger.info(json.dumps(context['stats'], indent=2))
