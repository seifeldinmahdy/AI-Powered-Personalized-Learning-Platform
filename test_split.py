import math

class FakeChunk:
    display_title = "Title"

def split(chunk_sizes, max_tok=5000):
    total_tokens = sum(chunk_sizes)
    print(f"Total: {total_tokens}")
    if total_tokens <= max_tok * 1.10:
        return [chunk_sizes]
        
    num_parts = math.ceil(total_tokens / max_tok)
    target = total_tokens / num_parts
    print(f"Num parts: {num_parts}, target: {target}")
    
    parts = []
    current = []
    current_tokens = 0
    part = 1
    
    for tokens in chunk_sizes:
        if current_tokens > 0 and (current_tokens + tokens / 2 >= target):
            if part < num_parts:
                parts.append((part, current, current_tokens))
                part += 1
                current = []
                current_tokens = 0
        current.append(tokens)
        current_tokens += tokens
        
    if current:
        parts.append((part, current, current_tokens))
    return parts

# Construct 17 chunks summing to 6078. 14 chunks -> 4930, 3 chunks -> 1148
sizes = [4930 / 14] * 14 + [1148 / 3] * 3
# Run it
for p, chunks, total in split(sizes):
    print(f"Part {p}: {len(chunks)} chunks, {total} tok")

