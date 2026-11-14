"""The strategy template (M4, own design on upstream's trailing-stop example); see strategy.py."""

from .actions import Action, ActionLog
from .params import TemplateParams
from .strategy import Phase, SymbolBook, TrailingTemplate

__all__ = ["Action", "ActionLog", "Phase", "SymbolBook", "TemplateParams", "TrailingTemplate"]
