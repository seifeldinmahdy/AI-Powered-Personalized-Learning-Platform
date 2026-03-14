"""Template library for visual generation."""

from slide_gen.templates.registry import (
    TemplateRegistry,
    get_template,
    render_template,
    list_templates,
    TEMPLATE_REGISTRY,
)

__all__ = [
    "TemplateRegistry",
    "get_template",
    "render_template",
    "list_templates",
    "TEMPLATE_REGISTRY",
]
