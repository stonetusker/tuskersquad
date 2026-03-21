import os
import sys

# ensure that the workspace root is on the python path for all tests
root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
if root not in sys.path:
    sys.path.insert(0, root)
