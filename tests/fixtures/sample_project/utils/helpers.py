"""工具函数模块。"""

from models.user import User


def format_greeting(user: User) -> str:
    return f"Hello, {user.name}! Email: {user.email}"
