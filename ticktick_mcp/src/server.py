import asyncio
import json
import os
import logging
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Dict, List, Any, Optional

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from .ticktick_client import TickTickClient
from .cache import task_cache
from .datetime_utils import (
    datetime_to_ticktick_format,
    ticktick_to_human_readable,
    parse_ticktick_datetime
)
from .filters import PropertyFilter, PeriodFilter, TaskFilterer, build_property_filter

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastMCP server
mcp = FastMCP("ticktick")

# Create TickTick client
ticktick = None

# Constants
INBOX_PROJECT_ID = "inbox115795465"


def _get_all_projects_including_inbox() -> List[Dict]:
    """
    Get all projects including the Inbox project.
    TickTick API doesn't return Inbox in /project endpoint, so we add it manually.
    
    Returns:
        List of project dictionaries with Inbox prepended
    """
    projects = ticktick.get_projects()
    if 'error' in projects:
        return projects
    
    # Create a virtual Inbox project entry
    inbox_project = {
        'id': INBOX_PROJECT_ID,
        'name': 'Inbox',
        'color': None,
        'closed': False,
        'kind': 'TASK'
    }
    
    # Prepend Inbox to the projects list
    return [inbox_project] + projects

def initialize_client():
    global ticktick
    try:
        # Check if .env file exists with access token
        load_dotenv()
        
        # Check if we have valid credentials
        if os.getenv("TICKTICK_ACCESS_TOKEN") is None:
            logger.error("No access token found in .env file. Please run 'uv run -m ticktick_mcp.cli auth' to authenticate.")
            return False
        
        # Initialize the client
        ticktick = TickTickClient()
        logger.info("TickTick client initialized successfully")
        
        # Test API connectivity (use direct API call, not the Inbox helper)
        projects = ticktick.get_projects()
        if 'error' in projects:
            logger.error(f"Failed to access TickTick API: {projects['error']}")
            logger.error("Your access token may have expired. Please run 'uv run -m ticktick_mcp.cli auth' to refresh it.")
            return False
            
        logger.info(f"Successfully connected to TickTick API with {len(projects)} projects")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize TickTick client: {e}")
        return False

# Format a task object from TickTick for better display
def format_task(task: Dict) -> str:
    """Format a task into a human-readable string."""
    formatted = f"ID: {task.get('id', 'No ID')}\n"
    formatted += f"Title: {task.get('title', 'No title')}\n"
    
    # Add project ID
    formatted += f"Project ID: {task.get('projectId', 'None')}\n"
    
    # Get the task's timezone (TickTick stores dates in UTC but includes timezone info)
    task_timezone = task.get('timeZone')
    
    # Add dates if available (using human-readable format)
    if task.get('startDate'):
        start_readable = ticktick_to_human_readable(task.get('startDate'), tz=task_timezone, format_type="datetime")
        formatted += f"Start Date: {start_readable}\n"
    if task.get('dueDate'):
        due_readable = ticktick_to_human_readable(task.get('dueDate'), tz=task_timezone, format_type="datetime")
        due_relative = ticktick_to_human_readable(task.get('dueDate'), tz=task_timezone, format_type="relative")
        formatted += f"Due Date: {due_readable} ({due_relative})\n"
    
    # Add priority if available
    priority_map = {0: "None", 1: "Low", 3: "Medium", 5: "High"}
    priority = task.get('priority', 0)
    formatted += f"Priority: {priority_map.get(priority, str(priority))}\n"
    
    # Add status if available
    status = "Completed" if task.get('status') == 2 else "Active"
    formatted += f"Status: {status}\n"
    
    # Add completion time if completed
    if task.get('status') == 2 and task.get('completedTime'):
        completed_readable = ticktick_to_human_readable(task.get('completedTime'), tz=task_timezone, format_type="datetime")
        formatted += f"Completed: {completed_readable}\n"
    
    # Add content if available
    if task.get('content'):
        formatted += f"\nContent:\n{task.get('content')}\n"
    
    # Add subtasks if available
    items = task.get('items', [])
    if items:
        formatted += f"\nSubtasks ({len(items)}):\n"
        for i, item in enumerate(items, 1):
            status = "✓" if item.get('status') == 1 else "□"
            formatted += f"{i}. [{status}] {item.get('title', 'No title')}\n"
    
    return formatted

# Format a project object from TickTick for better display
def format_project(project: Dict) -> str:
    """Format a project into a human-readable string."""
    formatted = f"Name: {project.get('name', 'No name')}\n"
    formatted += f"ID: {project.get('id', 'No ID')}\n"
    
    # Add color if available
    if project.get('color'):
        formatted += f"Color: {project.get('color')}\n"
    
    # Add view mode if available
    if project.get('viewMode'):
        formatted += f"View Mode: {project.get('viewMode')}\n"
    
    # Add closed status if available
    if 'closed' in project:
        formatted += f"Closed: {'Yes' if project.get('closed') else 'No'}\n"
    
    # Add kind if available
    if project.get('kind'):
        formatted += f"Kind: {project.get('kind')}\n"
    
    return formatted

