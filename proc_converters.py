# Additional PROC converters for SAS to Python conversion
import re
import logging

logger = logging.getLogger('SASPythonConverter')

def convert_proc_corr(component):
    """Convert PROC CORR to pandas correlation."""
    try:
        content = component.content
        data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
        var_match = re.search(r'var\s+(.*?);', content, re.IGNORECASE)
        with_match = re.search(r'with\s+(.*?);', content, re.IGNORECASE)
        
        if not data_match:
            return "# TODO: Convert PROC CORR - no dataset specified"
        
        dataset = data_match.group(1).replace('.', '_')
        dataset_df = f"{dataset}_df"
        
        # Extract variables
        if var_match:
            variables = [v.strip() for v in var_match.group(1).split()]
            var_list = ", ".join([f"'{v}'" for v in variables])
            var_code = f"variables = [{var_list}]"
        else:
            var_code = "# No specific variables specified, using all numeric columns"
            var_list = "None"
        
        # Extract WITH variables for partial correlation
        with_vars = []
        if with_match:
            with_vars = [v.strip() for v in with_match.group(1).split()]
            with_list = ", ".join([f"'{v}'" for v in with_vars])
            with_code = f"with_variables = [{with_list}]"
        else:
            with_code = "# No WITH variables specified"
            with_list = "None"
        
        # Generate correlation code
        code = [
            f"# Calculate correlations for {dataset}",
            var_code,
            with_code,
            "",
            f"# Select numeric columns if no variables specified",
            f"if {var_list} is None:",
            f"    corr_df = {dataset_df}.select_dtypes(include=['number'])",
            f"else:",
            f"    corr_df = {dataset_df}[variables]",
            "",
            f"# Calculate correlation matrix",
            f"correlation_matrix = corr_df.corr()",
            f"print('Correlation Matrix:')",
            f"print(correlation_matrix)",
            "",
            f"# Create correlation heatmap",
            f"plt.figure(figsize=(10, 8))",
            f"sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', vmin=-1, vmax=1)",
            f"plt.title('Correlation Heatmap')",
            f"plt.tight_layout()",
            f"plt.show()"
        ]
        
        return "\n".join(code)
        
    except Exception as e:
        logger.warning(f"Error converting PROC CORR: {str(e)}")
        return f"# TODO: Convert PROC CORR:\n# {component.content}"

def convert_proc_reg(component):
    """Convert PROC REG to scipy/statsmodels regression."""
    try:
        content = component.content
        data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
        model_match = re.search(r'model\s+(\w+)\s*=\s*([^;]+);', content, re.IGNORECASE)
        
        if not data_match or not model_match:
            return "# TODO: Convert PROC REG - missing dataset or model specification"
        
        dataset = data_match.group(1).replace('.', '_')
        dataset_df = f"{dataset}_df"
        
        # Extract dependent and independent variables
        dependent_var = model_match.group(1).strip()
        independent_vars = [v.strip() for v in model_match.group(2).split()]
        
        # Generate regression code
        indep_vars_list = ", ".join([f"'{v}'" for v in independent_vars])
        
        code = [
            f"# Linear regression analysis for {dataset}",
            f"from statsmodels.formula.api import ols",
            f"from statsmodels.stats.anova import anova_lm",
            "",
            f"# Define dependent and independent variables",
            f"dependent_var = '{dependent_var}'",
            f"independent_vars = [{indep_vars_list}]",
            "",
            f"# Create formula for regression",
            f"formula = dependent_var + ' ~ ' + ' + '.join(independent_vars)",
            "",
            f"# Fit regression model",
            f"model = ols(formula, data={dataset_df}).fit()",
            f"print(model.summary())",
            "",
            f"# ANOVA table",
            f"anova_table = anova_lm(model)",
            f"print('\nANOVA Results:')",
            f"print(anova_table)",
            "",
            f"# Plot residuals",
            f"plt.figure(figsize=(12, 6))",
            f"plt.subplot(1, 2, 1)",
            f"plt.scatter(model.fittedvalues, model.resid)",
            f"plt.xlabel('Fitted values')",
            f"plt.ylabel('Residuals')",
            f"plt.title('Residuals vs Fitted')",
            f"plt.axhline(y=0, color='r', linestyle='-')",
            "",
            f"plt.subplot(1, 2, 2)",
            f"import scipy.stats as stats",
            f"stats.probplot(model.resid, plot=plt)",
            f"plt.title('Normal Q-Q')",
            f"plt.tight_layout()"
        ]
        
        return "\n".join(code)
        
    except Exception as e:
        logger.warning(f"Error converting PROC REG: {str(e)}")
        return f"# TODO: Convert PROC REG:\n# {component.content}"

