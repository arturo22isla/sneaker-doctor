"""Packs de Clean Lab y búsqueda de la opción más barata con packs.

El contenido de cada pack sale de la sección "¿Qué contiene?" de cleanlab.pe.
Comprobación: el precio anterior de cada pack coincide con la suma de los precios
anteriores de sus productos sueltos (por ejemplo, Pack Gamuza Pro = 69.90 + 39.90 + 39.90).
"""
from itertools import combinations

import pandas as pd

PACKS = {
    "PCLPGP-P": ["LCLKG", "PCLACP"],                               # Pack Gamuza Duo
    "LCLGF-P": ["LCLKG", "LCLFP"],                                 # Kit de Gamuza + Foam Pack
    "LCLGM-P": ["LCLFP", "LCLKG", "PCLACP"],                       # Pack Gamuza Pro
    "PCLLCPP-P": ["LCLFP", "LCLKG", "PCLPP"],                      # Lab Care & Protect Pack (validar contenido)
    "LCLSP-P": ["LCLFP", "PCLPP", "PCLEO"],                        # Clean System Pack
    "LCLTC-P": ["LCLFP", "LCLKG", "LCLLL"],                        # Total Clean
    "LCLMP-P": ["LCLFP", "LCLLL"],                                 # Master Pack
    "LCLFB-P": ["LCLFP", "LCLBP-P"],                               # Foam Pack + Blanqueadores
    "LCLRPP1-P": ["LCLFP", "LCLKG", "PCLACP", "ACLPP1", "PCLEO"],  # Pack Restauración Pro (plantillas talla S)
    "LCLRPP2-P": ["LCLFP", "LCLKG", "PCLACP", "ACLPP2", "PCLEO"],  # Pack Restauración Pro (plantillas talla M)
    "LCLE-P": ["LCLEP", "LCLEB"],                                  # Pack Escobillas
    "LCLRF-P": ["LCLLL", "LCLEP", "LCLEB", "PCLACP"],              # Pack Refill
}


def best_option(needed: list[str], catalog: pd.DataFrame, max_packs: int = 2) -> dict | None:
    """Combinación de hasta `max_packs` packs + productos sueltos que cubre `needed` al menor precio.

    Solo se devuelve si sale más barata que comprar todo suelto. Los productos de más
    que traiga el pack se informan como regalo del pack.
    """
    needed = [s for s in dict.fromkeys(needed) if s in catalog.index]
    price = lambda s: float(catalog.loc[s, "precio"])  # noqa: E731
    singles_total = sum(price(s) for s in needed)
    packs = [p for p, items in PACKS.items()
             if p in catalog.index and catalog.loc[p, "disponible"] and set(items) & set(needed)]

    best = None
    for n in range(1, max_packs + 1):
        for combo in combinations(packs, n):
            contents = [s for p in combo for s in PACKS[p]]
            if len(contents) != len(set(contents)):
                continue  # dos packs con el mismo producto: no tiene sentido
            loose = [s for s in needed if s not in contents]
            total = sum(price(p) for p in combo) + sum(price(s) for s in loose)
            if total < singles_total - 0.01 and (best is None or total < best["total"]):
                best = {"packs": list(combo), "sueltos": loose, "total": round(total, 2),
                        "ahorro": round(singles_total - total, 2),
                        "extras": [s for s in contents if s not in needed]}
    return best
