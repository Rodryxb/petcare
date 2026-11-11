"""
Punto de entrada WSGI (Gunicorn en EC2):
    gunicorn config.wsgi:application --bind unix:/run/gunicorn.sock --workers 3
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
