"""
Setup configuration for AI Kefu package.
"""

from setuptools import setup, find_packages

setup(
    name="ai_kefu",
    version="1.0.0",
    description="AI-powered customer service agent for Xianyu",
    packages=find_packages(exclude=["tests", "tests.*", "legacy", "legacy.*"]),
    python_requires=">=3.9",
    install_requires=[
        "openai>=1.0.0",
        "websockets>=13.0",
        "loguru>=0.7.0",
        "python-dotenv>=1.0.0",
        "requests>=2.32.0",
        "fastapi>=0.108.0",
        "uvicorn[standard]>=0.25.0",
        "pydantic>=2.5.0",
        "pydantic-settings>=2.1.0",
        "dashscope>=1.14.0",
        "chromadb>=1.4.0",
        "redis>=5.0.0",
        "tenacity>=8.2.0",
        "playwright>=1.40.0",
        "pandas>=1.5.0",
        "openpyxl>=3.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "pytest-mock>=3.10.0",
            "ruff>=0.1.0",
            "mypy>=1.7.0",
            "httpx>=0.27.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ai-kefu=ai_kefu.main:main",
        ],
    },
)
