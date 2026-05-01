"""Template registry and rendering system."""

from dataclasses import dataclass
from typing import Any, Callable
from enum import Enum


class Renderer(str, Enum):
    """Supported visual renderers."""
    GRAPHVIZ = "graphviz"
    MERMAID = "mermaid"
    MATPLOTLIB = "matplotlib"


@dataclass
class Template:
    """Definition of a visual template."""
    id: str
    name: str
    description: str
    renderer: Renderer
    keywords: list[str]  # Keywords that suggest this template
    required_params: list[str]
    optional_params: list[str]
    render_func: Callable[[dict[str, Any]], str]


class TemplateRegistry:
    """Registry of all available templates."""
    
    def __init__(self):
        self.templates: dict[str, Template] = {}
    
    def register(self, template: Template) -> None:
        """Register a template."""
        self.templates[template.id] = template
    
    def get(self, template_id: str) -> Template | None:
        """Get a template by ID."""
        return self.templates.get(template_id)
    
    def list_all(self) -> list[Template]:
        """List all registered templates."""
        return list(self.templates.values())
    
    def render(self, template_id: str, params: dict[str, Any]) -> tuple[str, str]:
        """
        Render a template with given parameters.
        
        Returns:
            Tuple of (renderer_type, rendered_code)
        """
        template = self.get(template_id)
        if not template:
            raise ValueError(f"Unknown template: {template_id}")
        
        # Validate required params
        missing = [p for p in template.required_params if p not in params]
        if missing:
            raise ValueError(f"Missing required params for {template_id}: {missing}")
        
        rendered_code = template.render_func(params)
        return template.renderer.value, rendered_code


# =============================================================================
# GRAPHVIZ TEMPLATES
# =============================================================================

def _render_linear_chain(params: dict) -> str:
    """Render a linear chain/linked list diagram."""
    nodes = params.get("nodes", ["A", "B", "C"])
    direction = params.get("direction", "LR")  # LR or TB
    show_null = params.get("show_null", True)
    
    lines = [
        "digraph {",
        f"    rankdir={direction};",
        '    node [shape=record, style=filled, fillcolor="#E3F2FD"];',
        '    edge [arrowhead=vee];',
    ]
    
    # Node definitions
    for i, node in enumerate(nodes):
        lines.append(f'    n{i} [label="{node}"];')
    
    if show_null:
        lines.append('    null [label="null" shape=plaintext fontcolor="#666666"];')
    
    # Edge definitions
    node_ids = [f"n{i}" for i in range(len(nodes))]
    if show_null:
        node_ids.append("null")
    
    edges = " -> ".join(node_ids)
    lines.append(f"    {edges};")
    
    lines.append("}")
    return "\n".join(lines)


def _render_binary_tree(params: dict) -> str:
    """Render a binary tree diagram."""
    root = params.get("root", "Root")
    left = params.get("left", "Left")
    right = params.get("right", "Right")
    left_children = params.get("left_children", [])
    right_children = params.get("right_children", [])
    
    lines = [
        "digraph {",
        '    node [shape=circle, style=filled, fillcolor="#E8F5E9"];',
        f'    root [label="{root}"];',
        f'    left [label="{left}"];',
        f'    right [label="{right}"];',
        "    root -> left;",
        "    root -> right;",
    ]
    
    for i, child in enumerate(left_children):
        lines.append(f'    ll{i} [label="{child}"];')
        lines.append(f"    left -> ll{i};")
    
    for i, child in enumerate(right_children):
        lines.append(f'    rr{i} [label="{child}"];')
        lines.append(f"    right -> rr{i};")
    
    lines.append("}")
    return "\n".join(lines)


def _render_stack(params: dict) -> str:
    """Render a stack data structure."""
    items = params.get("items", ["Item 1", "Item 2", "Item 3"])
    top_label = params.get("top_label", "TOP")
    
    lines = [
        "digraph {",
        "    rankdir=TB;",
        '    node [shape=record, style=filled, width=2];',
    ]
    
    # Stack items (top to bottom)
    for i, item in enumerate(items):
        color = "#BBDEFB" if i == 0 else "#E3F2FD"
        label = f"{item}"
        if i == 0:
            label = f"{top_label} → {item}"
        lines.append(f'    s{i} [label="{label}" fillcolor="{color}"];')
    
    # Connect items
    for i in range(len(items) - 1):
        lines.append(f"    s{i} -> s{i+1} [style=invis];")
    
    lines.append("}")
    return "\n".join(lines)


