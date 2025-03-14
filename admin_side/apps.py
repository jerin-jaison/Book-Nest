# apps.py
from django.apps import AppConfig

class AdminSideConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_side'

    def ready(self):
        from . import signals