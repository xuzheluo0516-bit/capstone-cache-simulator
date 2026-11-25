# Thin PowerShell mapping over the Makefile targets.
# It mirrors the same commands; it does not reimplement simulator or experiment logic.
# Usage: .\make.ps1 <target>   e.g.  .\make.ps1 test
param(
    [Parameter(Position = 0)]
    [string]$Target = "help"
)

$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$resultsDir = if ($env:RESULTS_DIR) { $env:RESULTS_DIR } else { "data/results/main" }
$tuningDir = if ($env:TUNING_DIR) { $env:TUNING_DIR } else { "data/results/h-tuning" }
$figuresDir = if ($env:FIGURES_DIR) { $env:FIGURES_DIR } else { "data/experiments/figures" }

switch ($Target) {
    "help" {
        Write-Host "Targets:"
        Write-Host "  install            Install the project in editable mode (dev + plot)"
        Write-Host "  test               Run the unittest suite (same command as CI)"
        Write-Host "  reference          Run the reference trace validator (same command as CI)"
        Write-Host "  experiments        Run the full d_experiments pipeline"
        Write-Host "  experiments-small  Run the d_experiments quick check (--scale small; data/experiments/run_all_small)"
        Write-Host "  figures            Generate figures (default: data/experiments/figures; 512 KiB)"
        Write-Host "                     Set FIGURES_DIR=data/results/figures to refresh formal figures (overwrites)"
        Write-Host "  clean              Remove caches and build artifacts (keeps data/)"
    }
    "install" {
        & $python -m pip install -e ".[dev,plot]"
        exit $LASTEXITCODE
    }
    "test" {
        & $python -m unittest discover -s tests -t . -v
        exit $LASTEXITCODE
    }
    "reference" {
        & $python -m cache_simulator.reference_validation
        exit $LASTEXITCODE
    }
    "experiments" {
        & $python d_experiments/run_all.py
        exit $LASTEXITCODE
    }
    "experiments-small" {
        & $python d_experiments/run_all.py --scale small --output-dir data/experiments/run_all_small
        exit $LASTEXITCODE
    }
    "figures" {
        & $python d_experiments/make_plots.py --results-dir $resultsDir --tuning-dir $tuningDir --figures-dir $figuresDir --bar-capacity 512
        exit $LASTEXITCODE
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
