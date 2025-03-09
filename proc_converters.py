import pandas as pd
import numpy as np
from typing import Dict, Any

def convert_proc_corr(component: Dict[str, Any]) -> str:
    """Convert PROC CORR to Python code."""
    try:
        content = component.get('content', '')
        # Extract dataset and variables
        dataset = component.get('dataset', 'data')
        vars_match = re.search(r'var\s+(.*?);', content)
        variables = vars_match.group(1).split() if vars_match else []
        
        return f"""
# Calculate correlations
corr_df = {dataset}_df[{variables}].corr()
print("\\nCorrelation Matrix:")
print(corr_df)

# Add descriptive statistics
print("\\nDescriptive Statistics:")
print({dataset}_df[{variables}].describe())
"""
    except Exception as e:
        return f"# Error converting PROC CORR: {str(e)}"

def convert_proc_reg(component: Dict[str, Any]) -> str:
    """Convert PROC REG to Python code."""
    try:
        content = component.get('content', '')
        dataset = component.get('dataset', 'data')
        model_match = re.search(r'model\s+(.*?)\s*=\s*(.*?);', content)
        if not model_match:
            return "# Error: No model statement found in PROC REG"
            
        dependent = model_match.group(1)
        independents = model_match.group(2).split()
        
        return f"""
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error
import numpy as np

# Prepare data
X = {dataset}_df[[{', '.join(f"'{x}'" for x in independents)}]]
y = {dataset}_df['{dependent}']

# Fit model
model = LinearRegression()
model.fit(X, y)

# Print results
print("\\nRegression Results:")
print(f"R-squared: {{r2_score(y, model.predict(X)):.4f}}")
print("\\nCoefficients:")
for var, coef in zip(X.columns, model.coef_):
    print(f"{{var}}: {{coef:.4f}}")
"""
    except Exception as e:
        return f"# Error converting PROC REG: {str(e)}"

def convert_proc_sgplot(component: Dict[str, Any]) -> str:
    """Convert PROC SGPLOT to Python code using matplotlib/seaborn."""
    try:
        content = component.get('content', '')
        dataset = component.get('dataset', 'data')
        
        # Extract plot type and variables
        scatter_match = re.search(r'scatter\s+x\s*=\s*(\w+)\s+y\s*=\s*(\w+)', content)
        histogram_match = re.search(r'histogram\s+(\w+)', content)
        
        if scatter_match:
            x_var, y_var = scatter_match.group(1), scatter_match.group(2)
            return f"""
import matplotlib.pyplot as plt
import seaborn as sns

plt.figure(figsize=(10, 6))
sns.scatterplot(data={dataset}_df, x='{x_var}', y='{y_var}')
plt.title('Scatter Plot of {y_var} vs {x_var}')
plt.show()
"""
        elif histogram_match:
            var = histogram_match.group(1)
            return f"""
import matplotlib.pyplot as plt
import seaborn as sns

plt.figure(figsize=(10, 6))
sns.histplot(data={dataset}_df, x='{var}')
plt.title('Histogram of {var}')
plt.show()
"""
        else:
            return "# Error: Unsupported SGPLOT statement"
            
    except Exception as e:
        return f"# Error converting PROC SGPLOT: {str(e)}" 