#!/bin/bash
# Quick script to test Rust implementation during development

set -e

HARNESS_DIR="/home/dicosmo/code/swhid-rs-tools"
RUST_DIR="/home/dicosmo/code/swhid-rs"

cd "$HARNESS_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "🧪 Testing Rust SWHID Implementation"
echo "===================================="
echo ""

# Parse arguments
CATEGORY="${1:-content}"
OUTPUT="${2:-rust_test.json}"

echo "Category: $CATEGORY"
echo "Output: $OUTPUT"
echo ""

# Run the harness
echo "Running harness..."
swhid-harness --impl rust --category "$CATEGORY" --dashboard-output "$OUTPUT"

# Validate results
echo ""
echo "Validating results..."
python3 -m harness.models "$OUTPUT"

# Show summary
echo ""
echo "📊 Test Summary:"
echo "================"
python3 << EOF
import json
with open("$OUTPUT", 'r') as f:
    data = json.load(f)

tests = data.get('tests', [])
total = len(tests)
passed = sum(1 for t in tests 
             for r in t.get('results', []) 
             if r.get('implementation') == 'rust' and r.get('status') == 'pass')
failed = sum(1 for t in tests 
             for r in t.get('results', []) 
             if r.get('implementation') == 'rust' and r.get('status') == 'fail')

print(f"Total tests: {total}")
print(f"✅ Passed: {passed}")
if failed > 0:
    print(f"❌ Failed: {failed}")
    print("\nFailed tests:")
    for t in tests:
        for r in t.get('results', []):
            if r.get('implementation') == 'rust' and r.get('status') == 'fail':
                print(f"  - {t.get('id')}: {r.get('error', 'Unknown error')}")
else:
    print(f"✅ All tests passed!")
EOF

echo ""
echo "Results saved to: $OUTPUT"
echo ""
echo "To view detailed results:"
echo "  cat $OUTPUT | python3 -m json.tool | less"
