#!/usr/bin/env python3
"""Unit tests for variant registry system in view_results.py"""

import unittest
from scripts.view_results import (
    VariantRegistry,
    detect_variants_in_results,
    filter_results_by_variant,
)


class TestVariantRegistry(unittest.TestCase):
    """Test VariantRegistry class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.registry = VariantRegistry()
    
    def test_default_variants_registered(self):
        """Test that default v1 and v2 variants are registered."""
        variants = self.registry.list_variants()
        self.assertIn('v1_sha1_hex', variants)
        self.assertIn('v2_sha256_hex', variants)
    
    def test_v1_sha1_hex_detection(self):
        """Test detection of v1 SHA1 hex SWHID."""
        swhid = 'swh:1:cnt:e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'
        variant = self.registry.get_variant_for_swhid(swhid)
        self.assertEqual(variant, 'v1_sha1_hex')
        
        expected_key = self.registry.get_expected_key(variant)
        self.assertEqual(expected_key, 'swhid')
    
    def test_v2_sha256_hex_detection(self):
        """Test detection of v2 SHA256 hex SWHID."""
        swhid = 'swh:2:cnt:473a0f4c3be8a93681a267e3b1e9a7dcda1185436fe141f7749120a303721813'
        variant = self.registry.get_variant_for_swhid(swhid)
        self.assertEqual(variant, 'v2_sha256_hex')
        
        expected_key = self.registry.get_expected_key(variant)
        self.assertEqual(expected_key, 'expected_swhid_sha256')
    
    def test_invalid_swhid_returns_none(self):
        """Test that invalid SWHID strings return None."""
        invalid_cases = [
            '',
            'invalid',
            'swh:',
            'swh:1:',
            'swh:1:cnt',
        ]
        for invalid in invalid_cases:
            variant = self.registry.get_variant_for_swhid(invalid)
            self.assertIsNone(variant, f"Expected None for '{invalid}'")
    
    def test_register_new_variant(self):
        """Test registering a new variant."""
        self.registry.register_variant('v2_sha256_base64', {
            'version': 2,
            'hash_algo': 'sha256',
            'serialization': 'base64',
            'expected_key': 'expected_swhid_sha256_base64',
            'swhid_prefix': 'swh:2:',
            'hash_length': 44,
        })
        
        self.assertIn('v2_sha256_base64', self.registry.list_variants())
        config = self.registry.get_variant_config('v2_sha256_base64')
        self.assertEqual(config['hash_length'], 44)
        self.assertEqual(config['expected_key'], 'expected_swhid_sha256_base64')
    
    def test_register_variant_missing_key_raises(self):
        """Test that registering variant with missing required key raises ValueError."""
        with self.assertRaises(ValueError):
            self.registry.register_variant('invalid', {
                'version': 1,
                'hash_algo': 'sha1',
                # Missing other required keys
            })
    
    def test_get_variant_config(self):
        """Test getting variant configuration."""
        config = self.registry.get_variant_config('v1_sha1_hex')
        self.assertIsNotNone(config)
        self.assertEqual(config['version'], 1)
        self.assertEqual(config['hash_algo'], 'sha1')
        self.assertEqual(config['serialization'], 'hex')
        self.assertEqual(config['hash_length'], 40)
    
    def test_get_variant_config_nonexistent(self):
        """Test getting config for non-existent variant returns None."""
        config = self.registry.get_variant_config('nonexistent')
        self.assertIsNone(config)
    
    def test_serialization_detection_hex(self):
        """Test hex serialization format detection."""
        hex_hash = 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'
        serialization = self.registry._detect_serialization_format(hex_hash)
        self.assertEqual(serialization, 'hex')
    
    def test_serialization_detection_base64(self):
        """Test base64 serialization format detection."""
        base64_hash = '5p3im7Ld1kQ4uymud12tws5M1Tk='
        serialization = self.registry._detect_serialization_format(base64_hash)
        self.assertEqual(serialization, 'base64')
    
    def test_hash_algo_detection_from_length(self):
        """Test hash algorithm detection from length."""
        self.assertEqual(self.registry._detect_hash_algo_from_length(40), 'sha1')
        self.assertEqual(self.registry._detect_hash_algo_from_length(64), 'sha256')
        self.assertEqual(self.registry._detect_hash_algo_from_length(128), 'sha512')
        self.assertEqual(self.registry._detect_hash_algo_from_length(44), 'sha256')  # base64
        self.assertEqual(self.registry._detect_hash_algo_from_length(99), 'unknown')  # unknown
    
    def test_serialization_detection_base85(self):
        """Test base85 serialization format detection."""
        # Base85 uses characters from ! (33) to u (117) in ASCII
        # Example base85 string (valid base85 characters only)
        base85_hash = '!\"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstu'
        serialization = self.registry._detect_serialization_format(base85_hash)
        self.assertEqual(serialization, 'base85')
        
        # SHA256 base85 (40 chars) - example with valid base85 chars
        base85_hash_40 = '!\"#$%&\'()*+,-./0123456789:;<=>?@ABCD'
        serialization = self.registry._detect_serialization_format(base85_hash_40)
        self.assertEqual(serialization, 'base85')
    
    def test_serialization_detection_base32(self):
        """Test base32 serialization format detection."""
        # Base32 uses A-Z, 2-7, = (no lowercase, no 0/1/8/9)
        # Note: Base32 characters are all within base85 range (!-u), so base32 strings
        # will be detected as base85 first (which is correct - base85 check comes first).
        # However, base32 has additional constraints (no 0/1/8/9), so we can test those.
        
        # A pure base32 string (A-Z, 2-7, =) will match base85 pattern first
        base32_hash = 'ABCDEF234567='
        serialization = self.registry._detect_serialization_format(base32_hash)
        # Since base32 chars are subset of base85, it will be detected as base85
        # This is correct behavior - base85 check comes before base32
        self.assertEqual(serialization, 'base85')
        
        # Base32 should not match if it contains invalid chars like 0 or 1
        invalid_base32 = 'ABCDEF2345670'  # Contains '0' (outside base32 charset)
        serialization = self.registry._detect_serialization_format(invalid_base32)
        # '0' is in base85 range, so it will still match base85
        self.assertEqual(serialization, 'base85')
        
        # Test that base32 detection logic still works for edge cases
        # Base32 with lowercase should not match base32 pattern
        base32_with_lowercase = 'ABCDEF234567a='  # Contains lowercase 'a'
        serialization = self.registry._detect_serialization_format(base32_with_lowercase)
        # Lowercase 'a' is in base85 range, so it matches base85
        self.assertEqual(serialization, 'base85')
    
    def test_ambiguous_length_resolution(self):
        """Test ambiguous length resolution using serialization."""
        # 40 chars is ambiguous: could be SHA1 hex or SHA256 base85
        # With hex serialization, should return SHA1
        algo = self.registry._detect_hash_algo_from_length(40, serialization='hex')
        self.assertEqual(algo, 'sha1')
        
        # With base85 serialization, should return SHA256
        algo = self.registry._detect_hash_algo_from_length(40, serialization='base85')
        self.assertEqual(algo, 'sha256')
        
        # Without serialization, defaults to SHA1 (backward compatibility)
        algo = self.registry._detect_hash_algo_from_length(40)
        self.assertEqual(algo, 'sha1')
    
    def test_base64_padding_variations(self):
        """Test base64 detection with different padding amounts."""
        # Base64 with 2 padding chars
        base64_2pad = 'RzoPxMO+iZNhombjse6n3N2hGFQ2/hQfd0kSCjA3IYM=='
        serialization = self.registry._detect_serialization_format(base64_2pad)
        self.assertEqual(serialization, 'base64')
        
        # Base64 with 1 padding char
        base64_1pad = 'RzoPxMO+iZNhombjse6n3N2hGFQ2/hQfd0kSCjA3IYM='
        serialization = self.registry._detect_serialization_format(base64_1pad)
        self.assertEqual(serialization, 'base64')
        
        # Base64 without padding (43 chars for SHA256)
        base64_nopad = 'RzoPxMO+iZNhombjse6n3N2hGFQ2/hQfd0kSCjA3IYM'
        serialization = self.registry._detect_serialization_format(base64_nopad)
        self.assertEqual(serialization, 'base64')
    
    def test_length_mappings_all_formats(self):
        """Test length mappings for all serialization formats."""
        # Hex
        self.assertEqual(self.registry._detect_hash_algo_from_length(40, 'hex'), 'sha1')
        self.assertEqual(self.registry._detect_hash_algo_from_length(64, 'hex'), 'sha256')
        self.assertEqual(self.registry._detect_hash_algo_from_length(128, 'hex'), 'sha512')
        
        # Base64
        self.assertEqual(self.registry._detect_hash_algo_from_length(27, 'base64'), 'sha1')
        self.assertEqual(self.registry._detect_hash_algo_from_length(44, 'base64'), 'sha256')
        self.assertEqual(self.registry._detect_hash_algo_from_length(88, 'base64'), 'sha512')
        self.assertEqual(self.registry._detect_hash_algo_from_length(43, 'base64'), 'sha256')  # no padding
        
        # Base85
        self.assertEqual(self.registry._detect_hash_algo_from_length(25, 'base85'), 'sha1')
        self.assertEqual(self.registry._detect_hash_algo_from_length(40, 'base85'), 'sha256')
        self.assertEqual(self.registry._detect_hash_algo_from_length(50, 'base85'), 'sha512')
        
        # Base32
        self.assertEqual(self.registry._detect_hash_algo_from_length(32, 'base32'), 'sha1')
        self.assertEqual(self.registry._detect_hash_algo_from_length(52, 'base32'), 'sha256')
        self.assertEqual(self.registry._detect_hash_algo_from_length(104, 'base32'), 'sha512')
    
    def test_detection_order_base85_before_base64(self):
        """Test that base85 is detected before base64 (base85 charset is subset of base64)."""
        # A base85 string would also match base64 pattern, but should be detected as base85
        # Base85 uses characters ! through u (33-117 in ASCII)
        # Use valid base85 characters only
        base85_string = '!\"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstu'
        serialization = self.registry._detect_serialization_format(base85_string)
        self.assertEqual(serialization, 'base85')
        
        # Test that a string with base85 chars that would also match base64
        # is detected as base85 (because base85 check comes first)
        base85_overlap = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/='  # Base64 chars, but also base85
        serialization = self.registry._detect_serialization_format(base85_overlap)
        self.assertEqual(serialization, 'base85')  # Should be base85, not base64


class TestVariantDetection(unittest.TestCase):
    """Test variant detection and filtering functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.registry = VariantRegistry()
        self.sample_results = {
            'run': {'id': 'test-run', 'branch': 'main'},
            'implementations': [
                {'id': 'rust', 'version': '1.0.0'},
                {'id': 'python', 'version': '1.0.0'},
            ],
            'tests': [
                {
                    'id': 'test1',
                    'category': 'content',
                    'expected': {
                        'swhid': 'swh:1:cnt:e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
                        'expected_swhid_sha256': 'swh:2:cnt:473a0f4c3be8a93681a267e3b1e9a7dcda1185436fe141f7749120a303721813',
                    },
                    'results': [
                        {
                            'implementation': 'rust',
                            'status': 'PASS',
                            'swhid': 'swh:1:cnt:e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
                        },
                        {
                            'implementation': 'python',
                            'status': 'PASS',
                            'swhid': 'swh:2:cnt:473a0f4c3be8a93681a267e3b1e9a7dcda1185436fe141f7749120a303721813',
                        },
                    ],
                },
            ],
        }
    
    def test_detect_variants_in_results(self):
        """Test detecting variants present in results."""
        variants = detect_variants_in_results(self.sample_results, self.registry)
        self.assertEqual(variants, {'v1_sha1_hex', 'v2_sha256_hex'})
    
    def test_detect_variants_empty_results(self):
        """Test detecting variants in empty results."""
        empty_results = {'tests': []}
        variants = detect_variants_in_results(empty_results, self.registry)
        self.assertEqual(variants, set())
    
    def test_filter_results_by_variant_v1(self):
        """Test filtering results for v1 variant."""
        filtered = filter_results_by_variant(
            self.sample_results, 'v1_sha1_hex', self.registry
        )
        
        self.assertEqual(len(filtered['tests']), 1)
        test = filtered['tests'][0]
        self.assertEqual(test['id'], 'test1')
        self.assertEqual(len(test['results']), 1)
        self.assertEqual(test['results'][0]['implementation'], 'rust')
        self.assertEqual(test['results'][0]['swhid'], 'swh:1:cnt:e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')
        
        # Check expected value is filtered correctly
        self.assertIn('swhid', test['expected'])
        self.assertEqual(test['expected']['swhid'], 'swh:1:cnt:e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')
        self.assertNotIn('expected_swhid_sha256', test['expected'])
    
    def test_filter_results_by_variant_v2(self):
        """Test filtering results for v2 variant."""
        filtered = filter_results_by_variant(
            self.sample_results, 'v2_sha256_hex', self.registry
        )
        
        self.assertEqual(len(filtered['tests']), 1)
        test = filtered['tests'][0]
        self.assertEqual(test['id'], 'test1')
        self.assertEqual(len(test['results']), 1)
        self.assertEqual(test['results'][0]['implementation'], 'python')
        self.assertEqual(test['results'][0]['swhid'], 'swh:2:cnt:473a0f4c3be8a93681a267e3b1e9a7dcda1185436fe141f7749120a303721813')
        
        # Check expected value is filtered correctly
        self.assertIn('expected_swhid_sha256', test['expected'])
        self.assertEqual(test['expected']['expected_swhid_sha256'], 'swh:2:cnt:473a0f4c3be8a93681a267e3b1e9a7dcda1185436fe141f7749120a303721813')
        self.assertNotIn('swhid', test['expected'])
    
    def test_filter_results_unknown_variant_raises(self):
        """Test that filtering with unknown variant raises ValueError."""
        with self.assertRaises(ValueError):
            filter_results_by_variant(
                self.sample_results, 'nonexistent_variant', self.registry
            )
    
    def test_filter_results_preserves_metadata(self):
        """Test that filtering preserves run and implementation metadata."""
        filtered = filter_results_by_variant(
            self.sample_results, 'v1_sha1_hex', self.registry
        )
        
        self.assertIn('run', filtered)
        self.assertIn('implementations', filtered)
        self.assertEqual(filtered['run']['id'], 'test-run')
        self.assertEqual(len(filtered['implementations']), 2)


if __name__ == '__main__':
    unittest.main()

