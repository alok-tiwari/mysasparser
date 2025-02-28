# Auto-generated Python code from SAS file: analysis.sas
# Generated on: 2025-02-28 01:37:18

import pandas as pd
import numpy as np
from scipy import stats
import os
import matplotlib.pyplot as plt
import seaborn as sns

# Configure plotting
plt.style.use('seaborn')
sns.set_theme()


# Load required datasets

# --------------------------------------------------
# %LET: alpha (Lines 4-4)
# --------------------------------------------------
alpha = 0.05


# --------------------------------------------------
# %LET: min_obs (Lines 5-7)
# --------------------------------------------------
min_obs = 1000


# --------------------------------------------------
# PROC: format (Lines 8-8)
# --------------------------------------------------
# ERROR converting PROC - format: 'SASPythonConverter' object has no attribute '_convert_proc_print'
# Original code:
# proc format;


# --------------------------------------------------
# MACRO: analyze_segment (Lines 23-23)
# --------------------------------------------------
def analyze_segment(data, segment, var):
    """Analyze a segment of data with statistical tests and plots."""
    # Filter data for segment
    segment_data = data[data['segment'] == segment]

    # Check if enough observations
    if len(segment_data) < min_obs:
        print(f"WARNING: Insufficient observations for {segment}")
        return

    # Calculate summary statistics
    stats = segment_data[var].describe()
    print(f"Statistics for {var} in segment {segment}:")
    print(stats)

    # Detailed analysis
    # Normality test
    stat, p_value = stats.normaltest(segment_data[var].dropna())
    print(f"Normality test: stat={stat:.4f}, p-value={p_value:.4f}")

    # Visualizations
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))

    # Histogram
    sns.histplot(data=segment_data, x=var, kde=True, ax=ax1)
    ax1.set_title(f"Distribution of {var}")

    # Box plot
    sns.boxplot(y=segment_data[var], ax=ax2)
    ax2.set_title("Box Plot")

    # Q-Q plot
    stats.probplot(segment_data[var].dropna(), plot=ax3)
    ax3.set_title("Q-Q Plot")

    plt.tight_layout()
    plt.show()


# --------------------------------------------------
# PROC: means (Lines 25-25)
# --------------------------------------------------
# ERROR converting PROC - means: 'SASPythonConverter' object has no attribute '_convert_proc_print'
# Original code:
#  
# proc means data=&data noprint;


# --------------------------------------------------
# DATA: _null_ (Lines 37-37)
# --------------------------------------------------
# Create a new DataFrame
_null__df = pd.DataFrame()


# --------------------------------------------------
# %IF:  (Lines 46-47)
# --------------------------------------------------
if skip_analysis == 0:
    # TODO: Convert macro action: %do


# --------------------------------------------------
# PROC: univariate (Lines 48-48)
# --------------------------------------------------
# ERROR converting PROC - univariate: 'SASPythonConverter' object has no attribute '_convert_proc_print'
# Original code:
# proc univariate data=&data normal plot;


# --------------------------------------------------
# PROC: ttest (Lines 57-57)
# --------------------------------------------------
# ERROR converting PROC - ttest: 'SASPythonConverter' object has no attribute '_convert_proc_print'
# Original code:
#  
# proc ttest data=&data h0=0 alpha=&alpha;


# --------------------------------------------------
# MACRO: run_analysis (Lines 73-73)
# --------------------------------------------------
# ERROR converting MACRO - run_analysis
# Original code:
#  
%macro run_analysis;


# --------------------------------------------------
# %LET: i (Lines 74-74)
# --------------------------------------------------
i = 1


# --------------------------------------------------
# %LET: segment (Lines 75-75)
# --------------------------------------------------
segment = '%scan(&segment_list, &i)'


# --------------------------------------------------
# %DO:  (Lines 76-81)
# --------------------------------------------------
while segment != "":


# --------------------------------------------------
# %LET: i (Lines 82-82)
# --------------------------------------------------
i = '%eval(&i + 1)'


# --------------------------------------------------
# %LET: segment (Lines 83-85)
# --------------------------------------------------
segment = '%scan(&segment_list, &i)'


# --------------------------------------------------
# ODS:  (Lines 91-91)
# --------------------------------------------------
# Enable Matplotlib and seaborn for graphics
import matplotlib.pyplot as plt
import seaborn as sns
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['figure.dpi'] = 100


# --------------------------------------------------
# ODS:  (Lines 92-95)
# --------------------------------------------------
# Setup output directory for HTML reports
import os
output_dir = './output'
os.makedirs(output_dir, exist_ok=True)
html_file = os.path.join(output_dir, 'analysis_report.html')


# --------------------------------------------------
# TITLE:  (Lines 96-96)
# --------------------------------------------------
# Set plot title
plt.suptitle("Statistical Analysis Report", fontsize=14)
title_1 = "Statistical Analysis Report"


# --------------------------------------------------
# TITLE:  (Lines 97-98)
# --------------------------------------------------
# Set plot title
plt.suptitle("By Segment", fontsize=12)
title_2 = "By Segment"


# --------------------------------------------------
# PROC_R: R (Lines 99-99)
# --------------------------------------------------
# TODO: Convert PROC_R - R
# Original code:
# proc report data=WORK.analysis_data;


# --------------------------------------------------
# ODS:  (Lines 109-109)
# --------------------------------------------------
# Complete HTML output
# If using a library like pandas HTML output:
# with open(html_file, 'w') as f:
#     f.write(html_content)


# --------------------------------------------------
# ODS:  (Lines 110-110)
# --------------------------------------------------
# Close all open plots
plt.close('all')


# Execute main code when run directly
if __name__ == '__main__':
    # Add your main execution code here
    pass