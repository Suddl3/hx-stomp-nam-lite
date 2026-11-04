"""Where the upstream hx-stomp-nam-lite tools are: `repo/tools` next to this folder's parent (a
working copy with upstream cloned into repo/), or `../tools` (this folder inside the fork,
helix-floor/ at the root of hx-stomp-nam-lite)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = next(p for p in (os.path.join(ROOT, "repo", "tools"), os.path.join(os.path.dirname(ROOT), "tools"))
             if os.path.isdir(p))
SHARC = os.path.join(TOOLS, "sharc")
