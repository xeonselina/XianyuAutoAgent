#!/usr/bin/env python3
"""
WSGI entry point for gunicorn
"""

from app import create_app

# Create the Flask application instance
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)