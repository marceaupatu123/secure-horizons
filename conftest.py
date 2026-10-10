"""conftest racine : garantit que la racine du repo est sur sys.path pour pytest.

Permet d'importer les packages de module (monitor, detection, llm, response,
dashboard, shared) dans les tests de fumee sans installation editable.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
