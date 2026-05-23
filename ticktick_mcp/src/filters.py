"""
Advanced filtering system for TickTick MCP server.
Provides comprehensive task filtering with date ranges, status, tags, and more.
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from .datetime_utils import parse_ticktick_datetime

logger = logging.getLogger(__name__)

# Type alias for task dictionaries
TaskDict = Dict[str, Any]


@dataclass
class PeriodFilter:
    """
    Handles date range filtering for tasks.
    
    Filters tasks based on whether their date falls within [start_date, end_date].
    """
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tz: Optional[ZoneInfo] = None
    
    @classmethod
    def from_strings(
        cls, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None,
        tz: Optional[str] = None
    ) -> 'PeriodFilter':
        """
        Create a PeriodFilter from date strings.
        
        Args:
            start_date: Start date string (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:mm:ss)
            end_date: End date string (ISO format)
            tz: IANA timezone name
            
        Returns:
            PeriodFilter instance
        """
        timezone = None
        if tz:
            try:
                timezone = ZoneInfo(tz)
            except KeyError:
                logger.warning(f"Unknown timezone: {tz}")
        
        parsed_start = None
        parsed_end = None
        
        if start_date:
            parsed_start = cls._parse_date_string(start_date, timezone)
        
        if end_date:
            parsed_end = cls._parse_date_string(end_date, timezone)
        
        return cls(start_date=parsed_start, end_date=parsed_end, tz=timezone)
    
    @staticmethod
    def _parse_date_string(date_str: str, timezone: Optional[ZoneInfo] = None) -> Optional[datetime]:
        """Parse a date string into a datetime object."""
        if not date_str:
            return None
        
        try:
            # Try parsing as full datetime first
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            
            # Apply timezone if provided and datetime is naive
            if timezone and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone)
            
            return dt
        except ValueError:
            pass
        
        try:
            # Try parsing as date only
            d = date.fromisoformat(date_str)
            dt = datetime.combine(d, datetime.min.time())
            
            if timezone:
                dt = dt.replace(tzinfo=timezone)
            
            return dt
        except ValueError:
            logger.warning(f"Failed to parse date string: {date_str}")
            return None
    
    def contains(self, date_str: Optional[str]) -> bool:
        """
        Check if a date string falls within the filter's period [start_date, end_date].
        
        Args:
            date_str: TickTick format date string to check
            
        Returns:
            True if date is within period (or if no period is set), False otherwise
        """
        # If no filter is set, all dates pass
        if not self.start_date and not self.end_date:
            return True
        
        # If no date provided and filter is set, exclude
        if not date_str:
            return False
        
        # Parse the task date
        task_date = parse_ticktick_datetime(date_str)
        if not task_date:
            return False
        
        # Compare dates (ignoring time for date comparison)
        task_date_only = task_date.date()
        
        if self.start_date:
            start_date_only = self.start_date.date()
            if task_date_only < start_date_only:
                return False
        
        if self.end_date:
            end_date_only = self.end_date.date()
            if task_date_only > end_date_only:
                return False
        
        return True


@dataclass
class PropertyFilter:
    """
    Defines filtering criteria for tasks based on properties.
    
    Supports filtering by status, project, tag, priority, and date ranges.
    """
    status: str = "uncompleted"  # 'uncompleted' or 'completed'
    project_id: Optional[str] = None
    tag_label: Optional[str] = None
    priority: Optional[int] = None  # 0=None, 1=Low, 3=Medium, 5=High
    due_date_filter: Optional[PeriodFilter] = None
    completion_date_filter: Optional[PeriodFilter] = None
    
    def matches(self, task: TaskDict) -> bool:
        """
        Check if a task matches all filter criteria.
        
        Args:
            task: Task dictionary from TickTick API
            
        Returns:
            True if task matches all criteria, False otherwise
        """
        # Check tag filter
        if self.tag_label:
            task_tags = task.get('tags', [])
            if self.tag_label not in task_tags:
                return False
        
        # Check project filter
        if self.project_id:
            if task.get('projectId') != self.project_id:
                return False
        
        # Check priority filter
        if self.priority is not None:
            if task.get('priority') != self.priority:
                return False
        
        # Check status
        task_status = task.get('status', 0)
        task_is_completed = task_status == 2
        filter_wants_completed = self.status == 'completed'
        
        if filter_wants_completed != task_is_completed:
            return False
        
        # Check date filters based on status
        if not task_is_completed and self.due_date_filter:
            task_due_date = task.get('dueDate')
            if not self.due_date_filter.contains(task_due_date):
                return False
        
        if task_is_completed and self.completion_date_filter:
            if not self.completion_date_filter.contains(task.get('completedTime')):
                return False
        
        return True


class TaskFilterer:
    """
    Orchestrates the task filtering process.
    
    Fetches tasks and applies filters based on PropertyFilter criteria.
    """
    
    def __init__(self, ticktick_client):
        """
        Initialize the filterer with a TickTick client.
        
        Args:
            ticktick_client: TickTickClient instance for API calls
        """
        self.client = ticktick_client
    
    async def filter(
        self,
        tasks: List[TaskDict],
        property_filter: PropertyFilter,
        sort_by_priority: bool = False
    ) -> List[TaskDict]:
        """
        Filter a list of tasks using the property filter.
        
        Args:
            tasks: List of task dictionaries to filter
            property_filter: PropertyFilter with filter criteria
            sort_by_priority: Whether to sort results by priority (descending)
            
        Returns:
            List of filtered (and optionally sorted) tasks
        """
        # Apply filter
        filtered_tasks = [t for t in tasks if property_filter.matches(t)]
        
        logger.info(f"Filtered {len(tasks)} tasks down to {len(filtered_tasks)} matching criteria")
        
        # Sort by priority if requested (high priority first)
        if sort_by_priority:
            filtered_tasks.sort(
                key=lambda t: t.get('priority', 0),
                reverse=True
            )
            logger.debug("Sorted tasks by priority (descending)")
        
        return filtered_tasks


def build_property_filter(
    filter_criteria: Dict[str, Any]
) -> tuple[PropertyFilter, bool]:
    """
    Build a PropertyFilter from a dictionary of filter criteria.
    
    Args:
        filter_criteria: Dictionary with filter parameters:
            - status: 'uncompleted' or 'completed'
            - project_id: Optional project ID
            - tag_label: Optional tag name
            - priority: Optional priority (0, 1, 3, 5)
            - start_date: Optional start date (ISO format)
            - end_date: Optional end date (ISO format)
            - timezone: Optional IANA timezone name
            - sort_by_priority: Whether to sort by priority
            
    Returns:
        Tuple of (PropertyFilter, sort_by_priority flag)
    """
    status = filter_criteria.get('status', 'uncompleted')
    project_id = filter_criteria.get('project_id')
    tag_label = filter_criteria.get('tag_label')
    priority = filter_criteria.get('priority')
    start_date = filter_criteria.get('start_date')
    end_date = filter_criteria.get('end_date')
    timezone = filter_criteria.get('timezone')
    sort_by_priority = filter_criteria.get('sort_by_priority', False)
    
    # Build date filters
    due_date_filter = None
    completion_date_filter = None
    
    if status == 'uncompleted' and (start_date or end_date):
        due_date_filter = PeriodFilter.from_strings(start_date, end_date, timezone)
    elif status == 'completed' and (start_date or end_date):
        completion_date_filter = PeriodFilter.from_strings(start_date, end_date, timezone)
    
    property_filter = PropertyFilter(
        status=status,
        project_id=project_id,
        tag_label=tag_label,
        priority=priority,
        due_date_filter=due_date_filter,
        completion_date_filter=completion_date_filter
    )
    
    return property_filter, sort_by_priority