def _render_queue(params: dict) -> str:
    """Render a queue data structure."""
    items = params.get("items", ["Item 1", "Item 2", "Item 3"])
    front_label = params.get("front_label", "FRONT")
    back_label = params.get("back_label", "BACK")
    
    lines = [
        "digraph {",
        "    rankdir=LR;",
        '    node [shape=record, style=filled, fillcolor="#E3F2FD"];',
        f'    front [label="{front_label}" shape=plaintext];',
        f'    back [label="{back_label}" shape=plaintext];',
    ]
    
    # Queue items
    for i, item in enumerate(items):
        lines.append(f'    q{i} [label="{item}"];')
    
    # Connect: front -> items -> back
    if items:
        lines.append(f"    front -> q0;")
        for i in range(len(items) - 1):
            lines.append(f"    q{i} -> q{i+1};")
        lines.append(f"    q{len(items)-1} -> back;")
    
    lines.append("}")
    return "\n".join(lines)


def _render_graph(params: dict) -> str:
    """Render a generic graph with nodes and edges."""
    nodes = params.get("nodes", ["A", "B", "C"])
    edges = params.get("edges", [[0, 1], [1, 2]])
    directed = params.get("directed", True)
    
    graph_type = "digraph" if directed else "graph"
    arrow = "->" if directed else "--"
    
    lines = [
        f"{graph_type} {{",
        '    node [shape=circle, style=filled, fillcolor="#FFF3E0"];',
    ]
    
    for i, node in enumerate(nodes):
        lines.append(f'    n{i} [label="{node}"];')
    
    for edge in edges:
        lines.append(f"    n{edge[0]} {arrow} n{edge[1]};")
    
    lines.append("}")
    return "\n".join(lines)


def _render_layers(params: dict) -> str:
    """Render layered architecture diagram."""
    layers = params.get("layers", ["Layer 1", "Layer 2", "Layer 3"])
    
    lines = [
        "digraph {",
        "    rankdir=TB;",
        '    node [shape=box, style=filled, width=4, height=0.6];',
    ]
    
    colors = ["#FFCDD2", "#F8BBD9", "#E1BEE7", "#D1C4E9", "#C5CAE9", "#BBDEFB"]
    
    for i, layer in enumerate(layers):
        color = colors[i % len(colors)]
        lines.append(f'    l{i} [label="{layer}" fillcolor="{color}"];')
    
    for i in range(len(layers) - 1):
        lines.append(f"    l{i} -> l{i+1};")
    
    lines.append("}")
    return "\n".join(lines)


# =============================================================================
# MERMAID TEMPLATES
# =============================================================================

def _render_flowchart(params: dict) -> str:
    """Render a flowchart with decisions."""
    nodes = params.get("nodes", [])
    edges = params.get("edges", [])
    direction = params.get("direction", "TD")  # TD, LR, BT, RL
    
    lines = [f"graph {direction}"]
    
    for node in nodes:
        node_id = node.get("id", "A")
        label = node.get("label", "Node")
        node_type = node.get("type", "box")  # box, diamond, circle
        
        if node_type == "diamond":
            lines.append(f'    {node_id}{{{label}}}')
        elif node_type == "circle":
            lines.append(f'    {node_id}(({label}))')
        else:
            lines.append(f'    {node_id}[{label}]')
    
    for edge in edges:
        source = edge.get("from", "A")
        target = edge.get("to", "B")
        label = edge.get("label", "")
        
        if label:
            lines.append(f'    {source} -->|{label}| {target}')
        else:
            lines.append(f'    {source} --> {target}')
    
    return "\n".join(lines)


def _render_sequence(params: dict) -> str:
    """Render a sequence diagram."""
    actors = params.get("actors", ["A", "B"])
    messages = params.get("messages", [])
    
    lines = ["sequenceDiagram"]
    
    for actor in actors:
        lines.append(f"    participant {actor}")
    
    for msg in messages:
        sender = msg.get("from", actors[0])
        receiver = msg.get("to", actors[-1])
        text = msg.get("text", "message")
        msg_type = msg.get("type", "solid")  # solid, dashed
        
        arrow = "->>" if msg_type == "solid" else "-->>"
        lines.append(f"    {sender}{arrow}{receiver}: {text}")
    
    return "\n".join(lines)


