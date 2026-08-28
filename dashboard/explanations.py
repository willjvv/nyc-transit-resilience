"""
Plain language explanations for dashboard metrics.
Centralized to ensure consistency and easy updates.
"""

# Metric explanations for general audience
METRIC_EXPLANATIONS = {
    "on_time_performance": {
        "title": "Trains On Schedule",
        "simple": "Percentage of final observed realtime predictions that are within 5 minutes of the scheduled time.",
        "detailed": "On-time performance here measures the final observed realtime prediction against the published schedule. A prediction is counted as on-time when it is within 5 minutes of the scheduled arrival; this dashboard does not have an authoritative observed-arrival timestamp.",
        "context": "90% on-time means 9 out of 10 final observed predictions are within 5 minutes of schedule. It is a prediction-based reliability signal, not a direct measurement of platform arrival times.",
        "target": "90% is considered a good performance target for NYC subway service."
    },
    "average_delay": {
        "title": "Average Delay",
        "simple": "Average predicted lateness versus the scheduled time; this is not an observed arrival timestamp.",
        "detailed": "Average prediction delay shows how far the final observed realtime prediction is from schedule. GTFS-realtime TripUpdates do not by themselves provide an authoritative observed arrival timestamp.",
        "context": "An average prediction delay of 3 minutes means the final observed realtime predictions were, on average, 3 minutes behind schedule. It should not be read as proof that trains physically arrived 3 minutes late.",
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
        "simple": "Realtime predictions that cannot be confidently matched to the active published schedule.",
        "detailed": "Predictions can be unmatched or ambiguous when service has changed, extra service is operating, or the available identifying fields are insufficient to distinguish adjacent trips. These are reconciliation-quality signals, not proof that trains are missing.",
        "context": "Higher rates indicate that more predictions lack strong schedule-matching evidence. This can reflect added service, schedule changes, or limitations in the available identifiers.",
        "technical_note": "This metric helps identify when the real-time feed may need adjustment."
    },
    "delay_by_hour": {
        "title": "Delay Patterns by Time",
        "simple": "When delays typically happen during the day.",
        "detailed": "Shows average delays by hour of day for each subway line. This helps identify patterns like morning rush hour issues or late-night reliability problems.",
        "context": "Many lines have predictable delay patterns - for example, more delays during peak commuting hours. Understanding these patterns can help you plan your travel times.",
        "usage": "Use this to spot which times of day are most problematic for your regular line."
    },
    "betweenness_centrality": {
        "title": "Network Criticality",
        "simple": "How important a station is for overall subway connectivity.",
        "detailed": "Betweenness centrality measures how often a station lies on the shortest paths between other stations. Stations with high betweenness are critical bottlenecks - if they fail, many trips become impossible or much longer.",
        "context": "Times Square has high betweenness because it connects many different lines. If Times Square has problems, it affects riders across the entire system, not just one line.",
        "example": "A station with 0.15 betweenness means 15% of all shortest paths in the network go through it."
    },
    "degree_centrality": {
        "title": "Connection Diversity",
        "simple": "How many direct connections a station has to other stations.",
        "detailed": "Degree centrality counts the number of direct connections (routes) a station has. Stations with high degree serve multiple lines and offer more routing options.",
        "context": "DeKalb Avenue serves 6 different lines (N, D, Q, R, W, B), giving it high degree centrality and making it a major transfer hub.",
        "benefit": "High-degree stations give you more options when your regular line has issues."
    },
    "closeness_centrality": {
        "title": "Accessibility Score",
        "simple": "How quickly you can reach other parts of the subway system from a station.",
        "detailed": "Closeness centrality measures the average distance from a station to all other stations in the network. High closeness means you can reach most of the system with few transfers.",
        "context": "A station in the middle of Manhattan might have high closeness because it's centrally located and well-connected to the rest of the network.",
        "usage": "Choose stations with high closeness for easier access to the entire system."
    },
    "network_resilience": {
        "title": "System Resilience",
        "simple": "How well the subway system handles disruptions and failures.",
        "detailed": "Network resilience measures how the subway system maintains connectivity when individual stations or lines have problems. A resilient system has multiple alternative routes and doesn't rely too heavily on any single connection.",
        "context": "If the 4/5 lines fail, can riders still get between Brooklyn and Manhattan? Network resilience answers this by analyzing alternative paths.",
        "importance": "Understanding resilience helps commuters plan backup routes and the MTA prioritize infrastructure investments."
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
    "ghost_warning": 10,  # legacy dashboard threshold for prediction-quality issues
    "delay_good": 5,  # minutes
    "delay_concern": 10  # minutes
}

# Onboarding text
ONBOARDING = {
    "what_is_this": {
        "title": "What is this dashboard?",
        "content": """
        This dashboard compares MTA realtime arrival predictions with the active published schedule.
        It measures prediction-to-schedule differences; it does not claim those predictions are observed arrivals.

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
        3. We calculate how early or late the final observed prediction is versus schedule
        4. We summarize prediction-based metrics and data-quality indicators
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
        - Check unmatched/ambiguous prediction rates to identify data quality issues
        - Use Network Resilience analysis to understand system connectivity and critical stations
        """
    },
    "network_resilience_info": {
        "title": "Understanding Network Resilience",
        "content": """
        **What is Network Resilience?**
        Network resilience measures how well the subway system maintains connectivity when individual stations or lines have problems. Think of it as the subway's ability to keep working even when parts of it fail.

        **Why Critical Stations Matter:**
        Some stations are more important than others for overall system connectivity. These "critical stations" serve as major hubs where many lines intersect. If Times Square has problems, it affects riders across the entire system, not just people using that specific station.

        **How to Use This Information:**
        - **Commute Planning**: Choose routes that avoid critical stations if you want more reliable options
        - **Backup Routes**: Know alternative paths when your regular station has issues
        - **System Understanding**: Learn which parts of the network are most vulnerable to disruptions
        - **Timing Awareness**: Critical stations often have more delays due to their importance
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
        "answer": "A final observed realtime prediction is counted as on-time when it is within 5 minutes of the scheduled time. This dashboard should not be interpreted as a direct measurement of physical arrival timestamps."
    },
    {
        "question": "Why do some lines have higher unmatched prediction rates?",
        "answer": "Unmatched or ambiguous predictions can reflect added service, schedule changes, or limitations in the matching evidence. High rates are primarily a data-quality signal, not proof that trains are missing."
    },
    {
        "question": "How often is this data updated?",
        "answer": "Real-time data is collected continuously, but the dashboard is updated daily with the previous day's complete performance data."
    },
    {
        "question": "Can I use this to plan my commute?",
        "answer": "Yes! Check your line's reliability and typical delay patterns. However, for real-time arrival information, use the MTA's official apps or website."
    },
    {
        "question": "What does 'critical station' mean?",
        "answer": "Critical stations are those that are most important for overall subway connectivity. If a critical station has problems, it affects many riders across different lines, not just people using that specific station."
    },
    {
        "question": "Why are some stations more critical than others?",
        "answer": "Stations become critical when they serve multiple lines, are located centrally, or lie on the most direct paths between many other stations. Times Square is critical because it connects so many different lines and routes."
    },
    {
        "question": "How can I use network resilience information?",
        "answer": "Network resilience helps you understand backup route options. If your regular line has issues, knowing which stations are critical helps you find alternative paths and understand system-wide disruption patterns."
    },
    {
        "question": "What happens if a critical station fails?",
        "answer": "When a critical station has problems, the impact ripples through the entire system. Many trips become impossible, take much longer, or require complex workarounds. This is why the MTA prioritizes maintenance at critical stations."
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
