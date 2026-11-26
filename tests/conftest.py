import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "langfuse-trace-triage" / "scripts"
sys.path.insert(0, str(SCRIPTS))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "demo-agent"))
