"""Catch a training run that didn't train.

A run can finish with a falling loss in the log and still leave the weights untouched (seen once
on the 8 GB Mac under heavy swapping, 2026-10-10). Saving that as "fine-tuned" would put the base
model into the results table under a new name, so the trainers compare a few tensors before and
after and refuse to save when nothing moved.
"""

from typing import Any


def snapshot(module: Any, count: int = 6) -> dict[str, Any]:
    """Copies of the first and last few parameter tensors (embeddings and the top layers)."""
    params = [(name, p) for name, p in module.named_parameters() if p.requires_grad]
    picked = params[: count // 2] + params[-(count - count // 2) :]
    return {name: p.detach().float().cpu().clone() for name, p in picked}


def max_change(module: Any, before: dict[str, Any]) -> float:
    current = dict(module.named_parameters())
    return max(
        (current[name].detach().float().cpu() - tensor).abs().max().item()
        for name, tensor in before.items()
    )
