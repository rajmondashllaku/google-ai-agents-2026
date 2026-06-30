import os, sys
sys.path.append("src")

env_path = ".env"
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                os.environ[parts[0].strip()] = parts[1].strip().strip('"').strip("'")

from google import genai
client = genai.Client()
for m in client.models.list():
    name = m.name.lower()
    if "pro" in name or "flash" in name:
        print(m.name)