# MCP Tools

@mcp.tool()
async def get_projects() -> str:
    """Get all projects from TickTick, including Inbox."""
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        # Use helper that includes Inbox project
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        if not projects:
            return "No projects found."
        
        result = f"Found {len(projects)} projects:\n\n"
        for i, project in enumerate(projects, 1):
            result += f"Project {i}:\n" + format_project(project) + "\n"
        
        return result
    except Exception as e:
        logger.error(f"Error in get_projects: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def get_project(project_id: str) -> str:
    """
    Get details about a specific project.
    
    Args:
        project_id: ID of the project (or 'Inbox' for the Inbox project)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        resolved_project_id = _resolve_project_id(project_id)
        project = ticktick.get_project(resolved_project_id)
        if 'error' in project:
            return f"Error fetching project: {project['error']}"
        
        return format_project(project)
    except Exception as e:
        logger.error(f"Error in get_project: {e}")
        return f"Error retrieving project: {str(e)}"

@mcp.tool()
async def get_project_tasks(project_id: str) -> str:
    """
    Get all tasks in a specific project.
    
    Args:
        project_id: ID of the project (or 'Inbox' for the Inbox project)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        resolved_project_id = _resolve_project_id(project_id)
        project_data = ticktick.get_project_with_data(resolved_project_id)
        if 'error' in project_data:
            return f"Error fetching project data: {project_data['error']}"
        
        tasks = project_data.get('tasks', [])
        if not tasks:
            return f"No tasks found in project '{project_data.get('project', {}).get('name', project_id)}'."
        
        result = f"Found {len(tasks)} tasks in project '{project_data.get('project', {}).get('name', project_id)}':\n\n"
        for i, task in enumerate(tasks, 1):
            result += f"Task {i}:\n" + format_task(task) + "\n"
        
        return result
    except Exception as e:
        logger.error(f"Error in get_project_tasks: {e}")
        return f"Error retrieving project tasks: {str(e)}"

@mcp.tool()
async def get_task(project_id: str, task_id: str) -> str:
    """
    Get details about a specific task.
    
    Args:
        project_id: ID of the project (or 'Inbox' for the Inbox project)
        task_id: ID of the task
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        resolved_project_id = _resolve_project_id(project_id)
        task = ticktick.get_task(resolved_project_id, task_id)
        if 'error' in task:
            return f"Error fetching task: {task['error']}"
        
        return format_task(task)
    except Exception as e:
        logger.error(f"Error in get_task: {e}")
        return f"Error retrieving task: {str(e)}"

@mcp.tool()
async def create_task(
    title: str, 
    project_id: str, 
    content: str = None, 
    start_date: str = None, 
    due_date: str = None, 
    priority: int = 0
) -> str:
    """
    Create a new task in TickTick.
    
    Args:
        title: Task title
        project_id: ID of the project to add the task to (or 'Inbox' for the Inbox project)
        content: Task description/content (optional)
        start_date: Start date in ISO format YYYY-MM-DDThh:mm:ss+0000 (optional)
        due_date: Due date in ISO format YYYY-MM-DDThh:mm:ss+0000 (optional)
        priority: Priority level (0: None, 1: Low, 3: Medium, 5: High) (optional)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    # Validate priority
    if priority not in [0, 1, 3, 5]:
        return "Invalid priority. Must be 0 (None), 1 (Low), 3 (Medium), or 5 (High)."
    
    try:
        # Validate dates if provided
        for date_str, date_name in [(start_date, "start_date"), (due_date, "due_date")]:
            if date_str:
                try:
                    # Try to parse the date to validate it
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    return f"Invalid {date_name} format. Use ISO format: YYYY-MM-DDThh:mm:ss+0000"
        
        resolved_project_id = _resolve_project_id(project_id)
        task = ticktick.create_task(
            title=title,
            project_id=resolved_project_id,
            content=content,
            start_date=start_date,
            due_date=due_date,
            priority=priority
        )
        
        if 'error' in task:
            return f"Error creating task: {task['error']}"
        
        # Auto-cache the created task
        task_id = task.get('id')
        if task_id:
            task_cache.add_task(task_id, resolved_project_id, title)
            logger.debug(f"Task {task_id} auto-cached")
        
        return f"Task created successfully:\n\n" + format_task(task)
    except Exception as e:
        logger.error(f"Error in create_task: {e}")
        return f"Error creating task: {str(e)}"

@mcp.tool()
async def update_task(
    task_id: str,
    project_id: str,
    title: str = None,
    content: str = None,
    start_date: str = None,
    due_date: str = None,
    priority: int = None
) -> str:
    """
    Update an existing task in TickTick.
    
    Args:
        task_id: ID of the task to update
        project_id: ID of the project the task belongs to (or 'Inbox' for the Inbox project)
        title: New task title (optional)
        content: New task description/content (optional)
        start_date: New start date in ISO format YYYY-MM-DDThh:mm:ss+0000 (optional)
        due_date: New due date in ISO format YYYY-MM-DDThh:mm:ss+0000 (optional)
        priority: New priority level (0: None, 1: Low, 3: Medium, 5: High) (optional)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    # Validate priority if provided
    if priority is not None and priority not in [0, 1, 3, 5]:
        return "Invalid priority. Must be 0 (None), 1 (Low), 3 (Medium), or 5 (High)."
    
    try:
        # Validate dates if provided
        for date_str, date_name in [(start_date, "start_date"), (due_date, "due_date")]:
            if date_str:
                try:
                    # Try to parse the date to validate it
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    return f"Invalid {date_name} format. Use ISO format: YYYY-MM-DDThh:mm:ss+0000"
        
        resolved_project_id = _resolve_project_id(project_id)
        task = ticktick.update_task(
            task_id=task_id,
            project_id=resolved_project_id,
            title=title,
            content=content,
            start_date=start_date,
            due_date=due_date,
            priority=priority
        )
        
        if 'error' in task:
            return f"Error updating task: {task['error']}"
        
        return f"Task updated successfully:\n\n" + format_task(task)
    except Exception as e:
        logger.error(f"Error in update_task: {e}")
        return f"Error updating task: {str(e)}"

@mcp.tool()
async def complete_task(project_id: str, task_id: str) -> str:
    """
    Mark a task as complete.
    
    Args:
        project_id: ID of the project (or 'Inbox' for the Inbox project)
        task_id: ID of the task
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        resolved_project_id = _resolve_project_id(project_id)
        result = ticktick.complete_task(resolved_project_id, task_id)
        if 'error' in result:
            return f"Error completing task: {result['error']}"
        
        return f"Task {task_id} marked as complete."
    except Exception as e:
        logger.error(f"Error in complete_task: {e}")
        return f"Error completing task: {str(e)}"

@mcp.tool()
async def delete_task(project_id: str, task_id: str) -> str:
    """
    Delete a task.
    
    Args:
        project_id: ID of the project (or 'Inbox' for the Inbox project)
        task_id: ID of the task
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        resolved_project_id = _resolve_project_id(project_id)
        result = ticktick.delete_task(resolved_project_id, task_id)
        if 'error' in result:
            return f"Error deleting task: {result['error']}"
        
        return f"Task {task_id} deleted successfully."
    except Exception as e:
        logger.error(f"Error in delete_task: {e}")
        return f"Error deleting task: {str(e)}"

@mcp.tool()
async def create_project(
    name: str,
    color: str = "#F18181",
    view_mode: str = "list"
) -> str:
    """
    Create a new project in TickTick.
    
    Args:
        name: Project name
        color: Color code (hex format) (optional)
        view_mode: View mode - one of list, kanban, or timeline (optional)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    # Validate view_mode
    if view_mode not in ["list", "kanban", "timeline"]:
        return "Invalid view_mode. Must be one of: list, kanban, timeline."
    
    try:
        project = ticktick.create_project(
            name=name,
            color=color,
            view_mode=view_mode
        )
        
        if 'error' in project:
            return f"Error creating project: {project['error']}"
        
        return f"Project created successfully:\n\n" + format_project(project)
    except Exception as e:
        logger.error(f"Error in create_project: {e}")
        return f"Error creating project: {str(e)}"

@mcp.tool()
async def delete_project(project_id: str) -> str:
    """
    Delete a project.
    
    Args:
        project_id: ID of the project (or 'Inbox' for the Inbox project)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        resolved_project_id = _resolve_project_id(project_id)
        result = ticktick.delete_project(resolved_project_id)
        if 'error' in result:
            return f"Error deleting project: {result['error']}"
        
        return f"Project {project_id} deleted successfully."
    except Exception as e:
        logger.error(f"Error in delete_project: {e}")
        return f"Error deleting project: {str(e)}"
    

### Improved Task MCP Tools

# Helper Functions

PRIORITY_MAP = {0: "None", 1: "Low", 3: "Medium", 5: "High"}

def _resolve_project_id(project_id_or_name: str) -> str:
    """
    Resolve a project identifier to a project ID.
    Handles special case for 'Inbox' or 'inbox'.
    
    Args:
        project_id_or_name: Either a project ID or 'Inbox'/'inbox'
    
    Returns:
        The resolved project ID
    """
    if project_id_or_name.lower() == "inbox":
        return INBOX_PROJECT_ID
    return project_id_or_name

def _get_task_due_datetime(task: Dict[str, Any]) -> Optional[datetime]:
    """
    Parse a task's dueDate and convert it to the task's local timezone.

    TickTick stores dueDate values in UTC (+0000) and records the user's
    intended timezone separately in the 'timeZone' field (an IANA name such
    as 'Asia/Kolkata'). Returning a UTC datetime would shift the calendar
    date for tasks scheduled in the early hours of a UTC+ timezone (e.g.
    5 AM IST is 11:30 PM UTC the previous day). Converting to the task's
    local timezone ensures all date comparisons use the correct calendar day.

    Returns:
        A timezone-aware datetime in the task's local timezone, or None if
        the dueDate field is absent or cannot be parsed.
    """
    due_date = task.get('dueDate')
    if not due_date:
        return None

    try:
        task_due_dt = datetime.strptime(due_date, "%Y-%m-%dT%H:%M:%S.%f%z")
    except (ValueError, TypeError):
        return None

    task_tz_name = task.get('timeZone')
    if task_tz_name:
        try:
            task_due_dt = task_due_dt.astimezone(ZoneInfo(task_tz_name))
        except (ZoneInfoNotFoundError, KeyError):
            logger.warning("Unknown timeZone '%s' for task '%s'; falling back to UTC.",
                           task_tz_name, task.get('id', '<unknown>'))

    return task_due_dt


def _is_task_due_today(task: Dict[str, Any]) -> bool:
    """Return True if the task is due on today's date in its local timezone."""
    task_due_dt = _get_task_due_datetime(task)
    if task_due_dt is None:
        return False
    return task_due_dt.date() == datetime.now(task_due_dt.tzinfo).date()


def _is_task_overdue(task: Dict[str, Any]) -> bool:
    """Return True if the task's due datetime is in the past in its local timezone."""
    task_due_dt = _get_task_due_datetime(task)
    if task_due_dt is None:
        return False
    return task_due_dt < datetime.now(task_due_dt.tzinfo)


def _is_task_due_in_days(task: Dict[str, Any], days: int) -> bool:
    """Return True if the task is due exactly *days* days from today in its local timezone."""
    task_due_dt = _get_task_due_datetime(task)
    if task_due_dt is None:
        return False
    target_date = (datetime.now(task_due_dt.tzinfo) + timedelta(days=days)).date()
    return task_due_dt.date() == target_date

def _task_matches_search(task: Dict[str, Any], search_term: str) -> bool:
    """Check if a task matches the search term (case-insensitive)."""
    search_term = search_term.lower()
    
    # Search in title
    title = task.get('title', '').lower()
    if search_term in title:
        return True
    
    # Search in content
    content = task.get('content', '').lower()
    if search_term in content:
        return True
    
    # Search in subtasks
    items = task.get('items', [])
    for item in items:
        item_title = item.get('title', '').lower()
        if search_term in item_title:
            return True
    
    return False

def _validate_task_data(task_data: Dict[str, Any], task_index: int) -> Optional[str]:
    """
    Validate a single task's data for batch creation.
    
    Returns:
        None if valid, error message string if invalid
    """
    # Check required fields
    if 'title' not in task_data or not task_data['title']:
        return f"Task {task_index + 1}: 'title' is required and cannot be empty"
    
    if 'project_id' not in task_data or not task_data['project_id']:
        return f"Task {task_index + 1}: 'project_id' is required and cannot be empty"
    
    # Validate priority if provided
    priority = task_data.get('priority')
    if priority is not None and priority not in [0, 1, 3, 5]:
        return f"Task {task_index + 1}: Invalid priority {priority}. Must be 0 (None), 1 (Low), 3 (Medium), or 5 (High)"
    
    # Validate dates if provided
    for date_field in ['start_date', 'due_date']:
        date_str = task_data.get(date_field)
        if date_str:
            try:
                # Try to parse the date to validate it
                # Handle both with and without timezone info
                if date_str.endswith('Z'):
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                elif '+' in date_str or date_str.endswith(('00', '30')):
                    datetime.fromisoformat(date_str)
                else:
                    # Assume local timezone if no timezone specified
                    datetime.fromisoformat(date_str)
            except ValueError:
                return f"Task {task_index + 1}: Invalid {date_field} format '{date_str}'. Use ISO format: YYYY-MM-DDTHH:mm:ss or with timezone"
    
    return None

def _get_project_tasks_by_filter(projects: List[Dict], filter_func, filter_name: str) -> str:
    """
    Helper function to filter tasks across all projects.
    
    Args:
        projects: List of project dictionaries
        filter_func: Function that takes a task and returns True if it matches the filter
        filter_name: Name of the filter for output formatting
    
    Returns:
        Formatted string of filtered tasks
    """
    if not projects:
        return "No projects found."
    
    result = f"Found {len(projects)} projects:\n\n"
    
    for i, project in enumerate(projects, 1):
        if project.get('closed'):
            continue
            
        project_id = project.get('id', 'No ID')
        project_data = ticktick.get_project_with_data(project_id)
        tasks = project_data.get('tasks', [])
        
        if not tasks:
            result += f"Project {i}:\n{format_project(project)}"
            result += f"With 0 tasks that are to be '{filter_name}' in this project :\n\n\n"
            continue
        
        # Filter tasks using the provided function
        filtered_tasks = [(t, task) for t, task in enumerate(tasks, 1) if filter_func(task)]
        
        result += f"Project {i}:\n{format_project(project)}"
        result += f"With {len(filtered_tasks)} tasks that are to be '{filter_name}' in this project :\n"
        
        for t, task in filtered_tasks:
            result += f"Task {t}:\n{format_task(task)}\n"
        
        result += "\n\n"
    
    return result

# New MCP Tools for Tasks

@mcp.tool()
async def get_all_tasks() -> str:
    """Get all tasks from TickTick. Ignores closed projects."""
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def all_tasks_filter(task: Dict[str, Any]) -> bool:
            return True  # Include all tasks
        
        return _get_project_tasks_by_filter(projects, all_tasks_filter, "included")
        
    except Exception as e:
        logger.error(f"Error in get_all_tasks: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def get_tasks_by_priority(priority_id: int) -> str:
    """
    Get all tasks from TickTick by priority. Ignores closed projects.

    Args:
        priority_id: Priority of tasks to retrieve {0: "None", 1: "Low", 3: "Medium", 5: "High"}
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    if priority_id not in PRIORITY_MAP:
        return f"Invalid priority_id. Valid values: {list(PRIORITY_MAP.keys())}"
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def priority_filter(task: Dict[str, Any]) -> bool:
            return task.get('priority', 0) == priority_id
        
        priority_name = f"{PRIORITY_MAP[priority_id]} ({priority_id})"
        return _get_project_tasks_by_filter(projects, priority_filter, f"priority '{priority_name}'")
        
    except Exception as e:
        logger.error(f"Error in get_tasks_by_priority: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def get_tasks_due_today() -> str:
    """Get all tasks from TickTick that are due today. Ignores closed projects."""
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def today_filter(task: Dict[str, Any]) -> bool:
            return _is_task_due_today(task)
        
        return _get_project_tasks_by_filter(projects, today_filter, "due today")
        
    except Exception as e:
        logger.error(f"Error in get_tasks_due_today: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def get_overdue_tasks() -> str:
    """Get all overdue tasks from TickTick. Ignores closed projects."""
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def overdue_filter(task: Dict[str, Any]) -> bool:
            return _is_task_overdue(task)
        
        return _get_project_tasks_by_filter(projects, overdue_filter, "overdue")
        
    except Exception as e:
        logger.error(f"Error in get_overdue_tasks: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def get_tasks_due_tomorrow() -> str:
    """Get all tasks from TickTick that are due today. Ignores closed projects."""
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def today_filter(task: Dict[str, Any]) -> bool:
            return _is_task_due_in_days(task, 1)
        
        return _get_project_tasks_by_filter(projects, today_filter, "due today")
        
    except Exception as e:
        logger.error(f"Error in get_tasks_due_today: {e}")
        return f"Error retrieving projects: {str(e)}"
    
@mcp.tool()
async def get_tasks_due_in_days(days: int) -> str:
    """
    Get all tasks from TickTick that are due in exactly X days. Ignores closed projects.
    
    Args:
        days: Number of days from today (0 = today, 1 = tomorrow, etc.)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    if days < 0:
        return "Days must be a non-negative integer."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def days_filter(task: Dict[str, Any]) -> bool:
            return _is_task_due_in_days(task, days)
        
        day_description = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        return _get_project_tasks_by_filter(projects, days_filter, f"due {day_description}")
        
    except Exception as e:
        logger.error(f"Error in get_tasks_due_in_days: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def get_tasks_due_this_week() -> str:
    """Get all tasks from TickTick that are due within the next 7 days. Ignores closed projects."""
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def week_filter(task: Dict[str, Any]) -> bool:
            task_due_dt = _get_task_due_datetime(task)
            if task_due_dt is None:
                return False
            today = datetime.now(task_due_dt.tzinfo).date()
            week_from_today = today + timedelta(days=7)
            return today <= task_due_dt.date() <= week_from_today
        
        return _get_project_tasks_by_filter(projects, week_filter, "due this week")
        
    except Exception as e:
        logger.error(f"Error in get_tasks_due_this_week: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def search_tasks(search_term: str) -> str:
    """
    Search for tasks in TickTick by title, content, or subtask titles. Ignores closed projects.
    
    Args:
        search_term: Text to search for (case-insensitive)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    if not search_term.strip():
        return "Search term cannot be empty."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def search_filter(task: Dict[str, Any]) -> bool:
            return _task_matches_search(task, search_term)
        
        return _get_project_tasks_by_filter(projects, search_filter, f"matching '{search_term}'")
        
    except Exception as e:
        logger.error(f"Error in search_tasks: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def batch_create_tasks(tasks: List[Dict[str, Any]]) -> str:
    """
    Create multiple tasks in TickTick at once
    
    Args:
        tasks: List of task dictionaries. Each task must contain:
            - title (required): Task Name
            - project_id (required): ID of the project for the task
            - content (optional): Task description
            - start_date (optional): Start date in user timezone (YYYY-MM-DDTHH:mm:ss or with timezone)
            - due_date (optional): Due date in user timezone (YYYY-MM-DDTHH:mm:ss or with timezone)  
            - priority (optional): Priority level {0: "None", 1: "Low", 3: "Medium", 5: "High"}
    
    Example:
        tasks = [
            {"title": "Example A", "project_id": "1234ABC", "priority": 5},
            {"title": "Example B", "project_id": "1234XYZ", "content": "Description", "start_date": "2025-07-18T10:00:00", "due_date": "2025-07-19T10:00:00"}
        ]
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    if not tasks:
        return "No tasks provided. Please provide a list of tasks to create."
    
    if not isinstance(tasks, list):
        return "Tasks must be provided as a list of dictionaries."
    
    # Validate all tasks before creating any
    validation_errors = []
    for i, task_data in enumerate(tasks):
        if not isinstance(task_data, dict):
            validation_errors.append(f"Task {i + 1}: Must be a dictionary")
            continue
        
        error = _validate_task_data(task_data, i)
        if error:
            validation_errors.append(error)
    
    if validation_errors:
        return "Validation errors found:\n" + "\n".join(validation_errors)
    
    # Create tasks one by one and collect results
    created_tasks = []
    failed_tasks = []
    
    try:
        for i, task_data in enumerate(tasks):
            try:
                # Extract task parameters with defaults
                title = task_data['title']
                project_id = task_data['project_id']
                content = task_data.get('content')
                start_date = task_data.get('start_date')
                due_date = task_data.get('due_date')
                priority = task_data.get('priority', 0)
                
                # Create the task
                result = ticktick.create_task(
                    title=title,
                    project_id=project_id,
                    content=content,
                    start_date=start_date,
                    due_date=due_date,
                    priority=priority
                )
                
                if 'error' in result:
                    failed_tasks.append(f"Task {i + 1} ('{title}'): {result['error']}")
                else:
                    created_tasks.append((i + 1, title, result))
                    # Auto-cache the created task
                    task_id = result.get('id')
                    if task_id:
                        task_cache.add_task(task_id, project_id, title)
                    
            except Exception as e:
                failed_tasks.append(f"Task {i + 1} ('{task_data.get('title', 'Unknown')}'): {str(e)}")
        
        # Format the results
        result_message = f"Batch task creation completed.\n\n"
        result_message += f"Successfully created: {len(created_tasks)} tasks\n"
        result_message += f"Failed: {len(failed_tasks)} tasks\n\n"
        
        if created_tasks:
            result_message += "✅ Successfully Created Tasks:\n"
            for task_num, title, task_obj in created_tasks:
                result_message += f"{task_num}. {title} (ID: {task_obj.get('id', 'Unknown')})\n"
            result_message += "\n"
        
        if failed_tasks:
            result_message += "❌ Failed Tasks:\n"
            for error in failed_tasks:
                result_message += f"{error}\n"
        
        return result_message
        
    except Exception as e:
        logger.error(f"Error in batch_create_tasks: {e}")
        return f"Error during batch task creation: {str(e)}"

# New MCP Tools for Getting things done framework (Priority / Due Dates)

@mcp.tool()
async def get_engaged_tasks() -> str:
    """
    Get all tasks from TickTick that are "Engaged".
    This includes tasks marked as high priority (5), due today or overdue.
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def engaged_filter(task: Dict[str, Any]) -> bool:
            is_high_priority = task.get('priority', 0) == 5
            is_overdue = _is_task_overdue(task)
            is_today = _is_task_due_today(task)
            return is_high_priority or is_overdue or is_today
        
        return _get_project_tasks_by_filter(projects, engaged_filter, "engaged")
        
    except Exception as e:
        logger.error(f"Error in get_engaged_tasks: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def get_next_tasks() -> str:
    """
    Get all tasks from TickTick that are "Next".
    This includes tasks marked as medium priority (3) or due tomorrow.
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        projects = _get_all_projects_including_inbox()
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        def next_filter(task: Dict[str, Any]) -> bool:
            is_medium_priority = task.get('priority', 0) == 3
            is_due_tomorrow = _is_task_due_in_days(task, 1)
            return is_medium_priority or is_due_tomorrow
        
        return _get_project_tasks_by_filter(projects, next_filter, "next")
        
    except Exception as e:
        logger.error(f"Error in get_next_tasks: {e}")
        return f"Error retrieving projects: {str(e)}"

@mcp.tool()
async def create_subtask(
    subtask_title: str,
    parent_task_id: str,
    project_id: str,
    content: str = None,
    priority: int = 0
) -> str:
    """
    Create a subtask for a parent task within the same project.
    
    Args:
        subtask_title: Title of the subtask
        parent_task_id: ID of the parent task
        project_id: ID of the project (must be same for both parent and subtask) (or 'Inbox' for the Inbox project)
        content: Optional content/description for the subtask
        priority: Priority level (0: None, 1: Low, 3: Medium, 5: High) (optional)
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    # Validate priority
    if priority not in [0, 1, 3, 5]:
        return "Invalid priority. Must be 0 (None), 1 (Low), 3 (Medium), or 5 (High)."
    
    try:
        resolved_project_id = _resolve_project_id(project_id)
        subtask = ticktick.create_subtask(
            subtask_title=subtask_title,
            parent_task_id=parent_task_id,
            project_id=resolved_project_id,
            content=content,
            priority=priority
        )
        
        if 'error' in subtask:
            return f"Error creating subtask: {subtask['error']}"
        
        return f"Subtask created successfully:\n\n" + format_task(subtask)
    except Exception as e:
        logger.error(f"Error in create_subtask: {e}")
        return f"Error creating subtask: {str(e)}"


# Cache Tools

@mcp.tool()
async def get_cached_tasks(project_id: str = None, include_stale: bool = False) -> str:
    """
    Get tasks from the local cache. Useful for quick lookups without API calls.
    
    Args:
        project_id: Optional project ID to filter by (or 'Inbox' for the Inbox project)
        include_stale: Whether to include tasks older than 24 hours (default: False)
    """
    try:
        resolved_project_id = None
        if project_id:
            resolved_project_id = _resolve_project_id(project_id)
        
        cached_tasks = task_cache.get_tasks(
            project_id=resolved_project_id,
            include_stale=include_stale
        )
        
        if not cached_tasks:
            return "No cached tasks found."
        
        result = f"Found {len(cached_tasks)} cached tasks:\n\n"
        for i, task in enumerate(cached_tasks, 1):
            stale_marker = " (stale)" if task_cache.is_task_stale(task) else ""
            result += f"{i}. {task.get('title', 'No title')}{stale_marker}\n"
            result += f"   Task ID: {task.get('task_id')}\n"
            result += f"   Project ID: {task.get('project_id')}\n"
            result += f"   Cached: {task.get('cached_at', 'Unknown')}\n\n"
        
        return result
    except Exception as e:
        logger.error(f"Error in get_cached_tasks: {e}")
        return f"Error retrieving cached tasks: {str(e)}"


@mcp.tool()
async def register_task_id(task_id: str, project_id: str, title: str) -> str:
    """
    Manually register a task ID in the cache. Useful for tasks not created through this server.
    
    Args:
        task_id: TickTick task ID
        project_id: TickTick project ID (or 'Inbox' for the Inbox project)
        title: Task title for reference
    """
    try:
        resolved_project_id = _resolve_project_id(project_id)
        task_cache.add_task(task_id, resolved_project_id, title)
        return f"Task '{title}' (ID: {task_id}) registered in cache."
    except Exception as e:
        logger.error(f"Error in register_task_id: {e}")
        return f"Error registering task: {str(e)}"


@mcp.tool()
async def clear_task_cache(clear_all: bool = False) -> str:
    """
    Clear tasks from the cache.
    
    Args:
        clear_all: If True, clears all tasks. If False, only clears stale tasks (default: False)
    """
    try:
        if clear_all:
            task_cache.clear_cache()
            return "All cached tasks have been cleared."
        else:
            removed = task_cache.clear_stale_tasks()
            return f"Removed {removed} stale tasks from cache."
    except Exception as e:
        logger.error(f"Error in clear_task_cache: {e}")
        return f"Error clearing cache: {str(e)}"


# DateTime Conversion Tools

@mcp.tool()
async def convert_datetime_to_ticktick_format(datetime_string: str, timezone: str = None) -> str:
    """
    Convert a human-readable datetime to TickTick API format.
    
    Args:
        datetime_string: Date/datetime in ISO format:
            - Date only: '2024-07-26'
            - Datetime: '2024-07-26T10:00:00'
            - With timezone: '2024-07-26T10:00:00+09:00'
        timezone: IANA timezone name (e.g., 'America/New_York', 'Asia/Seoul').
            Used if datetime_string doesn't include timezone info.
    
    Returns:
        TickTick format datetime (e.g., '2024-08-15T00:00:00.000+0900')
    """
    try:
        result = datetime_to_ticktick_format(datetime_string, timezone)
        return f"TickTick format: {result}"
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in convert_datetime_to_ticktick_format: {e}")
        return f"Error converting datetime: {str(e)}"


@mcp.tool()
async def convert_ticktick_to_readable(
    ticktick_datetime: str, 
    timezone: str = None, 
    format_type: str = "datetime"
) -> str:
    """
    Convert a TickTick datetime to human-readable format.
    
    Args:
        ticktick_datetime: TickTick format datetime (e.g., '2024-08-15T00:00:00.000+0900')
        timezone: Target timezone for display (IANA name, e.g., 'America/Los_Angeles')
        format_type: Output format:
            - 'date': 'Aug 15, 2024'
            - 'datetime': 'Aug 15, 2024 at 10:00 AM'
            - 'relative': 'Tomorrow', 'In 3 days', '2 days ago'
    
    Returns:
        Human-readable datetime string
    """
    try:
        result = ticktick_to_human_readable(ticktick_datetime, timezone, format_type)
        return f"Human-readable: {result}"
    except Exception as e:
        logger.error(f"Error in convert_ticktick_to_readable: {e}")
        return f"Error converting datetime: {str(e)}"


# Advanced Filtering Tool

@mcp.tool()
async def filter_tasks(
    status: str = "uncompleted",
    project_id: str = None,
    tag_label: str = None,
    priority: int = None,
    start_date: str = None,
    end_date: str = None,
    timezone: str = None,
    sort_by_priority: bool = False
) -> str:
    """
    Advanced task filtering with multiple criteria.
    
    Args:
        status: 'uncompleted' or 'completed' (default: 'uncompleted')
        project_id: Filter by project ID (or 'Inbox' for the Inbox project)
        tag_label: Filter by tag name
        priority: Filter by priority (0=None, 1=Low, 3=Medium, 5=High)
        start_date: Start of date range (ISO format: YYYY-MM-DD)
        end_date: End of date range (ISO format: YYYY-MM-DD)
        timezone: IANA timezone name (e.g., 'America/New_York')
        sort_by_priority: Sort results by priority, highest first (default: False)
    
    Note:
        - For uncompleted tasks, date filters apply to due dates
        - For completed tasks, date filters apply to completion dates
    """
    if not ticktick:
        if not initialize_client():
            return "Failed to initialize TickTick client. Please check your API credentials."
    
    try:
        # Build filter criteria
        filter_criteria = {
            'status': status,
            'project_id': _resolve_project_id(project_id) if project_id else None,
            'tag_label': tag_label,
            'priority': priority,
            'start_date': start_date,
            'end_date': end_date,
            'timezone': timezone,
            'sort_by_priority': sort_by_priority
        }
        
        property_filter, should_sort = build_property_filter(filter_criteria)
        filterer = TaskFilterer(ticktick)
        
        # Collect all tasks from all projects
        all_tasks = []
        projects = _get_all_projects_including_inbox()
        
        if 'error' in projects:
            return f"Error fetching projects: {projects['error']}"
        
        for project in projects:
            if project.get('closed'):
                continue
            
            proj_id = project.get('id')
            
            # Skip other projects if filtering by specific project
            if filter_criteria['project_id'] and proj_id != filter_criteria['project_id']:
                continue
            
            project_data = ticktick.get_project_with_data(proj_id)
            tasks = project_data.get('tasks', [])
            
            # Add project name to each task for display
            for task in tasks:
                task['_project_name'] = project.get('name', 'Unknown')
            
            all_tasks.extend(tasks)
        
        # Apply filter
        filtered_tasks = await filterer.filter(all_tasks, property_filter, should_sort)
        
        if not filtered_tasks:
            return f"No tasks found matching the filter criteria."
        
        # Format results
        result = f"Found {len(filtered_tasks)} tasks matching filter:\n"
        result += f"Status: {status}"
        if project_id:
            result += f", Project: {project_id}"
        if tag_label:
            result += f", Tag: {tag_label}"
        if priority is not None:
            result += f", Priority: {PRIORITY_MAP.get(priority, priority)}"
        if start_date or end_date:
            result += f", Date range: {start_date or 'any'} to {end_date or 'any'}"
        result += "\n\n"
        
        for i, task in enumerate(filtered_tasks, 1):
            result += f"Task {i} (Project: {task.get('_project_name', 'Unknown')}):\n"
            result += format_task(task) + "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in filter_tasks: {e}")
        return f"Error filtering tasks: {str(e)}"


def main():
    """Main entry point for the MCP server."""
    # Initialize the TickTick client
    if not initialize_client():
        logger.error("Failed to initialize TickTick client. Please check your API credentials.")
        return
    
    # Run the server
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()