import json
import sys

filename = sys.argv[1] if len(sys.argv) > 1 else 'amp_probe_test.json'

with open(filename) as f:
    d = json.load(f)

print(f"Total top files: {len(d['top_files'])}\n")
for i, f in enumerate(d['top_files'][:15]):
    path = f['path'].split('bdai-main')[-1]
    print(f"{i+1:2}. hits:{f['hits']:3} | {path}")
    
# Find projects/amp/README.md
for i, f in enumerate(d['top_files']):
    if 'projects/amp/README.md' in f['path'] or 'projects\\amp\\README.md' in f['path']:
        print(f"\n✅ Found projects/amp/README.md at position {i+1} with {f['hits']} hits")
        break
else:
    print("\n❌ projects/amp/README.md NOT in top files!")
