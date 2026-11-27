import pathlib
import sys

# Make `import app...` and `import fixtures...` work without installing the project.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
