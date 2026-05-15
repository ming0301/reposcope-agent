import warnings

# 屏蔽 LangChain/LangGraph 框架的 deprecation warning
warnings.filterwarnings("ignore", message=".*allowed_objects.*")
