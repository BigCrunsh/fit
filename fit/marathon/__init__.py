"""Marathon durability model (Bayesian, fitness-aware).

See openspec/changes/marathon-durability-model/design.md. The PyMC-heavy parts
(model.py, predict.py) import pymc/arviz/nutpie lazily so the core install stays
light and the dashboard degrades gracefully when the `forecast` extra is absent.
The feature layer (features.py) is pure pandas/numpy and always importable.
"""

from fit.marathon.features import extract_efforts  # noqa: F401  (no PyMC dependency)
