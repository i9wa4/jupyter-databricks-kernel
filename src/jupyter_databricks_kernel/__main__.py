"""Entry point for the Databricks kernel."""

from ipykernel.kernelapp import IPKernelApp

from .kernel import DatabricksKernel

if __name__ == "__main__":
    IPKernelApp.launch_instance(kernel_class=DatabricksKernel)
