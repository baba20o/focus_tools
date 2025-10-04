# Example: Simple Profile Usage

**Scenario:** Find all Spot teleop launch files

```bash
# Using the built-in teleop-scout profile
python focus_probe.py spot "teleop" \
  -b /path/to/bdai-main \
  --profile teleop-scout \
  --json > teleop_results.json
```

**What it finds:**
- `spot_rviz_teleop.launch.py` (ranked #1, weight=2.0)
- `spot_utilities/README.md` (docs, weight=1.5)
- `teleop_node.py` (code reference)

**Why it works:**
- Profile filters to `src/` directories only
- Weights `.launch.py` files 2x higher than regular code
- Excludes `tests/` and `examples/` automatically

---

## Example Output (Simplified)

```json
{
  "keyword": "spot",
  "pattern": "teleop",
  "dirs_found": 7,
  "files_with_hits": 15,
  "top_files": [
    {
      "path": ".../spot_utilities/launch/spot_rviz_teleop.launch.py",
      "score": 12.5,
      "hits": 5,
      "snippets": [
        {
          "line": 42,
          "context": [
            {"line": 40, "text": "# Launch RViz teleop node"},
            {"line": 41, "text": "Node("},
            {"line": 42, "text": "    package='spot_utilities',"},
            {"line": 43, "text": "    executable='teleop_node',"},
            {"line": 44, "text": "    name='spot_teleop'"}
          ]
        }
      ],
      "peek_head": ["...(first 80 lines)..."],
      "peek_tail": ["...(last 40 lines)..."]
    }
  ],
  "token_estimate": 3200
}
```
