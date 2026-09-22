"""Static configuration shared by services, routes, templates, and (via APP_META) the browser."""

DAYS_OF_WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
EMPLOYMENT_TYPES = ("Full-Time", "Part-Time")

DEFAULT_OPERATING_HOURS = {day: {"open": "09:00", "close": "21:00"} for day in DAYS_OF_WEEK}

# A shift at or above the threshold has an unpaid break deducted from its paid time.
BREAK_THRESHOLD_MINUTES = 300
BREAK_DURATION_MINUTES = 30

# Shift times snap to this grid; a shift can never be shorter than the minimum.
SLOT_MINUTES = 15
MINIMUM_SHIFT_MINUTES = 30

# Distinguishable defaults; a new employee without a chosen color takes the first unused one.
EMPLOYEE_COLOR_PALETTE = (
    "#E07A5F", "#3D8BBD", "#5B9A6A", "#B5678E", "#D9A23B",
    "#5F6FB0", "#C25E4A", "#3F9E93", "#8A6FBF", "#9D8A3C",
    "#D97A9A", "#4A8F5C", "#B36B3F", "#5A82C0", "#A45DB0",
)

# Seeded into the positions table on first run. The table is the source of truth
# afterwards; this only fills gaps.
DEFAULT_POSITIONS = (
    {"name": "Cashier", "label": "Cashier", "color": "#4B9CD3", "sort_order": 1},
    {"name": "Merchandiser", "label": "Merchandiser", "color": "#7A9E52", "sort_order": 2},
    {"name": "Cosmetics", "label": "Cosmetics", "color": "#C875A5", "sort_order": 3},
    {"name": "Food", "label": "Food", "color": "#E07A5F", "sort_order": 4},
    {"name": "Management", "label": "Management + Supervisor", "color": "#53685D", "sort_order": 5},
)

# Extra URL slugs that resolve to a position, e.g. /schedule/supervisor.
POSITION_SLUG_ALIASES = {"supervisor": "Management"}
