#!/bin/bash
# Type and import checking script for native-blend-cli

set -e  # Exit on first error

echo "🔍 Running code quality checks..."
echo ""

# Change to script directory
cd "$(dirname "$0")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Type checking with mypy
echo "📝 Type checking with mypy..."
if uv run mypy src/nativeblend --pretty --show-error-codes; then
    echo -e "${GREEN}✓ Type checking passed${NC}"
else
    echo -e "${RED}✗ Type checking failed${NC}"
    exit 1
fi
echo ""

# Import checking
echo "📦 Checking imports..."
if uv run python -c "import nativeblend; print('✓ All imports OK')"; then
    echo -e "${GREEN}✓ Import checking passed${NC}"
else
    echo -e "${RED}✗ Import checking failed${NC}"
    exit 1
fi
echo ""

# Compile check
echo "🐍 Compiling Python files..."
if uv run python -m py_compile src/nativeblend/*.py; then
    echo -e "${GREEN}✓ Compilation passed${NC}"
else
    echo -e "${RED}✗ Compilation failed${NC}"
    exit 1
fi
echo ""

echo -e "${GREEN}✅ All checks passed!${NC}"
