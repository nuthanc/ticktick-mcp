"""
DateTime conversion utilities for TickTick MCP server.
Provides bidirectional conversion between human-readable datetime and TickTick's API format.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# TickTick datetime format: YYYY-MM-DDTHH:mm:ss.fff+ZZZZ (e.g., 2024-08-15T00:00:00.000+0900)
TICKTICK_FORMAT = "%Y-%m-%dT%H:%M:%S.000%z"


def datetime_to_ticktick_format(dt_string: str, tz: Optional[str] = None) -> str:
    """
    Convert an ISO datetime string to TickTick API format.
    
    Args:
        dt_string: Input datetime string. Supports:
            - Date only: '2024-07-26'
            - Naive datetime: '2024-07-26T10:00:00'
            - Datetime with timezone: '2024-07-26T10:00:00+09:00'
        tz: IANA timezone name (e.g., 'America/New_York', 'Asia/Seoul').
            Used if input is naive (no timezone info).
            
    Returns:
        TickTick format datetime string (e.g., '2024-08-15T00:00:00.000+0900')
        
    Raises:
        ValueError: If the datetime string is invalid or timezone is unknown
    """
    try:
        # Try parsing as date only first
        try:
            dt_obj = datetime.strptime(dt_string, "%Y-%m-%d")
            # Set time to start of day
            dt_obj = datetime.combine(dt_obj.date(), datetime.min.time())
        except ValueError:
            # Try parsing as ISO datetime
            dt_obj = datetime.fromisoformat(dt_string.replace("Z", "+00:00"))
        
        # If naive datetime and timezone provided, localize it
        if dt_obj.tzinfo is None:
            if tz:
                try:
                    timezone = ZoneInfo(tz)
                    dt_obj = dt_obj.replace(tzinfo=timezone)
                except KeyError:
                    raise ValueError(f"Unknown timezone: {tz}")
            else:
                # Default to UTC if no timezone specified
                dt_obj = dt_obj.replace(tzinfo=ZoneInfo("UTC"))
        
        # Format to TickTick format
        # TickTick uses format like +0900 without colon, but Python uses +09:00
        formatted = dt_obj.strftime("%Y-%m-%dT%H:%M:%S.000%z")
        
        # Remove the colon in timezone offset if present (e.g., +09:00 -> +0900)
        if len(formatted) > 5 and formatted[-3] == ':':
            formatted = formatted[:-3] + formatted[-2:]
        
        return formatted
        
    except ValueError as e:
        logger.error(f"Failed to parse datetime '{dt_string}': {e}")
        raise ValueError(f"Invalid datetime format: {dt_string}. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:mm:ss)")


def ticktick_to_human_readable(
    ticktick_dt: str, 
    tz: Optional[str] = None, 
    format_type: str = "datetime"
) -> str:
    """
    Convert TickTick datetime format to human-readable format.
    
    Args:
        ticktick_dt: TickTick format datetime (e.g., '2024-08-15T00:00:00.000+0900')
        tz: Target timezone for display (IANA name, e.g., 'America/Los_Angeles').
            If not provided, uses the timezone from the input.
        format_type: Output format type:
            - 'date': 'Aug 15, 2024'
            - 'datetime': 'Aug 15, 2024 at 10:00 AM'
            - 'relative': 'Tomorrow', 'In 3 days', '2 days ago'
            
    Returns:
        Human-readable datetime string
        
    Raises:
        ValueError: If the datetime string is invalid
    """
    if not ticktick_dt:
        return ""
    
    try:
        # Parse TickTick format
        # Handle both +0900 and +09:00 formats
        dt_string = ticktick_dt
        
        # If timezone offset doesn't have colon, add it for parsing
        # Check if it ends with timezone offset like +0900 or -0500
        if len(dt_string) >= 5:
            if dt_string[-5] in ['+', '-'] and ':' not in dt_string[-5:]:
                # Insert colon: +0900 -> +09:00
                dt_string = dt_string[:-2] + ':' + dt_string[-2:]
        
        # Parse the datetime
        dt_obj = datetime.fromisoformat(dt_string)
        
        # Convert to target timezone if specified
        if tz:
            try:
                target_tz = ZoneInfo(tz)
                dt_obj = dt_obj.astimezone(target_tz)
            except KeyError:
                logger.warning(f"Unknown timezone: {tz}, using original")
        
        # Format based on requested type
        if format_type == "date":
            return dt_obj.strftime("%b %d, %Y")
        
        elif format_type == "datetime":
            return dt_obj.strftime("%b %d, %Y at %I:%M %p")
        
        elif format_type == "relative":
            return _format_relative_date(dt_obj)
        
        else:
            # Default to datetime format
            return dt_obj.strftime("%b %d, %Y at %I:%M %p")
            
    except ValueError as e:
        logger.error(f"Failed to parse TickTick datetime '{ticktick_dt}': {e}")
        # Return original string if parsing fails
        return ticktick_dt


def _format_relative_date(dt_obj: datetime) -> str:
    """
    Format a datetime as a relative date string.
    
    Args:
        dt_obj: Datetime object to format
        
    Returns:
        Relative date string (e.g., 'Today', 'Tomorrow', 'In 3 days', '2 days ago')
    """
    now = datetime.now(dt_obj.tzinfo)
    today = now.date()
    target_date = dt_obj.date()
    
    diff_days = (target_date - today).days
    
    if diff_days == 0:
        return "Today"
    elif diff_days == 1:
        return "Tomorrow"
    elif diff_days == -1:
        return "Yesterday"
    elif diff_days > 1 and diff_days <= 7:
        return f"In {diff_days} days"
    elif diff_days < -1 and diff_days >= -7:
        return f"{abs(diff_days)} days ago"
    elif diff_days > 7:
        weeks = diff_days // 7
        if weeks == 1:
            return "In 1 week"
        elif weeks <= 4:
            return f"In {weeks} weeks"
        else:
            return dt_obj.strftime("%b %d, %Y")
    else:
        weeks = abs(diff_days) // 7
        if weeks == 1:
            return "1 week ago"
        elif weeks <= 4:
            return f"{weeks} weeks ago"
        else:
            return dt_obj.strftime("%b %d, %Y")


def parse_ticktick_datetime(ticktick_dt: str) -> Optional[datetime]:
    """
    Parse a TickTick datetime string into a datetime object.
    
    Args:
        ticktick_dt: TickTick format datetime string
        
    Returns:
        Datetime object or None if parsing fails
    """
    if not ticktick_dt:
        return None
    
    try:
        dt_string = ticktick_dt
        
        # If timezone offset doesn't have colon, add it for parsing
        if len(dt_string) >= 5:
            if dt_string[-5] in ['+', '-'] and ':' not in dt_string[-5:]:
                dt_string = dt_string[:-2] + ':' + dt_string[-2:]
        
        return datetime.fromisoformat(dt_string)
    except ValueError as e:
        logger.warning(f"Failed to parse TickTick datetime '{ticktick_dt}': {e}")
        return None


def get_local_timezone() -> str:
    """
    Get the local timezone name.
    
    Returns:
        IANA timezone name or 'UTC' as fallback
    """
    try:
        import time
        # Try to get local timezone
        if time.daylight:
            local_tz = time.tzname[1]
        else:
            local_tz = time.tzname[0]
        
        # This might return abbreviations like 'PST', 'EST' which aren't IANA names
        # For now, return a reasonable default
        return "UTC"
    except Exception:
        return "UTC"