def _render_cycle(params: dict) -> str:
    """Render a circular/cycle diagram."""
    nodes = params.get("nodes", ["A", "B", "C"])
    title = params.get("title", "")
    
    lines = ["graph LR"]
    
    for i, node in enumerate(nodes):
        lines.append(f'    n{i}[{node}]')
    
    # Connect in a cycle
    for i in range(len(nodes)):
        next_i = (i + 1) % len(nodes)
        lines.append(f"    n{i} --> n{next_i}")
    
    return "\n".join(lines)


def _render_comparison(params: dict) -> str:
    """Render a side-by-side comparison."""
    left_title = params.get("left_title", "Option A")
    right_title = params.get("right_title", "Option B")
    left_items = params.get("left_items", [])
    right_items = params.get("right_items", [])
    
    lines = ["graph LR"]
    lines.append(f'    subgraph {left_title}')
    for i, item in enumerate(left_items):
        lines.append(f'        L{i}[{item}]')
    lines.append("    end")
    
    lines.append(f'    subgraph {right_title}')
    for i, item in enumerate(right_items):
        lines.append(f'        R{i}[{item}]')
    lines.append("    end")
    
    return "\n".join(lines)


def _render_timeline(params: dict) -> str:
    """Render a timeline diagram."""
    title = params.get("title", "Timeline")
    events = params.get("events", [])
    
    lines = ["timeline", f"    title {title}"]
    
    for event in events:
        time = event.get("time", "")
        description = event.get("description", "")
        lines.append(f"    {time} : {description}")
    
    return "\n".join(lines)


def _render_process_flow(params: dict) -> str:
    """Render a simple process flow."""
    steps = params.get("steps", ["Step 1", "Step 2", "Step 3"])
    direction = params.get("direction", "LR")
    
    lines = [f"graph {direction}"]
    
    for i, step in enumerate(steps):
        lines.append(f'    s{i}["{step}"]')
    
    for i in range(len(steps) - 1):
        lines.append(f"    s{i} --> s{i+1}")
    
    return "\n".join(lines)


# =============================================================================
# MATPLOTLIB TEMPLATES
# =============================================================================

def _render_bar_chart(params: dict) -> str:
    """Render a bar chart as matplotlib code."""
    labels = params.get("labels", ["A", "B", "C"])
    values = params.get("values", [10, 20, 15])
    title = params.get("title", "Bar Chart")
    xlabel = params.get("xlabel", "")
    ylabel = params.get("ylabel", "Value")
    
    code = f'''import matplotlib.pyplot as plt

labels = {labels}
values = {values}

plt.figure(figsize=(8, 5))
plt.bar(labels, values, color='steelblue')
plt.title("{title}")
plt.xlabel("{xlabel}")
plt.ylabel("{ylabel}")
plt.tight_layout()
plt.savefig("output.png", dpi=150)
'''
    return code


def _render_pie_chart(params: dict) -> str:
    """Render a pie chart as matplotlib code."""
    labels = params.get("labels", ["A", "B", "C"])
    values = params.get("values", [30, 40, 30])
    title = params.get("title", "Pie Chart")
    
    code = f'''import matplotlib.pyplot as plt

labels = {labels}
values = {values}

plt.figure(figsize=(8, 8))
plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
plt.title("{title}")
plt.tight_layout()
plt.savefig("output.png", dpi=150)
'''
    return code


def _render_grid(params: dict) -> str:
    """Render a grid/table as matplotlib."""
    data = params.get("data", [["A", "B"], ["C", "D"]])
    row_labels = params.get("row_labels", None)
    col_labels = params.get("col_labels", None)
    title = params.get("title", "Grid")
    
    code = f'''import matplotlib.pyplot as plt
import numpy as np

data = {data}

fig, ax = plt.subplots(figsize=(6, 4))
ax.axis('off')

table = ax.table(
    cellText=data,
    rowLabels={row_labels},
    colLabels={col_labels},
    cellLoc='center',
    loc='center'
)
table.auto_set_font_size(False)
table.set_fontsize(12)
table.scale(1.2, 1.5)

plt.title("{title}", fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
'''
    return code


