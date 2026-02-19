from setuptools import find_packages, setup

setup(
    name="personal-finance-dashboard",
    version="0.1.0",
    description="Local-first personal finance dashboard using Streamlit and DuckDB",
    packages=find_packages(include=["finance_core*", "app*"]),
    python_requires=">=3.11",
)
