"""Plain-language dashboard copy and thresholds."""

THRESHOLDS = {
    "on_time_target": 90,
    "on_time_warning": 75,
    "quality_warning": 10,
}

FAQ = [
    {
        "question": "What does 'on schedule' mean?",
        "answer": "A matched realtime prediction is on schedule when its predicted arrival is within ±5 minutes of the published static schedule.",
    },
    {
        "question": "Is this measuring actual train arrivals?",
        "answer": "No. GTFS-Realtime Trip Updates provide predicted arrival times. The dashboard measures the final prediction observed for a matched trip-stop, not an authoritative physical arrival timestamp.",
    },
    {
        "question": "Why is a prediction unmatched?",
        "answer": "A realtime record may represent added service, a schedule change, or simply lack enough evidence to identify one scheduled trip confidently. Unmatched and ambiguous records are retained as data-quality signals instead of being forced into a schedule match.",
    },
    {
        "question": "Why can a line have a high quality-issue rate?",
        "answer": "Realtime and static feeds do not always describe service in exactly the same way. Extra service, schedule changes, and incomplete matching evidence can all increase the rate. It is not proof that trains are missing.",
    },
    {
        "question": "Why does the network page look different from the performance page?",
        "answer": "Performance is based on realtime prediction-vs-schedule measurements. Network importance is derived from the static subway topology and scheduled running times. A highly important station is not necessarily delayed right now.",
    },
    {
        "question": "Can I use this to plan a trip right now?",
        "answer": "Use the MTA's official realtime tools for current arrival information. This dashboard is designed for historical analysis and system-level understanding rather than live trip planning.",
    },
]
