#!/usr/bin/env python3
"""
Generate a color-coded HTML table from SWHID harness test results.

This script reads the JSON results file and creates an HTML table showing:
- One row per test case
- One column per implementation
- Color-coded cells indicating test outcomes:
  - SKIP: Test was skipped (gray)
  - CONFORMANT: PASS with matching expected SWHID (green)
  - NON-CONFORMANT: PASS but wrong SWHID, or FAIL with expected (red)
  - EXECUTED_OK: PASS but no expected to compare (blue)
  - EXECUTED_ERROR: FAIL without expected (yellow/orange)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from html import escape


class VariantRegistry:
    """Registry for SWHID variants (version + hash algorithm + serialization format)."""
    
    def __init__(self):
        self.variants: Dict[str, Dict] = {}
        self._register_defaults()
    
    def _register_defaults(self):
        """Register default v1 and v2 variants."""
        # v1 SHA1 hex (legacy)
        self.register_variant('v1_sha1_hex', {
            'version': 1,
            'hash_algo': 'sha1',
            'serialization': 'hex',
            'expected_key': 'swhid',  # Legacy key name
            'swhid_prefix': 'swh:1:',
            'hash_length': 40,  # SHA1 hex length (160 bits = 20 bytes = 40 hex chars)
        })
        
        # v2 SHA256 hex (current)
        self.register_variant('v2_sha256_hex', {
            'version': 2,
            'hash_algo': 'sha256',
            'serialization': 'hex',
            'expected_key': 'expected_swhid_sha256',
            'swhid_prefix': 'swh:2:',
            'hash_length': 64,  # SHA256 hex length (256 bits = 32 bytes = 64 hex chars)
        })
    
    def register_variant(self, variant_id: str, config: Dict):
        """Register a new variant.
        
        Args:
            variant_id: Identifier like 'v2_sha256_hex'
            config: Dictionary with keys: version, hash_algo, serialization, 
                   expected_key, swhid_prefix, hash_length
        """
        required_keys = ['version', 'hash_algo', 'serialization', 'expected_key', 
                        'swhid_prefix', 'hash_length']
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Variant config missing required key: {key}")
        
        self.variants[variant_id] = config.copy()
    
    def get_variant_for_swhid(self, swhid: str) -> Optional[str]:
        """Detect variant from SWHID string format.
        
        Args:
            swhid: SWHID string like 'swh:1:cnt:abc...' or 'swh:2:cnt:def...'
        
        Returns:
            Variant ID like 'v1_sha1_hex' or 'v2_sha256_hex', or None if not detected
        """
        if not swhid or not swhid.startswith('swh:'):
            return None
        
        parts = swhid.split(':')
        if len(parts) < 4:
            return None
        
        version_str = parts[1]  # "1", "2", etc.
        try:
            version = int(version_str)
        except ValueError:
            return None
        
        hash_part = parts[-1]  # Last part is the hash
        
        # Detect serialization format first (needed for disambiguation)
        serialization = self._detect_serialization_format(hash_part)
        
        # Detect hash algorithm from length, using serialization to disambiguate
        hash_length = len(hash_part)
        hash_algo = self._detect_hash_algo_from_length(hash_length, serialization)
        
        # Build variant ID
        variant_id = f"v{version}_{hash_algo}_{serialization}"
        
        # Check if this variant is registered
        if variant_id in self.variants:
            return variant_id
        
        # If not registered, try to find a matching variant by version and characteristics
        # This allows detection of unknown variants for future extensibility
        return variant_id
    
    def _detect_hash_algo_from_length(self, hash_length: int, serialization: Optional[str] = None) -> str:
        """Detect hash algorithm from hash length, using serialization to disambiguate.
        
        Some lengths are ambiguous (e.g., 40 chars could be SHA1 hex or SHA256 base85).
        When serialization is provided, it's used to resolve these ambiguities.
        
        Length reference:
        - Hex: SHA1=40, SHA256=64, SHA512=128
        - Base64 (with padding): SHA1=27, SHA256=44, SHA512=88
        - Base64 (no padding): SHA1=27, SHA256=43, SHA512=86
        - Base85: SHA1=25, SHA256=40, SHA512=50
        - Base32: SHA1=32, SHA256=52, SHA512=104
        
        Args:
            hash_length: Length of hash string
            serialization: Optional serialization format (hex, base64, base32, base85)
                Used to disambiguate ambiguous lengths
        
        Returns:
            Hash algorithm name (sha1, sha256, sha512) or 'unknown'
        """
        # Handle ambiguous lengths using serialization
        if serialization:
            if hash_length == 40:
                if serialization == 'hex':
                    return 'sha1'
                elif serialization == 'base85':
                    return 'sha256'
            # Add other ambiguous cases as needed
        
        # Direct length mappings (non-ambiguous)
        # Note: 40 is ambiguous (SHA1 hex or SHA256 base85), so it's handled above
        length_to_algo = {
            # Hex (non-ambiguous lengths)
            64: 'sha256',    # SHA256 hex
            128: 'sha512',   # SHA512 hex
            
            # Base64 (with padding)
            27: 'sha1',      # SHA1 base64
            44: 'sha256',    # SHA256 base64
            88: 'sha512',    # SHA512 base64
            
            # Base64 (without padding)
            43: 'sha256',    # SHA256 base64 (no padding)
            86: 'sha512',   # SHA512 base64 (no padding)
            
            # Base85 (non-ambiguous lengths)
            25: 'sha1',      # SHA1 base85
            50: 'sha512',    # SHA512 base85
            
            # Base32
            32: 'sha1',      # SHA1 base32
            52: 'sha256',    # SHA256 base32
            104: 'sha512',   # SHA512 base32
        }
        
        # Check non-ambiguous mappings first
        if hash_length in length_to_algo:
            return length_to_algo[hash_length]
        
        # Handle ambiguous length 40 (SHA1 hex or SHA256 base85)
        # Default to SHA1 hex if serialization not provided (backward compatibility)
        if hash_length == 40:
            return 'sha1'  # Default assumption for backward compatibility
        
        return 'unknown'
    
    def _detect_serialization_format(self, hash_part: str) -> str:
        """Detect serialization format from hash character set.
        
        Detection order matters: hex (most restrictive) → base85 → base32 → base64 (most permissive).
        Base85 must be checked before base64 since its character set is a subset of base64.
        
        Args:
            hash_part: The hash portion of the SWHID
        
        Returns:
            'hex', 'base85', 'base32', 'base64', or 'unknown'
        """
        # Hex: only 0-9, a-f (most restrictive)
        if re.match(r'^[0-9a-f]+$', hash_part):
            return 'hex'
        
        # Base85: ASCII characters 33-117 (! through u)
        # Must check before base64 since base85 charset is subset of base64
        if re.match(r'^[!-u]+$', hash_part):
            return 'base85'
        
        # Base32: A-Z, 2-7, = (padding), no lowercase, no 0, 1, 8, 9
        if re.match(r'^[A-Z2-7=]+$', hash_part) and not re.search(r'[01]', hash_part):
            return 'base32'
        
        # Base64: A-Z, a-z, 0-9, +, /, = (padding) (most permissive)
        if re.match(r'^[A-Za-z0-9+/=]+$', hash_part):
            return 'base64'
        
        return 'unknown'
    
    def get_expected_key(self, variant_id: str) -> Optional[str]:
        """Get expected value key for a variant.
        
        Args:
            variant_id: Variant identifier like 'v1_sha1_hex'
        
        Returns:
            Expected key like 'swhid' or 'expected_swhid_sha256', or None
        """
        variant = self.variants.get(variant_id)
        return variant.get('expected_key') if variant else None
    
    def list_variants(self) -> List[str]:
        """List all registered variant IDs."""
        return sorted(self.variants.keys())
    
    def get_variant_config(self, variant_id: str) -> Optional[Dict]:
        """Get full configuration for a variant."""
        return self.variants.get(variant_id)


def detect_variants_in_results(results_data: Dict, registry: VariantRegistry) -> Set[str]:
    """Find all variants present in test results.
    
    Args:
        results_data: Results dictionary from JSON file
        registry: VariantRegistry instance
    
    Returns:
        Set of variant IDs found in the results
    """
    variants = set()
    for test in results_data.get('tests', []):
        for result in test.get('results', []):
            swhid = result.get('swhid')
            if swhid:
                variant = registry.get_variant_for_swhid(swhid)
                if variant:
                    variants.add(variant)
    return variants


def filter_results_by_variant(results_data: Dict, variant_id: str, 
                              registry: VariantRegistry) -> Dict:
    """Filter results to only include specified variant.
    
    Args:
        results_data: Full results dictionary
        variant_id: Variant identifier like 'v1_sha1_hex'
        registry: VariantRegistry instance
    
    Returns:
        Filtered results dictionary with only tests/results for the specified variant
    """
    variant_config = registry.get_variant_config(variant_id)
    if not variant_config:
        raise ValueError(f"Unknown variant: {variant_id}")
    
    filtered_tests = []
    
    for test in results_data.get('tests', []):
        filtered_results = []
        for result in test.get('results', []):
            swhid = result.get('swhid', '')
            if swhid.startswith(variant_config['swhid_prefix']):
                # Check hash length matches
                hash_part = swhid.split(':')[-1]
                if len(hash_part) == variant_config['hash_length']:
                    # Additional check: verify serialization format matches
                    detected_serialization = registry._detect_serialization_format(hash_part)
                    if detected_serialization == variant_config['serialization']:
                        filtered_results.append(result)
        
        if filtered_results:
            # Create filtered test with variant-appropriate expected
            expected_key = variant_config['expected_key']
            expected = test.get('expected', {})
            
            # Get the expected value for this variant
            expected_value = expected.get(expected_key)
            
            # Create filtered expected dict with the variant-specific key
            filtered_expected = {expected_key: expected_value}
            
            filtered_test = {
                'id': test['id'],
                'category': test.get('category'),
                'payload_ref': test.get('payload_ref'),
                'expected': filtered_expected,
                'results': filtered_results
            }
            filtered_tests.append(filtered_test)
    
    return {
        'run': results_data.get('run'),
        'implementations': results_data.get('implementations'),
        'tests': filtered_tests
    }


def determine_cell_status(result: Dict, expected_swhid: Optional[str]) -> Tuple[str, str, Optional[str]]:
    """
    Determine the status, color, and content for a test result cell.
    
    Returns:
        Tuple of (status_label, html_color, cell_content)
    """
    status = result.get('status', 'UNKNOWN')
    swhid = result.get('swhid')
    error = result.get('error')
    
    if status == 'SKIPPED':
        return ('SKIP', '#888888', '')  # Gray - color only, no text
    
    if status == 'PASS':
        if expected_swhid:
            if swhid == expected_swhid:
                return ('CONFORMANT', '#90EE90', '')  # Light green - color only, no text
            else:
                # Non-conformant: show full wrong SWHID
                return ('NON-CONFORMANT', '#FF6B6B', swhid)  # Light red - full SWHID
        else:
            return ('EXECUTED_OK', '#87CEEB', '')  # Sky blue - color only
    
    if status == 'FAIL':
        if expected_swhid:
            # Non-conformant: show full wrong SWHID if available
            if swhid:
                return ('NON-CONFORMANT', '#FF6B6B', swhid)  # Full SWHID for discrepancy
            else:
                return ('NON-CONFORMANT', '#FF6B6B', '')  # Red - color only, no text
        else:
            return ('EXECUTED_ERROR', '#FFD700', '')  # Gold - color only, no text
    
    return ('UNKNOWN', '#FFFFFF', 'Unknown')


def get_error_summary(error: Optional[Dict]) -> str:
    """Extract a concise error summary from error dict."""
    if not error:
        return ''
    
    error_code = error.get('code', '')
    error_message = error.get('message', '')
    
    if error_code:
        return f"{error_code}: {error_message}"
    return error_message


def create_html_table(results_data: Dict, variant_config: Optional[Dict] = None) -> str:
    """Create an HTML table with color-coded results.
    
    Args:
        results_data: Results dictionary with tests and implementations
        variant_config: Optional variant configuration dict for variant-specific display
    """
    implementations = sorted([impl['id'] for impl in results_data.get('implementations', [])])
    tests = results_data.get('tests', [])
    
    if not implementations or not tests:
        return "<p>No data to display</p>"
    
    # Determine variant info for title
    if variant_config:
        variant_title = f"v{variant_config['version']} {variant_config['hash_algo'].upper()} {variant_config['serialization']}"
        page_title = f"SWHID Test Results - {variant_title}"
    else:
        page_title = "SWHID Test Results"
        variant_title = None
    
    # Start HTML
    html = ['<!DOCTYPE html>', '<html>', '<head>', '<meta charset="UTF-8">']
    html.append(f'<title>{escape(page_title)}</title>')
    html.append('<style>')
    html.append('''
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #333;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            background-color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        th {
            background-color: #4CAF50;
            color: white;
            padding: 10px;
            text-align: left;
            font-weight: bold;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        td {
            padding: 4px 8px;
            border: 1px solid #ddd;
            font-size: 10px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 150px;
            min-width: 80px;
        }
        td.test-name {
            font-weight: bold;
            background-color: #f9f9f9;
            max-width: 300px;
        }
        td.expected {
            font-family: monospace;
            font-size: 9px;
            max-width: 200px;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        .legend {
            margin: 20px 0;
            padding: 15px;
            background-color: white;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .legend-item {
            display: inline-block;
            margin: 5px 15px;
        }
        .color-box {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 1px solid #ccc;
            vertical-align: middle;
            margin-right: 5px;
        }
        .tooltip {
            position: relative;
            cursor: help;
        }
        .tooltip:hover::after {
            content: attr(title);
            position: absolute;
            left: 100%;
            top: 0;
            background-color: #333;
            color: white;
            padding: 5px 10px;
            border-radius: 3px;
            white-space: pre-wrap;
            z-index: 1000;
            min-width: 200px;
            font-size: 11px;
        }
    ''')
    html.append('</style>')
    html.append('</head>')
    html.append('<body>')
    html.append(f'<h1>{escape(page_title)}</h1>')
    
    # Add variant info if available
    if variant_title:
        html.append(f'<p><strong>Variant:</strong> {escape(variant_title)}</p>')
    
    # Add legend
    html.append('<div class="legend">')
    html.append('<strong>Legend:</strong>')
    html.append('<div class="legend-item"><span class="color-box" style="background-color: #888888;"></span>SKIP - Test was skipped</div>')
    html.append('<div class="legend-item"><span class="color-box" style="background-color: #90EE90;"></span>CONFORMANT - PASS with matching expected SWHID</div>')
    html.append('<div class="legend-item"><span class="color-box" style="background-color: #FF6B6B;"></span>NON-CONFORMANT - Wrong SWHID or FAIL with expected</div>')
    html.append('<div class="legend-item"><span class="color-box" style="background-color: #87CEEB;"></span>EXECUTED_OK - PASS but no expected to compare</div>')
    html.append('<div class="legend-item"><span class="color-box" style="background-color: #FFD700;"></span>EXECUTED_ERROR - FAIL without expected</div>')
    html.append('</div>')
    
    # Start table
    html.append('<table>')
    html.append('<thead>')
    html.append('<tr>')
    html.append('<th>Test Case</th>')
    html.append('<th>Expected SWHID</th>')
    for impl in implementations:
        html.append(f'<th>{escape(impl)}</th>')
    html.append('</tr>')
    html.append('</thead>')
    html.append('<tbody>')
    
    # Add rows
    for test in tests:
        test_id = test.get('id', 'unknown')
        expected = test.get('expected', {})
        
        # Get expected SWHID - use variant-specific key if available
        if variant_config:
            expected_key = variant_config.get('expected_key', 'swhid')
            expected_swhid = expected.get(expected_key)
        else:
            # Fallback: try 'swhid' first, then 'expected_swhid_sha256'
            expected_swhid = expected.get('swhid') or expected.get('expected_swhid_sha256')
        
        results = test.get('results', [])
        
        result_map = {r['implementation']: r for r in results}
        
        html.append('<tr>')
        
        # Test name
        html.append(f'<td class="test-name">{escape(test_id)}</td>')
        
        # Expected SWHID
        expected_display = escape(expected_swhid) if expected_swhid else ''
        html.append(f'<td class="expected">{expected_display}</td>')
        
        # Results per implementation
        for impl in implementations:
            result = result_map.get(impl)
            if not result:
                html.append('<td style="background-color: #f0f0f0;">N/A</td>')
            else:
                status_label, color, content = determine_cell_status(result, expected_swhid)
                
                # Build tooltip with full details
                tooltip_parts = [f"Status: {status_label}"]
                if result.get('swhid'):
                    tooltip_parts.append(f"SWHID: {result.get('swhid')}")
                if expected_swhid:
                    tooltip_parts.append(f"Expected: {expected_swhid}")
                if result.get('error'):
                    error_summary = get_error_summary(result.get('error'))
                    tooltip_parts.append(f"Error: {error_summary}")
                
                tooltip = '\n'.join(tooltip_parts)
                
                # Display content (for non-conformant, content already contains full SWHID)
                # For conformant/executed_ok, content is empty (color only)
                display_content = escape(str(content)).replace('\n', '<br>') if content else ''
                
                html.append(f'<td class="tooltip" style="background-color: {color};" title="{escape(tooltip)}">{display_content}</td>')
        
        html.append('</tr>')
    
    html.append('</tbody>')
    html.append('</table>')
    html.append('</body>')
    html.append('</html>')
    
    return '\n'.join(html)


def generate_table_for_variant(results_data: Dict, variant_id: str, 
                               output_dir: Path, registry: VariantRegistry) -> Path:
    """Generate HTML table for specific variant.
    
    Args:
        results_data: Full results dictionary
        variant_id: Variant identifier like 'v1_sha1_hex'
        output_dir: Directory to write output file
        registry: VariantRegistry instance
    
    Returns:
        Path to generated HTML file
    """
    variant_config = registry.get_variant_config(variant_id)
    if not variant_config:
        raise ValueError(f"Unknown variant: {variant_id}")
    
    # Filter results for this variant
    filtered_data = filter_results_by_variant(results_data, variant_id, registry)
    
    # Generate HTML table
    html_content = create_html_table(filtered_data, variant_config)
    
    # Save to variant-specific file
    output_file = output_dir / f"results_{variant_id}.html"
    output_file.write_text(html_content, encoding='utf-8')
    
    return output_file


def generate_all_tables(results_data: Dict, output_dir: Path, 
                       registry: VariantRegistry) -> List[Path]:
    """Generate separate tables for all detected variants.
    
    Args:
        results_data: Full results dictionary
        output_dir: Directory to write output files
        registry: VariantRegistry instance
    
    Returns:
        List of paths to generated HTML files
    """
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Detect all variants in results
    variants = detect_variants_in_results(results_data, registry)
    
    if not variants:
        # No variants detected - generate single table (backward compatibility)
        output_file = output_dir / "results.html"
        html_content = create_html_table(results_data)
        output_file.write_text(html_content, encoding='utf-8')
        return [output_file]
    
    output_files = []
    
    # Generate table for each variant
    for variant_id in sorted(variants):
        output_file = generate_table_for_variant(
            results_data, variant_id, output_dir, registry
        )
        output_files.append(output_file)
    
    # Generate index page
    index_file = generate_index_page(variants, output_dir, results_data, registry)
    output_files.append(index_file)
    
    return output_files


def generate_index_page(variants: Set[str], output_dir: Path, 
                       results_data: Dict, registry: VariantRegistry) -> Path:
    """Generate index page linking to all variant tables.
    
    Args:
        variants: Set of variant IDs found in results
        output_dir: Directory to write index file
        results_data: Full results dictionary (for statistics)
        registry: VariantRegistry instance
    
    Returns:
        Path to generated index.html file
    """
    # Calculate statistics per variant
    variant_stats = {}
    for variant_id in variants:
        filtered_data = filter_results_by_variant(results_data, variant_id, registry)
        tests = filtered_data.get('tests', [])
        
        total_tests = len(tests)
        total_results = sum(len(t.get('results', [])) for t in tests)
        passed = sum(1 for t in tests for r in t.get('results', []) 
                    if r.get('status') == 'PASS')
        failed = sum(1 for t in tests for r in t.get('results', []) 
                    if r.get('status') == 'FAIL')
        skipped = sum(1 for t in tests for r in t.get('results', []) 
                     if r.get('status') == 'SKIPPED')
        
        pass_rate = round((passed / total_results * 100) if total_results > 0 else 0, 1)
        
        variant_config = registry.get_variant_config(variant_id)
        variant_stats[variant_id] = {
            'total_tests': total_tests,
            'total_results': total_results,
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
            'pass_rate': pass_rate,
            'config': variant_config,
        }
    
    # Generate HTML
    html = ['<!DOCTYPE html>', '<html>', '<head>', '<meta charset="UTF-8">']
    html.append('<title>SWHID Test Results - All Variants</title>')
    html.append('<style>')
    html.append('''
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #333;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            background-color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-top: 20px;
        }
        th {
            background-color: #4CAF50;
            color: white;
            padding: 10px;
            text-align: left;
            font-weight: bold;
        }
        td {
            padding: 8px;
            border: 1px solid #ddd;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        .pass-rate {
            font-weight: bold;
        }
        .pass-rate.high {
            color: #4CAF50;
        }
        .pass-rate.medium {
            color: #FF9800;
        }
        .pass-rate.low {
            color: #F44336;
        }
        a {
            color: #2196F3;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
    ''')
    html.append('</style>')
    html.append('</head>')
    html.append('<body>')
    html.append('<h1>SWHID Test Results - All Variants</h1>')
    html.append(f'<p>Found {len(variants)} variant(s) in test results.</p>')
    
    # Start table
    html.append('<table>')
    html.append('<thead>')
    html.append('<tr>')
    html.append('<th>Variant</th>')
    html.append('<th>Version</th>')
    html.append('<th>Hash Algorithm</th>')
    html.append('<th>Serialization</th>')
    html.append('<th>Tests</th>')
    html.append('<th>Results</th>')
    html.append('<th>Passed</th>')
    html.append('<th>Failed</th>')
    html.append('<th>Pass Rate</th>')
    html.append('<th>Link</th>')
    html.append('</tr>')
    html.append('</thead>')
    html.append('<tbody>')
    
    # Add rows for each variant
    for variant_id in sorted(variants):
        stats = variant_stats[variant_id]
        config = stats['config']
        
        # Determine pass rate class
        if stats['pass_rate'] >= 80:
            pass_rate_class = 'high'
        elif stats['pass_rate'] >= 50:
            pass_rate_class = 'medium'
        else:
            pass_rate_class = 'low'
        
        html.append('<tr>')
        html.append(f'<td><code>{escape(variant_id)}</code></td>')
        html.append(f'<td>{config["version"]}</td>')
        html.append(f'<td>{escape(config["hash_algo"].upper())}</td>')
        html.append(f'<td>{escape(config["serialization"])}</td>')
        html.append(f'<td>{stats["total_tests"]}</td>')
        html.append(f'<td>{stats["total_results"]}</td>')
        html.append(f'<td>{stats["passed"]}</td>')
        html.append(f'<td>{stats["failed"]}</td>')
        html.append(f'<td class="pass-rate {pass_rate_class}">{stats["pass_rate"]}%</td>')
        html.append(f'<td><a href="results_{escape(variant_id)}.html">View Table</a></td>')
        html.append('</tr>')
    
    html.append('</tbody>')
    html.append('</table>')
    html.append('</body>')
    html.append('</html>')
    
    # Write index file
    index_file = output_dir / "results_index.html"
    index_file.write_text('\n'.join(html), encoding='utf-8')
    
    return index_file


def create_table_rich(results_data: Dict):
    """Create a rich table with color-coded results."""
    console = Console()
    
    # Get implementations and tests
    implementations = sorted([impl['id'] for impl in results_data.get('implementations', [])])
    tests = results_data.get('tests', [])
    
    if not implementations:
        console.print("[red]No implementations found in results[/red]")
        return None
    
    if not tests:
        console.print("[red]No test cases found in results[/red]")
        return None
    
    # Create table
    table = Table(title="SWHID Test Results", show_header=True, header_style="bold magenta")
    
    # Add columns
    table.add_column("Test Case", style="cyan", no_wrap=True)
    table.add_column("Expected", style="dim", max_width=20)
    
    for impl in implementations:
        table.add_column(impl, justify="center", max_width=25)
    
    # Add rows
    for test in tests:
        test_id = test.get('id', 'unknown')
        expected = test.get('expected', {})
        expected_swhid = expected.get('swhid')
        results = test.get('results', [])
        
        # Create result map by implementation
        result_map = {r['implementation']: r for r in results}
        
        # Build row
        row = [test_id]
        
        # Expected SWHID (shortened)
        expected_display = expected_swhid[:20] + '...' if expected_swhid and len(expected_swhid) > 20 else (expected_swhid or '')
        row.append(expected_display)
        
        # Results per implementation
        for impl in implementations:
            result = result_map.get(impl)
            if not result:
                cell_text = Text('N/A', style='dim white')
            else:
                status_label, color = determine_cell_status(result, expected_swhid)
                swhid = result.get('swhid')
                error = result.get('error')
                
                # Build cell content
                cell_parts = [status_label]
                
                if swhid:
                    swhid_short = swhid[:15] + '...' if len(swhid) > 15 else swhid
                    cell_parts.append(f"\n{swhid_short}")
                
                if error:
                    error_summary = get_error_summary(error)
                    if error_summary:
                        cell_parts.append(f"\n{error_summary}")
                
                cell_text = Text('\n'.join(cell_parts), style=color)
            
            row.append(cell_text)
        
        table.add_row(*row)
    
    return table


def create_table_basic(results_data: Dict) -> None:
    """Create a basic text table (fallback when rich is not available)."""
    implementations = sorted([impl['id'] for impl in results_data.get('implementations', [])])
    tests = results_data.get('tests', [])
    
    if not implementations or not tests:
        print("No data to display")
        return
    
    # Print header
    header = f"{'Test Case':<40} {'Expected':<25}"
    for impl in implementations:
        header += f" {impl:<25}"
    print(header)
    print("=" * len(header))
    
    # Print rows
    for test in tests:
        test_id = test.get('id', 'unknown')
        expected = test.get('expected', {})
        expected_swhid = expected.get('swhid')
        results = test.get('results', [])
        
        result_map = {r['implementation']: r for r in results}
        
        expected_display = expected_swhid[:24] if expected_swhid else ''
        row = f"{test_id:<40} {expected_display:<25}"
        
        for impl in implementations:
            result = result_map.get(impl)
            if not result:
                cell = 'N/A'
            else:
                status_label, _ = determine_cell_status(result, expected_swhid)
                swhid = result.get('swhid', '')
                error = result.get('error')
                
                cell_parts = [status_label]
                if swhid:
                    cell_parts.append(swhid[:15])
                if error:
                    error_summary = get_error_summary(error)
                    if error_summary:
                        cell_parts.append(error_summary[:20])
                
                cell = ' | '.join(cell_parts)
            
            row += f" {cell:<25}"
        
        print(row)


def print_legend(console: Optional = None):
    """Print a legend explaining the color codes."""
    if console:
        console.print("\n[bold]Legend:[/bold]")
        console.print("[dim white]SKIP[/dim white] - Test was skipped")
        console.print("[green]CONFORMANT[/green] - PASS with matching expected SWHID")
        console.print("[red]NON-CONFORMANT[/red] - PASS but wrong SWHID, or FAIL with expected")
        console.print("[blue]EXECUTED_OK[/blue] - PASS but no expected to compare")
        console.print("[yellow]EXECUTED_ERROR[/yellow] - FAIL without expected")
    else:
        print("\nLegend:")
        print("SKIP - Test was skipped")
        print("CONFORMANT - PASS with matching expected SWHID")
        print("NON-CONFORMANT - PASS but wrong SWHID, or FAIL with expected")
        print("EXECUTED_OK - PASS but no expected to compare")
        print("EXECUTED_ERROR - FAIL without expected")


def main():
    parser = argparse.ArgumentParser(
        description='Generate a color-coded table from SWHID harness test results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate single table (backward compatible)
  %(prog)s results.json
  %(prog)s results.json --output results_table.html
  
  # Generate separate tables per variant
  %(prog)s results.json --output-dir output/
  
  # Generate table for specific variant only
  %(prog)s results.json --output-dir output/ --variant v2_sha256_hex
        """
    )
    parser.add_argument(
        'results_file',
        type=str,
        help='Path to the JSON results file (e.g., results.json)'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Output HTML file (default: results.html in same directory as input). '
             'Mutually exclusive with --output-dir.'
    )
    parser.add_argument(
        '--output-dir', '-d',
        type=str,
        help='Output directory for variant tables (generates separate table per variant). '
             'Mutually exclusive with --output.'
    )
    parser.add_argument(
        '--variant',
        type=str,
        help='Generate table for specific variant only (e.g., v1_sha1_hex, v2_sha256_hex). '
             'Requires --output-dir.'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.output and args.output_dir:
        print("Error: --output and --output-dir are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    
    if args.variant and not args.output_dir:
        print("Error: --variant requires --output-dir", file=sys.stderr)
        sys.exit(1)
    
    # Read results file
    results_path = Path(args.results_file)
    if not results_path.exists():
        print(f"Error: Results file not found: {results_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        with open(results_path, 'r') as f:
            results_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in results file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading results file: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Initialize registry
    registry = VariantRegistry()
    
    # Generate tables based on mode
    if args.output_dir:
        # Variant-based generation mode
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if args.variant:
            # Generate single variant table
            try:
                output_file = generate_table_for_variant(
                    results_data, args.variant, output_dir, registry
                )
                print(f"HTML table written to: {output_file}", file=sys.stderr)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Generate all variant tables
            output_files = generate_all_tables(results_data, output_dir, registry)
            print(f"Generated {len(output_files)} file(s):", file=sys.stderr)
            for output_file in output_files:
                print(f"  - {output_file}", file=sys.stderr)
    else:
        # Legacy single-table mode (backward compatible)
        html_content = create_html_table(results_data)
        
        if args.output:
            output_path = Path(args.output)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"HTML table written to: {output_path}", file=sys.stderr)
        else:
            # Default to results.html if no output specified
            default_output = results_path.with_suffix('.html')
            with open(default_output, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"HTML table written to: {default_output}", file=sys.stderr)


if __name__ == '__main__':
    main()

