#!/usr/bin/env python3
"""
WSGI entry point for gunicorn
"""

# CRITICAL: Monkey patch MUST be done before any other imports
# This prevents SSL-related RecursionError when using gevent workers
import gevent.monkey
gevent.monkey.patch_all()

import os  # noqa: E402

from app import create_app  # noqa: E402

# Create the Flask application instance
app = create_app(os.environ.get('FLASK_ENV') or 'production')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)
