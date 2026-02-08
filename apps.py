from django.apps import AppConfig


class PythonSandboxConfig(AppConfig):
    name = 'p_python_sandbox'
    p_type = "plugin"
    verbose_name = "Python Sandbox"
    url_prefix = "python"

