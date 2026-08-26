"""
Plain language explanations for dashboard metrics.
Centralized to ensure consistency and easy updates.
"""

# Metric explanations for general audience
METRIC_EXPLANATIONS = {
    "on_time_performance": {
        "title": "Trains On Schedule",
        "simple": "Percentage of trains that arrive within 5 minutes of their scheduled time.",
        "detailed": "On-time performance measures how often trains arrive close to their published schedule. A train is considered 'on time' if it arrives within 5 minutes of the scheduled arrival time. This is the same standard used by NYC Transit for official reporting.",
        "context": "90% on-time means 9 out of 10 trains arrive within 5 minutes of schedule. For your daily commute, this means most trips run close to the published timetable.",
        "target": "90% is considered a good performance target for NYC subway service."
    },
    "average_delay": {
        "title": "Average Delay",
        "simple": "Average number of minutes trains are late when they don't arrive on schedule.",
        "detailed": "Average delay shows the typical lateness for trains that miss their scheduled arrival time. This helps you understand how severe delays are when they occur, not just how often they happen.",
        "context": "An average delay of 3 minutes means most riders experience minimal impact on their commute. Delays over 10 minutes typically indicate significant service issues.",
        "good_threshold": "Under 5 minutes is considered normal for urban rail systems."
    },
    "reliable_lines": {
        "title": "Most/Least Reliable Lines",
        "simple": "Which subway lines have the best and worst on-time performance.",
        "detailed": "Shows which lines consistently meet their schedule and which ones experience more frequent delays. This can help you choose alternative routes or plan for potential delays on certain lines.",
        "context": "Some lines are more prone to delays due to infrastructure, rider demand, or operational factors. This metric helps you understand which lines to watch out for.",
        "tip": "Consider using the most reliable lines for your commute when possible."
    },
    "ghost_trains": {
        "title": "Unmatched Predictions",
        "simple": "Real-time train predictions that don't match the published schedule.",
        "detailed": "Sometimes the MTA's real-time system shows trains that don't correspond to scheduled trips. This can be extra trains added during rush hour, schedule changes, or technical issues with the prediction system.",
        "context": "A low rate (under 10%) is normal and expected. High rates may indicate data quality issues rather than actual missing trains.",
        "technical_note": "This metric helps identify when the real-time feed may need adjustment."
    },
    "delay_by_hour": {
        "title": "Delay Patterns by Time",
        "simple": "When delays typically happen during the day.",
        "detailed": "Shows average delays by hour of day for each subway line. This helps identify patterns like morning rush hour issues or late-night reliability problems.",
        "context": "Many lines have predictable delay patterns - for example, more delays during peak commuting hours. Understanding these patterns can help you plan your travel times.",
        "usage": "Use this to spot which times of day are most problematic for your regular line."
    }
}

# Color coding explanations
COLOR_EXPLANATIONS = {
    "green": {
        "emoji": "🟢",
        "meaning": "Good performance - meets or exceeds target",
        "example": "On-time rate of 90% or higher"
    },
    "amber": {
        "emoji": "🟡", 
        "meaning": "Acceptable but below target - room for improvement",
        "example": "On-time rate between 75-89%"
    },
    "red": {
        "emoji": "🔴",
        "meaning": "Poor performance - significantly below target",
        "example": "On-time rate below 75%"
    }
}

# Thresholds used throughout the dashboard
THRESHOLDS = {
    "on_time_target": 90,  # percentage
    "on_time_warning": 75,  # percentage  
    "ghost_warning": 10,  # percentage
    "delay_good": 5,  # minutes
    "delay_concern": 10  # minutes
}

# Onboarding text
ONBOARDING = {
    "what_is_this": {
        "title": "What is this dashboard?",
        "content": """
        This dashboard shows how well NYC subway trains are running compared to their published schedules. 
        It uses real-time data from the MTA to measure actual performance vs. planned performance.
        
        **Why it matters:** Understanding service reliability helps you:
        - Plan your commute with realistic expectations
        - Choose alternative routes when your regular line has issues  
        - Understand system-wide performance trends
        """
    },
    "data_source": {
        "title": "Where does this data come from?",
        "content": """
        The MTA (Metropolitan Transportation Authority) provides real-time feeds showing train positions and predicted arrival times. 
        This dashboard compares those real-time predictions against the official subway schedule.
        
        **How it works:**
        1. Every 30-60 seconds, we collect real-time train data from the MTA
        2. We match each real-time train to its scheduled trip
        3. We calculate how early or late each train arrives
        4. We summarize this data into the metrics you see here
        """
    },
    "how_to_use": {
        "title": "How to use this dashboard",
        "content": """
        **For daily commuters:**
        - Check the "Trains On Schedule" metric for your line
        - Look at "Delay Patterns by Time" to avoid problem hours
        - Use "Most/Least Reliable Lines" to plan alternative routes
        
        **For detailed analysis:**
        - Switch to Advanced View for more metrics
        - Explore delay patterns by hour for specific lines
        - Check ghost train rates to identify data quality issues
        """
    }
}

# FAQ section
FAQ = [
    {
        "question": "Why isn't my train showing up in the data?",
        "answer": "Data is processed daily, so today's trips won't appear until tomorrow. Also, some short trips or very late trains may not match the schedule perfectly."
    },
    {
        "question": "What counts as 'on time'?",
        "answer": "A train is on time if it arrives within 5 minutes of its scheduled arrival time. This matches the official standard used by NYC Transit."
    },
    {
        "question": "Why do some lines have higher ghost train rates?",
        "answer": "Ghost trains are often extra service added during rush hour, or schedule changes that haven't been fully updated in the system. Rates above 10% may indicate data issues."
    },
    {
        "question": "How often is this data updated?",
        "answer": "Real-time data is collected continuously, but the dashboard is updated daily with the previous day's complete performance data."
    },
    {
        "question": "Can I use this to plan my commute?",
        "answer": "Yes! Check your line's reliability and typical delay patterns. However, for real-time arrival information, use the MTA's official apps or website."
    }
]

def get_explanation(metric_key, view="simple"):
    """Get explanation for a metric based on view level."""
    if metric_key not in METRIC_EXPLANATIONS:
        return None
    
    metric = METRIC_EXPLANATIONS[metric_key]
    if view == "simple":
        return metric["simple"]
    return metric["detailed"]

def get_context(metric_key):
    """Get real-world context for a metric."""
    if metric_key not in METRIC_EXPLANATIONS:
        return None
    return METRIC_EXPLANATIONS[metric_key].get("context", "")

def get_color_explanation(color_key):
    """Get explanation for color coding."""
    return COLOR_EXPLANATIONS.get(color_key, {})