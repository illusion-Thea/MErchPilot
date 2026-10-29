"""文件职责：声明 mcp Python 包及其模块边界。"""

from merchpilot.mcp.server import app, mcp

__all__ = ["app", "mcp"]
