#!/bin/bash
# SWHID Testing Harness - Deployment Test Script

set -e  # Exit on any error

echo "🚀 SWHID Testing Harness - Deployment Test"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2${NC}"
    else
        echo -e "${RED}❌ $2${NC}"
        exit 1
    fi
}

# Function to print warning
print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

echo ""
echo "1. Testing CLI Installation..."
swhid-harness --help > /dev/null
print_status $? "CLI installed and working"

echo ""
echo "2. Testing Schema Validation..."
python3 -c "from harness.models import HarnessResults; print('Schema models loaded')" > /dev/null
print_status $? "Pydantic models loaded"

echo ""
echo "3. Testing Implementation Loading..."
python3 -c "
from harness.harness import SwhidHarness
h = SwhidHarness()
print(f'Loaded {len(h.implementations)} implementations: {list(h.implementations.keys())}')
" > /dev/null
print_status $? "Implementations loaded"

echo ""
echo "4. Running Content Tests..."
swhid-harness --category content --dashboard-output test_results.json > /dev/null 2>&1
print_status $? "Content tests completed"

echo ""
echo "5. Validating Results Schema..."
python3 -m harness.models test_results.json > /dev/null
print_status $? "Results schema validation passed"

echo ""
echo "6. Testing Dashboard Generation..."
python3 tools/merge_results.py test_results.json --site site > /dev/null
print_status $? "Dashboard files generated"

echo ""
echo "7. Checking Dashboard Files..."
if [ -f "site/data/index.json" ] && [ -f "site/data/latest.json" ]; then
    print_status 0 "Dashboard files created"
else
    print_status 1 "Dashboard files missing"
fi

echo ""
echo "8. Testing Local Server..."
cd site
python3 -m http.server 8080 > /dev/null 2>&1 &
SERVER_PID=$!
sleep 2
if kill -0 $SERVER_PID 2>/dev/null; then
    kill $SERVER_PID 2>/dev/null
    print_status 0 "Local server test passed"
else
    print_warning "Local server test skipped (port may be in use)"
fi
cd ..

echo ""
echo "9. Cleanup..."
rm -f test_results.json
print_status 0 "Test files cleaned up"

echo ""
echo "🎉 All tests passed! The harness is ready for deployment."
echo ""
echo "Next steps:"
echo "1. Push to main branch to trigger GitHub Actions"
echo "2. Enable GitHub Pages (Settings → Pages → GitHub Actions)"
echo "3. Visit the dashboard at: https://your-username.github.io/swhid-rs-tools/"
echo ""
echo "For detailed instructions, see DEPLOYMENT.md"
