import yaml
from jinja2 import Environment, BaseLoader, Template
from typing import Dict, Any, List
import logging
import re

logger = logging.getLogger(__name__)

class TemplateError(Exception):
    """Base class for template errors."""
    pass

class TemplateNotFoundError(TemplateError):
    """Raised when template is not found."""
    pass

class TemplateRenderError(TemplateError):
    """Raised when template rendering fails."""
    pass

class TemplateValidationError(TemplateError):
    """Raised when template validation fails."""
    pass

class TemplateLoader:
    def __init__(self, template_file: str):
        """Initialize template loader with YAML template file."""
        self.env = Environment(loader=BaseLoader())
        
        # Add custom filters
        self.env.filters['join_quotes'] = self._join_quotes
        
        try:
            with open(template_file, 'r') as f:
                self.templates = yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Template file not found: {template_file}")
            raise TemplateError(f"Template file not found: {template_file}")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML template file: {e}")
            raise TemplateError(f"Invalid YAML in template file: {e}")
    
    def _join_quotes(self, items: list) -> str:
        """Join items with quotes and commas."""
        return ", ".join(f"'{item}'" for item in items)
    
    def get_template(self, template_name: str) -> Template:
        """Get a template by name with enhanced error handling."""
        try:
            if template_name not in self.templates:
                raise TemplateNotFoundError(f"Template {template_name} not found")
            
            template_data = self.templates[template_name]
            if not isinstance(template_data, dict) or 'template' not in template_data:
                raise TemplateValidationError(f"Invalid template structure for {template_name}")
            
            return self.env.from_string(template_data['template'])
        except Exception as e:
            logger.error(f"Error getting template {template_name}: {str(e)}")
            raise
    
    def render_template(self, template_name: str, **kwargs: Any) -> str:
        """Render a template with enhanced error handling."""
        try:
            template = self.get_template(template_name)
            
            # Validate required parameters
            missing_params = self._get_missing_params(template, kwargs)
            if missing_params:
                raise TemplateValidationError(
                    f"Missing required parameters for {template_name}: {', '.join(missing_params)}"
                )
            
            return template.render(**kwargs)
        except TemplateError:
            raise
        except Exception as e:
            logger.error(f"Error rendering template {template_name}: {str(e)}")
            raise TemplateRenderError(f"Failed to render template {template_name}: {str(e)}")

    def _get_missing_params(self, template: Template, params: Dict[str, Any]) -> List[str]:
        """Get list of missing required parameters."""
        required = self._get_required_params(template)
        return [p for p in required if p not in params]

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

    def load_templates(self) -> Dict[str, Template]:
        """Load all templates from YAML file."""
        templates = {}
        try:
            for name, template_data in self.templates.items():
                if isinstance(template_data, dict) and 'template' in template_data:
                    templates[name] = self.env.from_string(template_data['template'])
                elif isinstance(template_data, dict):
                    # Handle nested templates
                    nested_templates = {}
                    for subname, subtemplate in template_data.items():
                        if isinstance(subtemplate, dict) and 'template' in subtemplate:
                            nested_templates[subname] = self.env.from_string(subtemplate['template'])
                    templates[name] = nested_templates
        except Exception as e:
            logger.error(f"Error loading templates: {str(e)}")
            raise
        return templates

    def validate_templates(self) -> bool:
        """Validate all templates with detailed error reporting."""
        validation_errors = []
        try:
            templates = self.load_templates()
            for name, template in templates.items():
                try:
                    if isinstance(template, dict):
                        for subname, subtemplate in template.items():
                            self._validate_single_template(subtemplate, f"{name}.{subname}")
                    else:
                        self._validate_single_template(template, name)
                except Exception as e:
                    validation_errors.append(f"{name}: {str(e)}")
            
            if validation_errors:
                error_msg = "\n".join(validation_errors)
                logger.error(f"Template validation failed:\n{error_msg}")
                return False
            return True
        except Exception as e:
            logger.error(f"Template validation failed: {str(e)}")
            return False

    def _validate_single_template(self, template: Template, name: str):
        """Validate a single template."""
        try:
            # Try rendering with minimal parameters
            template.render()
        except Exception as e:
            logger.error(f"Template {name} validation failed: {str(e)}")
            raise 