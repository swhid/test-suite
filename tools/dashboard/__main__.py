#!/usr/bin/env python3
"""CLI entry point for dashboard generator."""

import argparse
from pathlib import Path
from .generator import DashboardGenerator


def main():
    parser = argparse.ArgumentParser(description="Generate dashboard from test results")
    parser.add_argument('--site', required=True, help='Site directory')
    parser.add_argument('--data', required=True, help='Data directory (contains index.json)')
    parser.add_argument('--artifacts', help='Artifacts directory (contains results.html files)')
    parser.add_argument('--views', nargs='+', help='Views to generate (default: all)')
    
    args = parser.parse_args()
    
    generator = DashboardGenerator(
        site_dir=Path(args.site),
        data_dir=Path(args.data),
        artifacts_dir=Path(args.artifacts) if args.artifacts else None
    )
    
    generator.generate(views=args.views)
    return 0


if __name__ == '__main__':
    exit(main())

