# Use Cases

## 1. When to Use This Kernel

This kernel is designed for scenarios where you need remote compute resources while maintaining a local development experience.

## 2. Use Case 1: Remote GPU/Memory Workloads

Run GPU-accelerated or memory-intensive workloads on Databricks while developing locally in JupyterLab.

### 2.1. Example: Deep Learning with PyTorch

```python
# All code runs on the remote cluster with GPU access
import torch

# Check GPU availability (remote GPU)
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"Device count: {torch.cuda.device_count()}")

# Create model on remote GPU
model = torch.nn.Sequential(
    torch.nn.Linear(784, 256),
    torch.nn.ReLU(),
    torch.nn.Linear(256, 10)
).cuda()

# Training runs on remote GPU
for epoch in range(10):
    # ... training code ...
    pass
```

### 2.2. Example: Large DataFrame Processing

```python
# Process large datasets using cluster memory
df = spark.read.parquet("/large-dataset/")  # Terabytes of data
print(f"Row count: {df.count():,}")

# Complex aggregations using cluster resources
result = df.groupBy("category").agg(
    {"value": "sum", "count": "avg"}
)
result.show()
```

## 3. Use Case 2: Local Module Development

Develop Python modules locally and seamlessly use them on the cluster.

### 3.1. Project Structure

```text
my-project/
├── src/
│   ├── __init__.py
│   ├── data_processing.py
│   └── models.py
├── notebooks/
│   └── analysis.ipynb
├── .databricks-kernel.yaml
└── .gitignore
```

### 3.2. Local Module

```python
# src/data_processing.py
def clean_data(df):
    return df.dropna().drop_duplicates()

def transform_features(df):
    # Complex transformations
    return df.withColumn("new_feature", ...)
```

### 3.3. Notebook Usage

```python
# In your notebook - modules are automatically synced
from src.data_processing import clean_data, transform_features

# Load and process data on the cluster
raw_df = spark.read.parquet("/raw-data/")
clean_df = clean_data(raw_df)
features_df = transform_features(clean_df)
```

### 3.4. Development Workflow

1. Edit `src/data_processing.py` locally
2. Run notebook cell - files sync automatically
3. Changes are immediately available on the cluster

## 4. Use Case 3: Team Collaboration

Share code through version control while each team member runs on their own cluster.

### 4.1. Setup

```yaml
# .databricks-kernel.yaml (not committed)
cluster_id: "team-member-cluster-id"
```

```gitignore
# .gitignore
.databricks-kernel.yaml
.databricks-kernel-cache.json
```

Each team member:

1. Clones the repository
2. Creates their own `.databricks-kernel.yaml` with their cluster ID
3. Runs notebooks on their assigned cluster

## 5. Comparison with Alternatives

| Feature | This Kernel | Databricks Connect | Databricks CLI |
|---------|-------------|-------------------|----------------|
| Architecture | Custom Jupyter Kernel | Python Library | CLI Tool |
| Python Execution | Remote cluster | Local machine | N/A |
| PySpark Execution | Remote cluster | Remote cluster | N/A |
| GPU Utilization | Remote GPU | Local only | N/A |
| File Sync | Automatic | Manual | Manual (sync command) |
| dbutils Support | Full | Limited | Full (in notebooks) |
| Local IDE | JupyterLab | Any IDE | N/A |
| Cluster State | Stateful session | Stateless calls | N/A |
| Use Case | Remote execution | Local development with remote Spark | Deployment & CI/CD |

### 5.1. When to Use Each Tool

#### 5.1.1. Use This Kernel When

- You need GPU or large memory resources
- All Python code should run remotely
- You want automatic file synchronization
- You prefer JupyterLab for development

#### 5.1.2. Use Databricks Connect When

- You want local Python execution with remote Spark
- You need IDE integration (VSCode, PyCharm)
- Local packages must be used
- You don't need GPU resources

#### 5.1.3. Use Databricks CLI When

- Deploying code to production
- Running in CI/CD pipelines
- Managing Databricks resources
- Syncing files manually

## 6. Example: Complete Workflow

### 6.1. Project Setup

```bash
# Create project
mkdir my-ml-project && cd my-ml-project

# Initialize
make install
make sync

# Configure cluster
echo 'cluster_id: "your-cluster-id"' > .databricks-kernel.yaml
```

### 6.2. Create Module

```python
# src/ml_pipeline.py
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.classification import RandomForestClassifier

def create_pipeline(feature_cols, label_col):
    assembler = VectorAssembler(
        inputCols=feature_cols,
        outputCol="features"
    )
    rf = RandomForestClassifier(
        labelCol=label_col,
        featuresCol="features"
    )
    return Pipeline(stages=[assembler, rf])
```

### 6.3. Develop in Notebook

```python
# notebook.ipynb
from src.ml_pipeline import create_pipeline

# Load data (on cluster)
df = spark.read.parquet("/training-data/")

# Create and train pipeline (on cluster)
pipeline = create_pipeline(["f1", "f2", "f3"], "label")
model = pipeline.fit(df)

# Evaluate (on cluster)
predictions = model.transform(df)
predictions.show()
```

### 6.4. Iterate

1. Modify `src/ml_pipeline.py` locally
2. Re-run notebook cells
3. Files automatically sync to cluster
4. New code executes on remote resources
