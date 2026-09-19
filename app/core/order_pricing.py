"""Cálculo de precios de pedidos en el servidor (réplica de getProductEffectivePrice del frontend).
Así el total guardado nunca depende de lo que envíe el navegador."""
from typing import Any, Dict, Optional


def _positive(value: Any) -> Optional[float]:
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _matching_combination(combinations: list, selected: Dict[str, str]) -> Optional[dict]:
    for comb in combinations or []:
        if not isinstance(comb, dict):
            continue
        options = comb.get("options") or {}
        if options and all(selected.get(k) == v for k, v in options.items()):
            return comb
    return None


def effective_unit_price(product, selected: Dict[str, str]) -> float:
    selected = selected or {}
    comb = _matching_combination(product.combinations or [], selected)
    if comb:
        price = _positive(comb.get("price"))
        if price:
            return price
    for variant in product.variants or []:
        if not isinstance(variant, dict):
            continue
        chosen = selected.get(variant.get("name"))
        if not chosen:
            continue
        for opt in variant.get("options") or []:
            if isinstance(opt, dict) and opt.get("name") == chosen:
                price = _positive(opt.get("price"))
                if price:
                    return price
    return float(product.price)


def is_combination_available(product, selected: Dict[str, str]) -> bool:
    comb = _matching_combination(product.combinations or [], selected or {})
    if comb is None:
        return True
    return bool(comb.get("inStock", comb.get("in_stock", True)))
