"""FORGE roam — one frontend whose backend roams.

Training jobs are described once. Providers (local GPU, Kaggle, ...) execute
them. The orchestrator watches health and fails over mid-training, carrying
checkpoints along, while the UI never changes.
"""
