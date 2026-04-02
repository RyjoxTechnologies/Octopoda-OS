#!/usr/bin/env python3
"""
SYNRIX Agent Integration - Deep Workflow Integration
====================================================
This module provides seamless SYNRIX integration for AI agents.
Automatically queries SYNRIX before code generation and stores results.

Usage:
    # Before generating code:
    from synrix.agent_integration import check_synrix_before_generate
    context = check_synrix_before_generate()
    # Use context['constraints'], context['patterns'], context['failures']
    
    # After success:
    from synrix.agent_integration import store_success_pattern
    store_success_pattern("pattern_name", code, context)
    
    # After failure:
    from synrix.agent_integration import store_failure
    store_failure("error_type", error, context, avoid)
"""
import logging

logger = logging.getLogger(__name__)


import os
import sys
import json
import time
from typing import Dict, Any, Optional
from functools import lru_cache

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from synrix.auto_memory import AIMemoryHelper
    SYNRIX_AVAILABLE = True
except ImportError:
    SYNRIX_AVAILABLE = False
    AIMemoryHelper = None


# Global memory instance (reused across calls for performance)
_memory_instance: Optional[AIMemoryHelper] = None


@lru_cache(maxsize=1)
def get_memory_instance() -> Optional[AIMemoryHelper]:
    """Get or create memory instance (cached for performance)"""
    global _memory_instance
    if not SYNRIX_AVAILABLE:
        return None
    if _memory_instance is None:
        _memory_instance = AIMemoryHelper()
    return _memory_instance


def check_synrix_before_generate() -> Dict[str, Any]:
    """
    Check SYNRIX before generating code.
    Returns constraints, patterns, and failures to consider.
    
    This should be called BEFORE every code generation.
    
    Returns:
        Dict with 'constraints', 'patterns', 'failures' keys
        
    Example:
        >>> context = check_synrix_before_generate()
        >>> for c in context['constraints']:
        ...     print(f"Constraint: {c['name']}")
    """
    if not SYNRIX_AVAILABLE:
        return {"constraints": [], "patterns": [], "failures": []}
    
    try:
        memory = get_memory_instance()
        if memory is None:
            return {"constraints": [], "patterns": [], "failures": []}
        
        context = memory.check_before_generate()
        return context
    except Exception as e:
        # Fail gracefully - don't break workflow if SYNRIX fails
        logger.error(f"SYNRIX check failed: {e}", file=sys.stderr)
        return {"constraints": [], "patterns": [], "failures": []}


def store_success_pattern(
    pattern_name: str,
    code: str,
    context: str = "",
    success_rate: float = 1.0,
    metadata: Optional[Dict] = None
) -> bool:
    """
    Store a successful pattern after code generation.
    
    This should be called AFTER successful code generation.
    
    Args:
        pattern_name: Name of the pattern (e.g., "lattice_query")
        code: The code that worked
        context: Context where it was used
        success_rate: Success rate (0.0-1.0)
        metadata: Optional additional metadata
        
    Returns:
        True if stored successfully, False otherwise
        
    Example:
        >>> store_success_pattern("lattice_query", "def query(...): ...", "SYNRIX operations")
    """
    if not SYNRIX_AVAILABLE:
        return False
    
    try:
        memory = get_memory_instance()
        if memory is None:
            return False
        
        memory.store_pattern(pattern_name, code, context, success_rate, metadata)
        return True
    except Exception as e:
        logger.error(f"SYNRIX store pattern failed: {e}", file=sys.stderr)
        return False


def store_failure(
    error_type: str,
    error: str,
    context: str = "",
    avoid: str = ""
) -> bool:
    """
    Store a failure to avoid repeating.
    
    This should be called AFTER an error occurs.
    
    Args:
        error_type: Type of error (e.g., "regex_approach")
        error: Error description
        context: Context where error occurred
        avoid: What to avoid in the future
        
    Returns:
        True if stored successfully, False otherwise
        
    Example:
        >>> store_failure("regex_approach", "User rejected regex", "Code parsing", "Use AST instead")
    """
    if not SYNRIX_AVAILABLE:
        return False
    
    try:
        memory = get_memory_instance()
        if memory is None:
            return False
        
        memory.store_failure(error_type, error, context, avoid)
        return True
    except Exception as e:
        logger.error(f"SYNRIX store failure failed: {e}", file=sys.stderr)
        return False


def store_constraint(rule_name: str, description: str) -> bool:
    """
    Store a project constraint.
    
    This should be called when learning a new project rule.
    
    Args:
        rule_name: Name of constraint (e.g., "no_regex")
        description: Description of the constraint
        
    Returns:
        True if stored successfully, False otherwise
        
    Example:
        >>> store_constraint("no_regex", "User prefers semantic reasoning over regex")
    """
    if not SYNRIX_AVAILABLE:
        return False
    
    try:
        memory = get_memory_instance()
        if memory is None:
            return False
        
        memory.store_constraint(rule_name, description)
        return True
    except Exception as e:
        logger.error(f"SYNRIX store constraint failed: {e}", file=sys.stderr)
        return False


def get_synrix_stats() -> Dict[str, Any]:
    """
    Get statistics about SYNRIX memory.
    
    Returns:
        Dict with counts of constraints, patterns, failures
        
    Example:
        >>> stats = get_synrix_stats()
        >>> print(f"Constraints: {stats['constraints']}")
    """
    if not SYNRIX_AVAILABLE:
        return {"constraints": 0, "patterns": 0, "failures": 0, "available": False}
    
    try:
        memory = get_memory_instance()
        if memory is None:
            return {"constraints": 0, "patterns": 0, "failures": 0, "available": False}
        
        context = memory.check_before_generate()
        return {
            "constraints": len(context.get("constraints", [])),
            "patterns": len(context.get("patterns", [])),
            "failures": len(context.get("failures", [])),
            "available": True
        }
    except Exception as e:
        return {"constraints": 0, "patterns": 0, "failures": 0, "available": False, "error": str(e)}


if __name__ == "__main__":
    # CLI interface for testing
    import sys
    
    if len(sys.argv) < 2:
        logger.info("Usage: agent_integration.py <command> [args...]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "check":
        context = check_synrix_before_generate()
        logger.info(json.dumps(context, indent=2))
    
    elif command == "stats":
        stats = get_synrix_stats()
        logger.info(json.dumps(stats, indent=2))
    
    elif command == "store_pattern":
        if len(sys.argv) < 4:
            logger.info("Usage: store_pattern <name> <code> [context] [success_rate]")
            sys.exit(1)
        result = store_success_pattern(
            sys.argv[2],
            sys.argv[3],
            sys.argv[4] if len(sys.argv) > 4 else "",
            float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
        )
        logger.info(json.dumps({"success": result}))
    
    elif command == "store_failure":
        if len(sys.argv) < 4:
            logger.error("Usage: store_failure <type> <error> [context] [avoid]")
            sys.exit(1)
        result = store_failure(
            sys.argv[2],
            sys.argv[3],
            sys.argv[4] if len(sys.argv) > 4 else "",
            sys.argv[5] if len(sys.argv) > 5 else ""
        )
        logger.info(json.dumps({"success": result}))
    
    elif command == "store_constraint":
        if len(sys.argv) < 4:
            logger.info("Usage: store_constraint <name> <description>")
            sys.exit(1)
        result = store_constraint(sys.argv[2], sys.argv[3])
        logger.info(json.dumps({"success": result}))
    
    else:
        logger.info(f"Unknown command: {command}")
        sys.exit(1)
