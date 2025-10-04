🧩 focus_common.py
Purpose

focus_common.py is the shared foundation for all Focus tools (focus_tree, focus_grep, focus_probe).
It provides configuration management, profile merging, alias expansion, scoring weights, ANSI color handling, and token budgeting — allowing each Focus tool to stay lightweight and interoperable.

🔧 Key Features
1. Configuration System

Automatically loads:

Global config from ~/.focus_config.yaml

Per-repo configs from <base>/.focus_config.yaml

Additional overrides via --config CLI argument

Config supports:

aliases: — map of keyword aliases

aliases:
  spot: [spot_ros2, spot_sdk]
  ros: [ros, ros2, ros_ws, catkin_ws]


defaults: — default include/exclude globs

weights: — file-type scoring weights

profiles: — reusable parameter sets for specialized searches

Example:

defaults:
  include: ["*.py", "*.launch.py", "*.md"]
  exclude: ["*.bin", "*.min.js"]
weights:
  .py: 1.5
  .launch.py: 2.0
profiles:
  teleop:
    must_parent_all: ["src", "ros"]
    include: ["*.py", "*.launch.py"]
    regex: true

2. Profile Application

Merges CLI args with named profiles:

Profiles pre-fill flags like --must-parent, --include, --name-regex, etc.

CLI arguments override profile values.

Enables context-specific presets (e.g., "docs", "teleop", "configs").

merged = fc.apply_profile(base_kwargs, cfg, "teleop")

3. Alias Expansion

Automatically expands keyword aliases before matching directories.
Example:

aliases:
  spot: [spot_ros2, spot_robot]


→ Searching spot will also match spot_ros2 or spot_robot.

4. ANSI Coloring Helpers

Safe colorization that automatically disables colors in non-TTY environments.

fc.colorize("Found match!", fc.Ansi.GREEN)

5. Token & Size Budgeting

Approximate token estimation for JSON/text objects.
Automatically trims oversized LLM bundles.

bundle = fc.trim_bundle_to_token_budget(bundle, max_tokens=8192)


Uses a simple heuristic (≈4 chars/token) to stay within API model limits.

6. Clustering Utilities

Groups file paths by directory prefixes for cleaner summaries and cluster visualization.

clusters = fc.common_prefix_components(paths)

⚙️ Typical Workflow Integration

focus_tree calls alias + parent filters from focus_common

focus_grep uses profile + weights for ranking

focus_probe imports everything for:

alias resolution

scoring

YAML-based configuration

token trimming

colorized summaries

🧠 Design Philosophy

Composable: Each Focus tool imports the same logic without duplicating behavior.

LLM-ready: Config-driven, structured output, and token control.

Predictable: All normalization, alias handling, and filtering use the same utilities.

📂 Example Config Locations
File	Purpose
~/.focus_config.yaml	User-wide global defaults
./my_repo/.focus_config.yaml	Repo-specific overrides
--config custom.yaml	Temporary or external configs
✅ Example Usage
# Load defaults and aliases
python focus_probe.py spot "teleop" -b ./bdai-main --profile teleop --budget-tokens 8192

# Debug print all loaded config and profiles
python -m focus_common --debug

📜 Summary
Capability	Description
🧩 Config Loader	YAML-based global, per-repo, or external
🗂️ Profile System	Named search presets
🧠 Alias Map	Normalize and unify keywords
🎨 ANSI Support	Color-safe printing
🪶 Token Budgeting	Keeps JSON under LLM limits
📊 Weight System	Rank results by file type
🧭 Clustering	Group paths for context