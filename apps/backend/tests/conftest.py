"""
conftest.py for ShopFlow API tests.

This file ensures pytest can import the app modules correctly both:
  - when running from the project root:  pytest apps/backend/tests/
  - when running from inside the shopflow repo clone (builder/tester agents)

The shopflow repo has this structure after cloning:
  /app/
    apps/backend/main.py
    apps/backend/tests/
    requirements.txt

PYTHONPATH=/app is set in the Dockerfile so imports resolve correctly.
"""
import sys
import os

# Add /app to path if not already present (handles running from arbitrary cwd)
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
