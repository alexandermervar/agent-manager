from setuptools import setup, find_packages

setup(
    name="agent-manager",
    version="0.2.0",
    packages=find_packages(),
    install_requires=[
        "anthropic>=0.40.0",
        "click>=8.1.0",
        "pyyaml>=6.0",
        "rich>=13.0.0",
        "python-dotenv>=1.0.0",
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.29.0",
        "jinja2>=3.1.0",
        "sse-starlette>=1.8.0",
        "httpx>=0.27.0",
        "pytest>=8.0.0",
        "pytest-asyncio>=0.23.0",
    ],
    entry_points={
        "console_scripts": [
            "agentmgr=agent_manager.cli:main",
            "agentmgr-web=agent_manager.web.app:start",
        ],
    },
    python_requires=">=3.10",
)
