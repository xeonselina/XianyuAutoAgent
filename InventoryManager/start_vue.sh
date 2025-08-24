#!/bin/bash

# Vue前端重写版本启动脚本

echo "🚀 启动库存管理系统 Vue 版本"
echo "================================"

# 检查是否已构建Vue应用
if [ ! -d "static/vue-dist" ]; then
    echo "📦 正在构建Vue应用..."
    cd frontend
    npm run build
    cd ..
    echo "✅ Vue应用构建完成"
fi

# 启动Flask后端
echo "🖥️ 启动Flask后端服务..."
echo "后端地址: http://localhost:5000"
echo "Vue应用地址: http://localhost:5000/vue"
echo "原版应用地址: http://localhost:5000/"
echo ""
echo "🔄 Vue开发模式 (可选):"
echo "在新终端窗口运行: cd frontend && npm run dev"
echo "Vue开发服务器: http://localhost:3000"
echo ""

# 设置环境变量
export FLASK_APP=app.py
export FLASK_ENV=development

# 启动Flask应用
python3 app.py
