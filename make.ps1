# Thin PowerShell mapping over the Makefile targets.
# It mirrors the same commands; it does not reimplement simulator or experiment logic.
# Usage: .\make.ps1 <target>   e.g.  .\make.ps1 test
param(
    [Parameter(Position = 0)]
    [string]$Target = "help"
)

$python = "python"

switch ($Target) {
    "help" {
        Write-Host "Targets:"
        Write-Host "  install     Install the project in editable mode"
        Write-Host "  test        Run the unittest suite (same command as CI)"
        Write-Host "  reference   Run the reference trace validator (same command as CI)"
        Write-Host "  experiments Run the batch experiment scaffold"
        Write-Host "  figures     Generate figures from committed experiment tables"
        Write-Host "  clean       Remove caches and build artifacts (keeps data/)"
    }
    "install" {
        & $python -m pip install -e .
    }
    "test" {
        & $python -m unittest discover -s tests -t . -v
    }
    "reference" {
        & $python -m cache_simulator.reference_validation
    }
    "experiments" {
        & $python -m cache_simulator.experiments
    }
    "figures" {
        & $python d_experiments/make_plots.py --results-dir data/results/main --tuning-dir data/results/h-tuning --figures-dir data/results/figures
    }
    "clean" {
        # Remove caches and build artifacts only; keep data/ and tracked results.
        Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
        Get-ChildItem -Path . -Recurse -File -Include "*.pyc", "*.pyo", "*.pyd" -ErrorAction SilentlyContinue |
            Remove-Item -Force
        foreach ($d in @("build", "dist", ".pytest_cache", ".ruff_cache")) {
            if (Test-Path $d) { Remove-Item -Recurse -Force $d }
        }
        Get-ChildItem -Path . -Recurse -Directory -Filter "*.egg-info" -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
    }
    default {
        Write-Host "Unknown target: $Target"
        exit 1
    }
}
