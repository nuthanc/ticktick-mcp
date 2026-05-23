"""
Task cache module for TickTick MCP server.
Provides file-based caching of task metadata to reduce API calls and enable quick lookups.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TaskCache:
    """
    File-based cache for TickTick task metadata.
    
    Stores task information in a JSON file with a 24-hour TTL.
    """
    
    CACHE_FILE = os.path.expanduser("~/.ticktick-mcp-cache.json")
    CACHE_TTL = 24 * 60 * 60  # 24 hours in seconds
    
    def __init__(self):
        """Initialize the cache, creating the file if it doesn't exist."""
        self.initialize_cache()
    
    def initialize_cache(self) -> None:
        """Initialize the cache file if it doesn't exist."""
        try:
            if not os.path.exists(self.CACHE_FILE):
                self.save_cache({"tasks": {}})
                logger.info(f"Cache file created at {self.CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Failed to initialize cache: {e}")
            # Continue without cache if there's an issue
    
    def load_cache(self) -> Dict[str, Any]:
        """
        Load the cache from disk.
        
        Returns:
            Cache data dictionary with 'tasks' key
        """
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data
        except json.JSONDecodeError as e:
            logger.warning(f"Cache file corrupted, resetting: {e}")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
        
        return {"tasks": {}}
    
    def save_cache(self, data: Dict[str, Any]) -> None:
        """
        Save the cache to disk.
        
        Args:
            data: Cache data dictionary to save
        """
        try:
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def is_task_stale(self, task: Dict[str, Any]) -> bool:
        """
        Check if a cached task is stale (older than TTL).
        
        Args:
            task: Cached task dictionary with 'cached_at' field
            
        Returns:
            True if task is stale, False otherwise
        """
        if not task.get('cached_at'):
            return True
        
        try:
            cached_at = datetime.fromisoformat(task['cached_at'])
            age_seconds = (datetime.now() - cached_at).total_seconds()
            return age_seconds > self.CACHE_TTL
        except (ValueError, TypeError):
            return True
    
    def add_task(self, task_id: str, project_id: str, title: str) -> None:
        """
        Add or update a task in the cache.
        
        Args:
            task_id: TickTick task ID
            project_id: TickTick project ID
            title: Task title
        """
        try:
            cache = self.load_cache()
            cache['tasks'][task_id] = {
                'project_id': project_id,
                'title': title,
                'cached_at': datetime.now().isoformat()
            }
            self.save_cache(cache)
            logger.debug(f"Task {task_id} added to cache")
        except Exception as e:
            logger.warning(f"Failed to add task to cache: {e}")
    
    def remove_task(self, task_id: str) -> bool:
        """
        Remove a task from the cache.
        
        Args:
            task_id: TickTick task ID to remove
            
        Returns:
            True if task was removed, False if not found
        """
        try:
            cache = self.load_cache()
            if task_id in cache['tasks']:
                del cache['tasks'][task_id]
                self.save_cache(cache)
                logger.debug(f"Task {task_id} removed from cache")
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to remove task from cache: {e}")
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific task from the cache.
        
        Args:
            task_id: TickTick task ID
            
        Returns:
            Task data dictionary or None if not found
        """
        try:
            cache = self.load_cache()
            task = cache['tasks'].get(task_id)
            if task:
                return {
                    'task_id': task_id,
                    **task
                }
            return None
        except Exception as e:
            logger.warning(f"Failed to get task from cache: {e}")
            return None
    
    def get_tasks(self, project_id: Optional[str] = None, include_stale: bool = False) -> List[Dict[str, Any]]:
        """
        Get all cached tasks, optionally filtered by project.
        
        Args:
            project_id: Optional project ID to filter by
            include_stale: Whether to include stale tasks (default: False)
            
        Returns:
            List of task data dictionaries
        """
        try:
            cache = self.load_cache()
            tasks = []
            
            for task_id, task_data in cache['tasks'].items():
                # Filter by project if specified
                if project_id and task_data.get('project_id') != project_id:
                    continue
                
                # Filter out stale tasks unless requested
                if not include_stale and self.is_task_stale(task_data):
                    continue
                
                tasks.append({
                    'task_id': task_id,
                    **task_data
                })
            
            return tasks
        except Exception as e:
            logger.warning(f"Failed to get tasks from cache: {e}")
            return []
    
    def clear_cache(self) -> None:
        """Clear all tasks from the cache."""
        try:
            self.save_cache({"tasks": {}})
            logger.info("Cache cleared")
        except Exception as e:
            logger.warning(f"Failed to clear cache: {e}")
    
    def clear_stale_tasks(self) -> int:
        """
        Remove all stale tasks from the cache.
        
        Returns:
            Number of tasks removed
        """
        try:
            cache = self.load_cache()
            original_count = len(cache['tasks'])
            
            cache['tasks'] = {
                task_id: task_data
                for task_id, task_data in cache['tasks'].items()
                if not self.is_task_stale(task_data)
            }
            
            self.save_cache(cache)
            removed = original_count - len(cache['tasks'])
            logger.info(f"Removed {removed} stale tasks from cache")
            return removed
        except Exception as e:
            logger.warning(f"Failed to clear stale tasks: {e}")
            return 0


# Global cache instance
task_cache = TaskCache()
