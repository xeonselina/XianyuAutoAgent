#!/bin/bash
# AI KEFU Boot Diagnostic Tool

echo "=========================================="
echo "AI KEFU Boot Diagnostic Check"
echo "=========================================="
echo ""

# Check Python environment
echo "1. Python Environment"
echo "   Python: $(python3 --version)"
echo "   Executable: $(which python3)"
echo ""

# Check installed packages
echo "2. Required Packages"
packages=("pydantic-settings" "gunicorn" "redis" "chromadb" "pymysql" "dingtalk-stream" "fastapi" "uvicorn" "pydantic" "openai" "playwright")

missing=0
for pkg in "${packages[@]}"; do
    if python3 -c "import ${pkg//-/_}" 2>/dev/null; then
        echo "   ✓ $pkg"
    else
        echo "   ✗ $pkg (MISSING)"
        ((missing++))
    fi
done

echo ""
echo "3. Services"

# Check Redis
if command -v redis-cli &> /dev/null; then
    if redis-cli ping &> /dev/null; then
        echo "   ✓ Redis (running)"
    else
        echo "   ⚠ Redis (installed but not responding)"
    fi
else
    echo "   ✗ Redis (not installed)"
fi

# Check MySQL
if command -v mysql &> /dev/null; then
    if mysql -e "SELECT 1" &> /dev/null; then
        echo "   ✓ MySQL (running)"
    else
        echo "   ⚠ MySQL (installed but not accessible)"
    fi
else
    echo "   ✗ MySQL (not installed)"
fi

echo ""
echo "4. App Import Test"
cd /Users/jimmypan/git_repo/XianyuAutoAgent
if python3 -c "from ai_kefu.api.main import app" 2>&1 | head -1 | grep -q "Successfully"; then
    echo "   ✓ App imports successfully"
else
    error=$(python3 -c "from ai_kefu.api.main import app" 2>&1 | head -1)
    echo "   ✗ App import failed: $error"
fi

echo ""
echo "=========================================="
if [ $missing -gt 0 ]; then
    echo "Status: FAILED - $missing missing packages"
    echo ""
    echo "Fix:"
    echo "  pip install -r requirements.txt"
else
    echo "Status: Ready to boot"
    echo ""
    echo "Start:"
    echo "  cd ai_kefu && make run-api"
fi
echo "=========================================="

