"""入口文件。"""

from config import DEBUG, APP_NAME
from utils.helpers import format_greeting
from models.user import User


def main():
    user = User("Alice", "alice@example.com")
    print(format_greeting(user))
    if DEBUG:
        print(f"[DEBUG] {APP_NAME} started")


if __name__ == "__main__":
    main()
