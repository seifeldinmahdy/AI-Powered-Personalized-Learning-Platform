import json
from transformers import AutoConfig

local_config_path = "/Users/seifmahdy/Desktop/Programming/Graduation Project/content_gen/AI-Powered-Personalized-Learning-Platform/slides-generator/models/content_specialist/config.json"

with open(local_config_path, "r") as f:
    local_config = json.load(f)

hf_config = AutoConfig.from_pretrained("google/flan-t5-large").to_dict()

diffs = {}
for k, v in hf_config.items():
    if k not in local_config:
        diffs[k] = ("MISSING", v)
    elif local_config[k] != v:
        diffs[k] = (local_config[k], v)

for k, v in local_config.items():
    if k not in hf_config:
        diffs[k] = (v, "EXTRA")

import pprint
print("Differences (Local vs HF):")
pprint.pprint(diffs)