def convert_proc_sgplot(component):
    """Convert PROC SGPLOT to matplotlib/seaborn plots."""
    try:
        content = component.content
        data_match = re.search(r'data\s*=\s*(\S+)', content, re.IGNORECASE)
        
        if not data_match:
            return "# TODO: Convert PROC SGPLOT - no dataset specified"
        
        dataset = data_match.group(1).replace('.', '_')
        dataset_df = f"{dataset}_df"
        
        # Identify plot type and variables
        scatter_match = re.search(r'scatter\s+x\s*=\s*(\w+)\s+y\s*=\s*(\w+)', content, re.IGNORECASE)
        series_match = re.search(r'series\s+x\s*=\s*(\w+)\s+y\s*=\s*(\w+)', content, re.IGNORECASE)
        histogram_match = re.search(r'histogram\s+(\w+)', content, re.IGNORECASE)
        vbar_match = re.search(r'vbar\s+(\w+)', content, re.IGNORECASE)
        hbar_match = re.search(r'hbar\s+(\w+)', content, re.IGNORECASE)
        
        # Extract title if present
        title_match = re.search(r'title\s*=\s*[\'"]([^\'"]+)[\'"]', content, re.IGNORECASE)
        title = f"'{title_match.group(1)}'" if title_match else "'SGPLOT Visualization'"
        
        code = [f"# Create visualization for {dataset}", f"plt.figure(figsize=(10, 6))"]
        
        if scatter_match:
            x_var = scatter_match.group(1)
            y_var = scatter_match.group(2)
            code.extend([
                f"# Create scatter plot",
                f"plt.scatter({dataset_df}['{x_var}'], {dataset_df}['{y_var}'])",
                f"plt.xlabel('{x_var}')",
                f"plt.ylabel('{y_var}')",
                f"plt.title({title})"
            ])
        
        elif series_match:
            x_var = series_match.group(1)
            y_var = series_match.group(2)
            code.extend([
                f"# Create line plot",
                f"plt.plot({dataset_df}['{x_var}'], {dataset_df}['{y_var}'])",
                f"plt.xlabel('{x_var}')",
                f"plt.ylabel('{y_var}')",
                f"plt.title({title})"
            ])
        
        elif histogram_match:
            var = histogram_match.group(1)
            code.extend([
                f"# Create histogram",
                f"plt.hist({dataset_df}['{var}'], bins=20, alpha=0.7)",
                f"plt.xlabel('{var}')",
                f"plt.ylabel('Frequency')",
                f"plt.title({title})"
            ])
        
        elif vbar_match:
            var = vbar_match.group(1)
            code.extend([
                f"# Create vertical bar chart",
                f"{dataset_df}['{var}'].value_counts().plot(kind='bar')",
                f"plt.xlabel('{var}')",
                f"plt.ylabel('Count')",
                f"plt.title({title})",
                f"plt.xticks(rotation=45)"
            ])
        
        elif hbar_match:
            var = hbar_match.group(1)
            code.extend([
                f"# Create horizontal bar chart",
                f"{dataset_df}['{var}'].value_counts().plot(kind='barh')",
                f"plt.xlabel('Count')",
                f"plt.ylabel('{var}')",
                f"plt.title({title})"
            ])
        
        else:
            code.extend([
                f"# TODO: Unrecognized SGPLOT type",
                f"# Original SAS code:",
                f"# {content.strip()}",
                f"plt.title({title})"
            ])
        
        code.extend(["plt.tight_layout()", "plt.show()"])
        
        return "\n".join(code)
        
    except Exception as e:
        logger.warning(f"Error converting PROC SGPLOT: {str(e)}")
        return f"# TODO: Convert PROC SGPLOT:\n# {component.content}"