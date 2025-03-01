import yaml
from jinja2 import Environment, BaseLoader, Template
from typing import Dict, Any, List
import logging
import re

logger = logging.getLogger(__name__)

class TemplateLoader:
    def __init__(self, template_file: str):
        """Initialize template loader with YAML template file."""
        self.env = Environment(loader=BaseLoader())
        
        # Add custom filters
        self.env.filters['join_quotes'] = self._join_quotes
        
        # Load templates
        with open(template_file, 'r') as f:
            self.templates = yaml.safe_load(f)
    
    def _join_quotes(self, items: list) -> str:
        """Join items with quotes and commas."""
        return ", ".join(f"'{item}'" for item in items)
    
    def get_template(self, template_name: str) -> Template:
        """Get a template by name."""
        if template_name not in self.templates:
            raise ValueError(f"Template {template_name} not found")
        return self.env.from_string(self.templates[template_name]['template'])
    
    def render_template(self, template_name: str, **kwargs: Any) -> str:
        """Render a template with given parameters."""
        try:
            template = self.get_template(template_name)
            return template.render(**kwargs)
        except ValueError as e:
            logger.error(f"Template error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error rendering template {template_name}: {str(e)}")
            raise

    def validate_template(self, template_name: str, params: Dict[str, Any]) -> bool:
        """Validate that all required parameters are present."""
        template = self.get_template(template_name)
        required_params = self._get_required_params(template)
        return all(param in params for param in required_params)

    def _get_required_params(self, template: Template) -> List[str]:
        """Extract required parameters from template."""
        params = re.findall(r'{{\s*(\w+)', template.source)
        # Remove duplicates and filter out special variables
        return list(set([p for p in params if p not in ['loop', 'if', 'else', 'endif']]))

    def get_template_info(self, template_name: str) -> Dict[str, Any]:
        """Get template information including required parameters."""
        if template_name not in self.templates:
            raise ValueError(f"Template {template_name} not found")
            
        template = self.templates[template_name]
        template_obj = self.env.from_string(template['template'])
        
        return {
            'name': template_name,
            'required_params': self._get_required_params(template_obj),
            'description': template.get('description', ''),
            'example': template.get('example', '')
        } 