import os
import sys

_proto_dir = os.path.dirname(os.path.abspath(__file__))
if _proto_dir not in sys.path:
    sys.path.insert(0, _proto_dir)
