✅ How to Use

List available profiles

There is no list command; profiles are the entries under profiles: in a loaded config.
focus_probe reads ~/.focus_config.yaml, then .focus_config.yaml in each -b base, then any
--config FILE (later files win; a profile with the same name is replaced, not merged).
The .focus_config.yaml in this repository is a sample: copy it to one of those places or
pass it with --config. pyyaml must be installed, and an unknown profile name is silently ignored.


Run probe with a preset

python focus_probe.py spot "(teleop|wasd|rviz|launch|cmd_vel)" -b ./bdai-main --profile teleop-scout --json

PATTERN is a required positional argument. A profile's pattern: entry is not currently used.


Override any parameter

python focus_probe.py spot "(teleop|rviz)" -b ./bdai-main --profile teleop-scout --top-files 5

Switches such as --peek can only turn a setting on (there is no --peek false), so a
profile's peek: true cannot currently be turned off from the command line.

🧠 What This Config Does
Section	Purpose
aliases	Expands common keywords automatically (spot → spot_ros2, etc.)
defaults	Default include/exclude globs (focus_probe currently reads only include and exclude from this section)
weights	Adjusts ranking importance by file type
profiles	Defines pre-baked strategies for ROS, Spot, docs, configs, etc.

This config basically gives your Focus suite a personality — ROS-savvy, context-limited, and LLM-friendly.