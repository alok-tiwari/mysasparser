# Auto-generated Python code from SAS file: analysis.sas
# Generated on: 2025-02-28 02:17:55

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

def load_sashelp_dataset(name: str) -> pd.DataFrame:
    """Load a dataset from sashelp library."""
    try:
        return pd.read_csv(f'sashelp_{name.lower()}.csv')
    except Exception as e:
        print(f'Error loading sashelp.{name}: {e}')
        return pd.DataFrame()

# Initialize _null_ dataset
_null__df = pd.DataFrame()

# Initialize h0 dataset
h0_df = pd.DataFrame()

# Initialize noprint dataset
noprint_df = pd.DataFrame()

# Initialize normal dataset
normal_df = pd.DataFrame()

# --------------------------------------------------
# %LET: alpha (Lines 4-4)
# --------------------------------------------------
alpha = 0.05


# --------------------------------------------------
# %LET: min_obs (Lines 5-7)
# --------------------------------------------------
min_obs = 1000


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
# ERROR converting PROC - MEANS: name 'stats' is not defined
# Original code:
 
proc means data=&data noprint;


# --------------------------------------------------
# %IF:  (Lines 46-47)
# --------------------------------------------------
if skip_analysis == 0:
    # TODO: Convert macro action: %do


# --------------------------------------------------
# PROC: univariate (Lines 48-48)
# --------------------------------------------------
# Calculate detailed statistics
from scipy import stats

# Analyze all numeric columns
numeric_cols = df.select_dtypes(include=[np.number]).columns
for col in numeric_cols:
    print(f'\nAnalysis for {col}:')
    data = df[col].dropna()
    print(data.describe())


# --------------------------------------------------
# PROC: ttest (Lines 57-57)
# --------------------------------------------------
# T-test analysis
from scipy import stats
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
# One-sample t-test (H0: mean = 0)


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
# Enable high-quality graphics
import matplotlib.pyplot as plt
import seaborn as sns
plt.style.use('seaborn')
plt.rcParams.update({
    'figure.figsize': (10, 6),
    'figure.dpi': 100,
    'savefig.dpi': 300,
    'font.size': 10,
    'axes.titlesize': 12,
    'axes.labelsize': 10,
    'axes.grid': True
})
sns.set_theme(style='whitegrid')


# --------------------------------------------------
# ODS:  (Lines 92-95)
# --------------------------------------------------
# Setup HTML output
import os
output_dir = './output'
os.makedirs(output_dir, exist_ok=True)
html_file = os.path.join(output_dir, 'analysis_report.html')
html_content = []


# --------------------------------------------------
# TITLE:  (Lines 96-96)
# --------------------------------------------------
title_ = "Statistical Analysis Report"
plt.suptitle("Statistical Analysis Report", fontsize=14)


# --------------------------------------------------
# TITLE:  (Lines 97-98)
# --------------------------------------------------
title_ = "By Segment"
plt.suptitle("By Segment", fontsize=14)


# --------------------------------------------------
# PROC_R: R (Lines 99-99)
# --------------------------------------------------
# TODO: Convert PROC_R - R
# Original code:
# proc report data=WORK.analysis_data;


# --------------------------------------------------
# ODS:  (Lines 109-109)
# --------------------------------------------------
# Close HTML output
if 'html_file' in locals():
    with open(html_file, 'w') as f:
        f.write(html_content)


# --------------------------------------------------
# ODS:  (Lines 110-110)
# --------------------------------------------------
# Close all plots
plt.close('all')


# Execute main code when run directly
if __name__ == '__main__':
    # Add your main execution code here
    pass