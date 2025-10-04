✅ How to Use

List available profiles

python focus_common.py --list-profiles


Run probe with a preset

python focus_probe.py spot -b ./bdai-main --profile teleop-scout --json


Override any parameter

python focus_probe.py spot -b ./bdai-main --profile teleop-scout --top-files 5 --peek false

🧠 What This Config Does
Section	Purpose
aliases	Expands common keywords automatically (spot → spot_ros2, etc.)
defaults	Defines safe global bounds (context lines, byte limits, excludes)
weights	Adjusts ranking importance by file type
profiles	Defines pre-baked strategies for ROS, Spot, docs, configs, etc.

This config basically gives your Focus suite a personality — ROS-savvy, context-limited, and LLM-friendly.