def _render_line_chart(params: dict) -> str:
    """Render a line chart."""
    x_values = params.get("x_values", [1, 2, 3, 4, 5])
    y_values = params.get("y_values", [10, 15, 12, 18, 20])
    title = params.get("title", "Line Chart")
    xlabel = params.get("xlabel", "X")
    ylabel = params.get("ylabel", "Y")
    
    code = f'''import matplotlib.pyplot as plt

x = {x_values}
y = {y_values}

plt.figure(figsize=(8, 5))
plt.plot(x, y, marker='o', linewidth=2, markersize=8)
plt.title("{title}")
plt.xlabel("{xlabel}")
plt.ylabel("{ylabel}")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("output.png", dpi=150)
'''
    return code


def _render_venn(params: dict) -> str:
    """Render a Venn diagram."""
    set_a_label = params.get("set_a_label", "A")
    set_b_label = params.get("set_b_label", "B")
    set_a_only = params.get("set_a_only", "Only A")
    set_b_only = params.get("set_b_only", "Only B")
    intersection = params.get("intersection", "A ∩ B")
    title = params.get("title", "Venn Diagram")
    
    code = f'''import matplotlib.pyplot as plt
from matplotlib_venn import venn2

plt.figure(figsize=(8, 6))
v = venn2(subsets=(1, 1, 0.5), set_labels=('{set_a_label}', '{set_b_label}'))

# Custom labels
if v.get_label_by_id('10'):
    v.get_label_by_id('10').set_text('{set_a_only}')
if v.get_label_by_id('01'):
    v.get_label_by_id('01').set_text('{set_b_only}')
if v.get_label_by_id('11'):
    v.get_label_by_id('11').set_text('{intersection}')

plt.title("{title}")
plt.tight_layout()
plt.savefig("output.png", dpi=150)
'''
    return code


# =============================================================================
# FALLBACK TEMPLATES (for abstract/generic concepts)
# =============================================================================

def _render_concept_box(params: dict) -> str:
    """Render a simple concept box for abstract ideas."""
    title = params.get("title", "Concept")
    points = params.get("points", ["Point 1", "Point 2"])
    color = params.get("color", "#E8F5E9")
    
    lines = [
        "digraph {",
        "    rankdir=TB;",
        f'    node [shape=box, style="filled,rounded", fillcolor="{color}", fontsize=14];',
        f'    title [label="{title}" fontsize=16 fontcolor="#1B5E20" fillcolor="#C8E6C9"];',
    ]
    
    # Add points as connected boxes
    for i, point in enumerate(points):
        lines.append(f'    p{i} [label="{point}"];')
        lines.append(f"    title -> p{i};")
    
    lines.append("}")
    return "\n".join(lines)


def _render_info_card(params: dict) -> str:
    """Render an info card with key-value pairs."""
    title = params.get("title", "Information")
    items = params.get("items", [{"key": "Key", "value": "Value"}])
    
    lines = [
        "digraph {",
        "    rankdir=TB;",
        '    node [shape=none];',
    ]
    
    # Build HTML-like table
    table_rows = [f'<TR><TD COLSPAN="2" BGCOLOR="#1976D2"><FONT COLOR="white"><B>{title}</B></FONT></TD></TR>']
    for item in items:
        key = item.get("key", "")
        value = item.get("value", "")
        table_rows.append(f'<TR><TD BGCOLOR="#BBDEFB"><B>{key}</B></TD><TD BGCOLOR="#E3F2FD">{value}</TD></TR>')
    
    table_content = "\n".join(table_rows)
    lines.append(f'    card [label=<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">{table_content}</TABLE>>];')
    
    lines.append("}")
    return "\n".join(lines)


def _render_definition_box(params: dict) -> str:
    """Render a definition box for terms and definitions."""
    term = params.get("term", "Term")
    definition = params.get("definition", "Definition goes here")
    examples = params.get("examples", [])
    
    lines = ["graph TD"]
    lines.append(f'    term["{term}"]')
    lines.append(f'    def["{definition}"]')
    lines.append("    term --> def")
    
    for i, ex in enumerate(examples):
        lines.append(f'    ex{i}["Example: {ex}"]')
        lines.append(f"    def --> ex{i}")
    
    return "\n".join(lines)


# =============================================================================
# TEMPLATE REGISTRY INITIALIZATION
# =============================================================================

TEMPLATE_REGISTRY = TemplateRegistry()

