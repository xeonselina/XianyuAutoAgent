#!/usr/bin/env python3
"""
WSGI entry point for gunicorn
"""

# CRITICAL: Monkey patch MUST be done before any other imports
# This prevents SSL-related RecursionError when using gevent workers
import gevent.monkey
gevent.monkey.patch_all()

from app import create_app

# Create the Flask application instance
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)