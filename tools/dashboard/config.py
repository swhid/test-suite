"""Configuration for dashboard generator."""

from pathlib import Path

# Base directory for dashboard module
DASHBOARD_DIR = Path(__file__).parent

# Default configuration
DASHBOARD_CONFIG = {
    'site_name': 'SWHID Test Results Dashboard',
    'views': ['index'],
    'copy_artifact_html': True,
    'template_dir': DASHBOARD_DIR / 'templates',
    'assets_dir': DASHBOARD_DIR / 'assets',
}

