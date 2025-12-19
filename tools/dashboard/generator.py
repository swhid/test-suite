#!/usr/bin/env python3
"""Dashboard generator for SWHID test results."""

import json
import shutil
from pathlib import Path
from string import Template
from typing import Dict, Any, List, Optional

from .config import DASHBOARD_CONFIG


class DashboardGenerator:
    """Generate dashboard HTML from test results data."""
    
    def __init__(self, site_dir: Path, data_dir: Path, artifacts_dir: Optional[Path] = None):
        self.site_dir = Path(site_dir)
        self.data_dir = Path(data_dir)
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.assets_dir = self.site_dir / "assets"
        self.template_dir = DASHBOARD_CONFIG['template_dir']
    
    def generate(self, views: Optional[List[str]] = None) -> None:
        """Generate dashboard views."""
        views = views or DASHBOARD_CONFIG['views']
        
        # Ensure site directory exists
        self.site_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy assets
        self._copy_assets()
        
        # Copy artifact HTML files
        artifact_files = []
        if DASHBOARD_CONFIG['copy_artifact_html'] and self.artifacts_dir:
            artifact_files = self._copy_artifact_html()
        
        # Generate views
        if 'index' in views:
            self._generate_index(artifact_files)
    
    def _copy_assets(self) -> None:
        """Copy CSS/JS assets to site directory."""
        source_assets = DASHBOARD_CONFIG['assets_dir']
        if source_assets.exists():
            if self.assets_dir.exists():
                shutil.rmtree(self.assets_dir)
            shutil.copytree(source_assets, self.assets_dir)
            print(f"Copied assets to {self.assets_dir}")
    
    def _copy_artifact_html(self) -> List[str]:
        """Copy HTML files from artifacts to site."""
        if not self.artifacts_dir or not self.artifacts_dir.exists():
            return []
        
        copied = []
        for html_file in self.artifacts_dir.rglob("results.html"):
            artifact_name = html_file.parent.name
            dest = self.site_dir / f"{artifact_name}.html"
            shutil.copy2(html_file, dest)
            copied.append(artifact_name)
            print(f"Copied {html_file} to {dest}")
        
        return copied
    
    def _generate_index(self, artifact_files: List[str]) -> None:
        """Generate main index.html."""
        # Load data
        index_file = self.data_dir / "index.json"
        if not index_file.exists():
            print(f"Warning: {index_file} not found, creating empty dashboard")
            data = {}
        else:
            with open(index_file) as f:
                data = json.load(f)
        
        # Load templates
        base_template = self._load_template('base.html')
        index_template = self._load_template('index.html')
        
        # Prepare context
        context = {
            'title': 'Dashboard',
            'total_runs': data.get('total_runs', 0),
            'total_tests': data.get('total_tests', 0),
            'overall_pass_rate': data.get('overall_pass_rate', 0),
            'implementations': ', '.join(data.get('implementations', [])),
            'runs': data.get('runs', []),
        }
        
        # Determine pass rate class
        pass_rate = context['overall_pass_rate']
        if pass_rate >= 80:
            context['pass_rate_class'] = 'success'
        elif pass_rate >= 50:
            context['pass_rate_class'] = 'warning'
        else:
            context['pass_rate_class'] = 'danger'
        
        # Generate runs table rows
        runs_rows = []
        for run in context['runs']:
            run_pass_class = 'success' if run['pass_rate'] >= 80 else 'warning' if run['pass_rate'] >= 50 else 'danger'
            commit_short = run['commit'][:7] if run['commit'] != 'unknown' else 'unknown'
            created_at = run['created_at'][:19] if len(run['created_at']) > 19 else run['created_at']
            runs_rows.append(f"""
                <tr>
                    <td><code>{run['id']}</code></td>
                    <td>{run['branch']}</td>
                    <td><code>{commit_short}</code></td>
                    <td><span class="badge badge-{run_pass_class}">{run['pass_rate']}%</span></td>
                    <td>{created_at}</td>
                    <td>
                        <a href="data/runs/{run['id']}.json">JSON</a>
                    </td>
                </tr>
            """)
        context['runs_rows'] = '\n'.join(runs_rows) if runs_rows else '<tr><td colspan="6">No runs available</td></tr>'
        
        # Generate artifact HTML section
        if artifact_files:
            artifact_links = '\n'.join([
                f'<li><a href="{name}.html">{name}</a></li>'
                for name in artifact_files
            ])
            context['artifact_html_section'] = f"""
            <section class="artifact-html">
                <h2>Detailed Results (HTML Tables)</h2>
                <ul>{artifact_links}</ul>
            </section>
            """
        else:
            context['artifact_html_section'] = ''
        
        # Render base template
        base_html = base_template.substitute(
            title=context['title'],
            content=index_template.substitute(**context)
        )
        
        # Write to site
        output_file = self.site_dir / "index.html"
        output_file.write_text(base_html)
        print(f"Generated {output_file}")
    
    def _load_template(self, name: str) -> Template:
        """Load a template file."""
        template_file = self.template_dir / name
        if not template_file.exists():
            raise FileNotFoundError(f"Template not found: {template_file}")
        with open(template_file) as f:
            return Template(f.read())