# Register Graphviz templates
TEMPLATE_REGISTRY.register(Template(
    id="linear_chain",
    name="Linear Chain / Linked List",
    description="A sequence of connected nodes pointing to the next",
    renderer=Renderer.GRAPHVIZ,
    keywords=["linked list", "chain", "sequence", "pointer", "next", "node", "singly"],
    required_params=["nodes"],
    optional_params=["direction", "show_null"],
    render_func=_render_linear_chain,
))

TEMPLATE_REGISTRY.register(Template(
    id="binary_tree",
    name="Binary Tree",
    description="A tree with root, left, and right children",
    renderer=Renderer.GRAPHVIZ,
    keywords=["tree", "binary", "root", "left", "right", "child", "parent", "hierarchy"],
    required_params=["root"],
    optional_params=["left", "right", "left_children", "right_children"],
    render_func=_render_binary_tree,
))

TEMPLATE_REGISTRY.register(Template(
    id="stack",
    name="Stack Data Structure",
    description="LIFO stack with push/pop operations",
    renderer=Renderer.GRAPHVIZ,
    keywords=["stack", "LIFO", "push", "pop", "top", "last in first out"],
    required_params=["items"],
    optional_params=["top_label"],
    render_func=_render_stack,
))

TEMPLATE_REGISTRY.register(Template(
    id="queue",
    name="Queue Data Structure", 
    description="FIFO queue with enqueue/dequeue operations",
    renderer=Renderer.GRAPHVIZ,
    keywords=["queue", "FIFO", "enqueue", "dequeue", "front", "back", "first in first out"],
    required_params=["items"],
    optional_params=["front_label", "back_label"],
    render_func=_render_queue,
))

TEMPLATE_REGISTRY.register(Template(
    id="graph",
    name="Generic Graph",
    description="Nodes connected by edges",
    renderer=Renderer.GRAPHVIZ,
    keywords=["graph", "network", "vertices", "edges", "connected"],
    required_params=["nodes", "edges"],
    optional_params=["directed"],
    render_func=_render_graph,
))

TEMPLATE_REGISTRY.register(Template(
    id="layers",
    name="Layered Architecture",
    description="Stacked layers from top to bottom",
    renderer=Renderer.GRAPHVIZ,
    keywords=["layer", "architecture", "stack", "OSI", "model", "levels"],
    required_params=["layers"],
    optional_params=[],
    render_func=_render_layers,
))

# Register Mermaid templates
TEMPLATE_REGISTRY.register(Template(
    id="flowchart",
    name="Flowchart with Decisions",
    description="Process flow with decision points",
    renderer=Renderer.MERMAID,
    keywords=["flowchart", "if", "else", "decision", "condition", "branch", "algorithm"],
    required_params=["nodes", "edges"],
    optional_params=["direction"],
    render_func=_render_flowchart,
))

TEMPLATE_REGISTRY.register(Template(
    id="sequence",
    name="Sequence Diagram",
    description="Actors sending messages to each other",
    renderer=Renderer.MERMAID,
    keywords=["sequence", "message", "actor", "communication", "protocol", "call"],
    required_params=["actors", "messages"],
    optional_params=[],
    render_func=_render_sequence,
))

TEMPLATE_REGISTRY.register(Template(
    id="cycle",
    name="Cycle / Loop Diagram",
    description="Circular process that repeats",
    renderer=Renderer.MERMAID,
    keywords=["cycle", "loop", "circular", "repeat", "continuous"],
    required_params=["nodes"],
    optional_params=["title"],
    render_func=_render_cycle,
))

TEMPLATE_REGISTRY.register(Template(
    id="comparison",
    name="Side-by-Side Comparison",
    description="Compare two options or concepts",
    renderer=Renderer.MERMAID,
    keywords=["compare", "comparison", "versus", "vs", "difference", "pros", "cons"],
    required_params=["left_items", "right_items"],
    optional_params=["left_title", "right_title"],
    render_func=_render_comparison,
))

TEMPLATE_REGISTRY.register(Template(
    id="timeline",
    name="Timeline",
    description="Events along a time axis",
    renderer=Renderer.MERMAID,
    keywords=["timeline", "history", "events", "chronological", "time", "dates"],
    required_params=["events"],
    optional_params=["title"],
    render_func=_render_timeline,
))

