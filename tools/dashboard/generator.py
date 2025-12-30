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
        platform_stats = data.get('platform_stats', {})
        total_results = data.get('total_results', 0)
        total_passed = data.get('total_passed', 0)
        total_failed = data.get('total_failed', 0)
        total_skipped = data.get('total_skipped', 0)
        
        context = {
            'title': 'Dashboard',
            'total_runs': data.get('total_runs', 0),
            'total_tests': data.get('total_tests', 0),
            'total_results': total_results,
            'total_passed': total_passed,
            'total_failed': total_failed,
            'total_skipped': total_skipped,
            'overall_pass_rate': round(data.get('overall_pass_rate', 0), 2),
            'overall_fail_rate': round(data.get('overall_fail_rate', 0), 2),
            'overall_skip_rate': round(data.get('overall_skip_rate', 0), 2),
            'implementations': ', '.join(data.get('implementations', [])),
            'runs': data.get('runs', []),
            'platform_stats': platform_stats,
        }
        
        # Determine pass rate class
        pass_rate = context['overall_pass_rate']
        if pass_rate >= 80:
            context['pass_rate_class'] = 'success'
        elif pass_rate >= 50:
            context['pass_rate_class'] = 'warning'
        else:
            context['pass_rate_class'] = 'danger'
        
        # Generate platform breakdown HTML
        platform_breakdown_html = []
        if platform_stats:
            for platform, stats in sorted(platform_stats.items()):
                total = stats.get('total', 0)
                passed = stats.get('passed', 0)
                failed = stats.get('failed', 0)
                skipped = stats.get('skipped', 0)
                pass_rate = stats.get('pass_rate', 0.0)
                fail_rate = stats.get('fail_rate', 0.0)
                skip_rate = stats.get('skip_rate', 0.0)
                
                # Determine pass rate class for this platform
                if pass_rate >= 80:
                    platform_class = 'success'
                elif pass_rate >= 50:
                    platform_class = 'warning'
                else:
                    platform_class = 'danger'
                
                platform_breakdown_html.append(f"""
                    <div class="platform-card">
                        <div class="platform-header">
                            <h3>{platform}</h3>
                            <span class="badge badge-{platform_class}">{pass_rate:.1f}%</span>
                        </div>
                        <div class="platform-details">
                            <div class="platform-stat">
                                <span class="stat-label">Pass</span>
                                <span class="stat-value stat-pass">{pass_rate:.1f}%</span>
                                <span class="stat-count">({passed}/{total})</span>
                            </div>
                            <div class="platform-stat">
                                <span class="stat-label">Fail</span>
                                <span class="stat-value stat-fail">{fail_rate:.1f}%</span>
                                <span class="stat-count">({failed}/{total})</span>
                            </div>
                            <div class="platform-stat">
                                <span class="stat-label">Skip</span>
                                <span class="stat-value stat-skip">{skip_rate:.1f}%</span>
                                <span class="stat-count">({skipped}/{total})</span>
                            </div>
                        </div>
                    </div>
                """)
        else:
            platform_breakdown_html.append('<p class="text-muted">No platform data available</p>')
        
        context['platform_breakdown'] = '\n'.join(platform_breakdown_html) if platform_breakdown_html else ''
        
        # Generate implementation x platform matrix
        impl_platform_matrix = data.get('impl_platform_matrix', {})
        implementations = data.get('implementations', [])
        platforms = sorted(set(platform_stats.keys())) if platform_stats else []
        
        matrix_header = []
        matrix_rows = []
        if impl_platform_matrix and implementations and platforms:
            # Header row
            header_cells = ['<th>Implementation</th>']
            for platform in platforms:
                header_cells.append(f'<th>{platform}</th>')
            matrix_header.append(f'<tr>{"".join(header_cells)}</tr>')
            
            # Data rows
            for impl_id in sorted(implementations):
                row_cells = [f'<td><strong>{impl_id}</strong></td>']
                for platform in platforms:
                    cell_data = impl_platform_matrix.get(impl_id, {}).get(platform, {})
                    passed = cell_data.get('passed', 0)
                    failed = cell_data.get('failed', 0)
                    skipped = cell_data.get('skipped', 0)
                    total = cell_data.get('total', 0)
                    pass_rate = cell_data.get('pass_rate', 0.0)
                    fail_rate = cell_data.get('fail_rate', 0.0)
                    skip_rate = cell_data.get('skip_rate', 0.0)
                    
                    # Determine cell class based on pass rate
                    if total == 0:
                        cell_class = 'matrix-cell-empty'
                        cell_content = '<span class="text-muted">—</span>'
                    elif pass_rate >= 80:
                        cell_class = 'matrix-cell-success'
                        cell_content = f'''
                            <div class="matrix-cell-content">
                                <div class="matrix-pass">✓ {pass_rate:.1f}%</div>
                                <div class="matrix-details">
                                    <small>{passed}/{total} pass</small>
                                    {f'<small class="matrix-fail">, {failed} fail</small>' if failed > 0 else ''}
                                    {f'<small class="matrix-skip">, {skipped} skip</small>' if skipped > 0 else ''}
                                </div>
                            </div>
                        '''
                    elif pass_rate >= 50:
                        cell_class = 'matrix-cell-warning'
                        cell_content = f'''
                            <div class="matrix-cell-content">
                                <div class="matrix-pass">✓ {pass_rate:.1f}%</div>
                                <div class="matrix-details">
                                    <small>{passed}/{total} pass</small>
                                    {f'<small class="matrix-fail">, {failed} fail</small>' if failed > 0 else ''}
                                    {f'<small class="matrix-skip">, {skipped} skip</small>' if skipped > 0 else ''}
                                </div>
                            </div>
                        '''
                    else:
                        cell_class = 'matrix-cell-danger'
                        cell_content = f'''
                            <div class="matrix-cell-content">
                                <div class="matrix-pass">✓ {pass_rate:.1f}%</div>
                                <div class="matrix-details">
                                    <small>{passed}/{total} pass</small>
                                    {f'<small class="matrix-fail">, {failed} fail</small>' if failed > 0 else ''}
                                    {f'<small class="matrix-skip">, {skipped} skip</small>' if skipped > 0 else ''}
                                </div>
                            </div>
                        '''
                    
                    row_cells.append(f'<td class="{cell_class}">{cell_content}</td>')
                matrix_rows.append(f'<tr>{"".join(row_cells)}</tr>')
        
        context['matrix_header'] = '\n'.join(matrix_header) if matrix_header else ''
        context['matrix_rows'] = '\n'.join(matrix_rows) if matrix_rows else '<tr><td colspan="100%">No data available</td></tr>'
        
        # Generate runs table rows
        runs_rows = []
        for run in context['runs']:
            run_pass_class = 'success' if run['pass_rate'] >= 80 else 'warning' if run['pass_rate'] >= 50 else 'danger'
            commit_short = run['commit'][:7] if run['commit'] != 'unknown' else 'unknown'
            created_at = run['created_at'][:19] if len(run['created_at']) > 19 else run['created_at']
            
            # Get platform name (default to "Unknown" for backward compatibility)
            platform = run.get('platform', 'Unknown')
            
            # Get per-platform stats
            passed = run.get('passed', 0)
            failed = run.get('failed', 0)
            skipped = run.get('skipped', 0)
            total = run.get('total', 0)
            
            # Calculate rates
            pass_rate = run.get('pass_rate', 0.0)
            fail_rate = run.get('failed_rate', 0.0)
            skip_rate = run.get('skipped_rate', 0.0)
            
            # Format platform breakdown
            if total > 0:
                platform_breakdown = f"""
                        <div class="platform-stats">
                            <span class="stat-pass">✓ {pass_rate:.1f}%</span>
                            <span class="stat-fail">✗ {fail_rate:.1f}%</span>
                            <span class="stat-skip">⊘ {skip_rate:.1f}%</span>
                        </div>
                        <div class="platform-counts">
                            <small>({passed}/{total} pass, {failed} fail, {skipped} skip)</small>
                        </div>
                    """
            else:
                platform_breakdown = '<span class="text-muted">No data</span>'
            
            runs_rows.append(f"""
                <tr>
                    <td><code>{run['id']}</code></td>
                    <td>{run['branch']}</td>
                    <td><code>{commit_short}</code></td>
                    <td><strong>{platform}</strong></td>
                    <td>
                        <span class="badge badge-{run_pass_class}">{run['pass_rate']:.1f}%</span>
                        {platform_breakdown}
                    </td>
                    <td>{created_at}</td>
                    <td>
                        <a href="data/runs/{run['id']}.json">JSON</a>
                    </td>
                </tr>
            """)
        context['runs_rows'] = '\n'.join(runs_rows) if runs_rows else '<tr><td colspan="7">No runs available</td></tr>'
        
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

