import pandas as pd
import numpy as np
from scipy import stats
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import os


# Initialize variables
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)



# Load required datasets

def load_sashelp_dataset(name: str) -> pd.DataFrame:
    """Load a dataset from sashelp library."""
    try:
        return pd.read_csv(f'sashelp_{name.lower()}.csv')
    except Exception as e:
        print(f'Error loading sashelp.{name}: {e}')
        return pd.DataFrame()

# Initialize filtered dataset
filtered_df = pd.DataFrame()

# Load sashelp.class
class_df = load_sashelp_dataset('class')
# Calculate descriptive statistics
class;_df_stats = class;_df.describe()
print(class;_df_stats)
# Create new DataFrame filtered
filtered_df = pd.DataFrame()