TEMPLATE_REGISTRY.register(Template(
    id="process_flow",
    name="Simple Process Flow",
    description="Sequential steps in a process",
    renderer=Renderer.MERMAID,
    keywords=["process", "steps", "flow", "procedure", "workflow", "then"],
    required_params=["steps"],
    optional_params=["direction"],
    render_func=_render_process_flow,
))

# Register Matplotlib templates
TEMPLATE_REGISTRY.register(Template(
    id="bar_chart",
    name="Bar Chart",
    description="Categorical data comparison",
    renderer=Renderer.MATPLOTLIB,
    keywords=["bar", "chart", "compare", "categories", "frequency", "count"],
    required_params=["labels", "values"],
    optional_params=["title", "xlabel", "ylabel"],
    render_func=_render_bar_chart,
))

TEMPLATE_REGISTRY.register(Template(
    id="pie_chart",
    name="Pie Chart",
    description="Proportional data visualization",
    renderer=Renderer.MATPLOTLIB,
    keywords=["pie", "chart", "proportion", "percentage", "share", "distribution"],
    required_params=["labels", "values"],
    optional_params=["title"],
    render_func=_render_pie_chart,
))

TEMPLATE_REGISTRY.register(Template(
    id="grid",
    name="Grid / Table",
    description="Tabular data display",
    renderer=Renderer.MATPLOTLIB,
    keywords=["table", "grid", "matrix", "cells", "rows", "columns"],
    required_params=["data"],
    optional_params=["row_labels", "col_labels", "title"],
    render_func=_render_grid,
))

TEMPLATE_REGISTRY.register(Template(
    id="line_chart",
    name="Line Chart",
    description="Trend over continuous data",
    renderer=Renderer.MATPLOTLIB,
    keywords=["line", "chart", "trend", "growth", "over time", "continuous"],
    required_params=["x_values", "y_values"],
    optional_params=["title", "xlabel", "ylabel"],
    render_func=_render_line_chart,
))

TEMPLATE_REGISTRY.register(Template(
    id="venn",
    name="Venn Diagram",
    description="Set relationships and intersections",
    renderer=Renderer.MATPLOTLIB,
    keywords=["venn", "set", "intersection", "union", "overlap", "common"],
    required_params=["set_a_label", "set_b_label"],
    optional_params=["set_a_only", "set_b_only", "intersection", "title"],
    render_func=_render_venn,
))

# Register Fallback templates (for abstract/generic concepts)
TEMPLATE_REGISTRY.register(Template(
    id="concept_box",
    name="Concept Box (Fallback)",
    description="General-purpose diagram for abstract concepts that don't fit other templates",
    renderer=Renderer.GRAPHVIZ,
    keywords=["concept", "idea", "abstract", "general", "overview", "summary", "main points"],
    required_params=["title"],
    optional_params=["points", "color"],
    render_func=_render_concept_box,
))

TEMPLATE_REGISTRY.register(Template(
    id="info_card",
    name="Info Card (Fallback)",
    description="Key-value information display for facts, properties, or characteristics",
    renderer=Renderer.GRAPHVIZ,
    keywords=["info", "information", "properties", "characteristics", "facts", "details", "attributes"],
    required_params=["title", "items"],
    optional_params=[],
    render_func=_render_info_card,
))

TEMPLATE_REGISTRY.register(Template(
    id="definition_box",
    name="Definition Box (Fallback)",
    description="Term and definition with optional examples",
    renderer=Renderer.MERMAID,
    keywords=["definition", "term", "meaning", "what is", "define", "explain"],
    required_params=["term", "definition"],
    optional_params=["examples"],
    render_func=_render_definition_box,
))

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_template(template_id: str) -> Template | None:
    """Get a template by ID."""
    return TEMPLATE_REGISTRY.get(template_id)


def render_template(template_id: str, params: dict[str, Any]) -> tuple[str, str]:
    """
    Render a template with given parameters.
    
    Returns:
        Tuple of (renderer_type, rendered_code)
    """
    return TEMPLATE_REGISTRY.render(template_id, params)


def list_templates() -> list[dict[str, Any]]:
    """List all available templates with their metadata."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "renderer": t.renderer.value,
            "keywords": t.keywords,
            "required_params": t.required_params,
            "optional_params": t.optional_params,
        }
        for t in TEMPLATE_REGISTRY.list_all()
    ]
