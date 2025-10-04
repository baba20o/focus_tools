# Example: Custom Profile Creation

**Scenario:** You frequently search for ROS message definitions

## Step 1: Add to `.focus_config.yaml`

```yaml
profiles:
  my-msg-hunter:
    # Only search in message directories
    must_parent_any: [msg, srv, action]
    
    # Exclude test messages
    not_parent: [test, tests, example, examples]
    
    # Only message/service/action files
    include: ["*.msg", "*.srv", "*.action", "*.idl"]
    
    # Pattern for finding field definitions
    pattern: "(^[a-zA-Z0-9_]+\\s+[a-zA-Z0-9_]+|^#.*comment)"
    regex: true
    
    # Weight message files highest
    weights:
      .msg: 2.0
      .srv: 1.8
      .action: 1.8
      .idl: 1.5
    
    # Return top 10 message files
    top_files: 10
    
    # Show structure
    peek: true
```

## Step 2: Use Your Profile

```bash
python focus_probe.py MultiJointTraj "fields" \
  -b ./bdai-main \
  --profile my-msg-hunter \
  --json
```

## Step 3: Share with Team

Commit `.focus_config.yaml` to your repo so everyone benefits!

```bash
git add .focus_config.yaml
git commit -m "Add custom message hunter profile"
git push
```

---

## Advanced: Profile Inheritance

You can build on existing profiles:

```yaml
profiles:
  # Base profile
  msg-hunter:
    include: ["*.msg", "*.srv"]
    weights: {.msg: 2.0, .srv: 1.8}
  
  # Specialized profile (extends msg-hunter in your app logic)
  spot-msg-hunter:
    # Inherits msg-hunter settings
    # Adds specific filters
    name_regex: "spot_.*"
    must_parent: [spot]
```
