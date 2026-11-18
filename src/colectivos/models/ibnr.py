"""IBNR por tipo de prestación y trimestre de ocurrencia: chain-ladder (monto y número) y Cape Cod para el
monto reciente de los tipos volátiles. Cola = 1."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from colectivos.config import PricingConfig

logger = logging.getLogger(__name__)


def _wide(triangle: pd.DataFrame, value: str) -> pd.DataFrame:
    return triangle.pivot_table(index="origin_quarter", columns="dev_quarter", values=value, aggfunc="sum").sort_index()


def development_factors(triangle: pd.DataFrame, value: str) -> pd.Series:
    """LDF_d (de d a d+1), ponderado por volumen sobre los orígenes con d+1 observado; 1 si el denominador es 0."""
    wide = _wide(triangle, value)
    dev_quarters = sorted(wide.columns)
    factors = {}
    for dev in dev_quarters[:-1]:
        observed = wide[dev + 1].notna()
        denominator = wide.loc[observed, dev].sum()
        factors[dev] = wide.loc[observed, dev + 1].sum() / denominator if denominator > 0 else 1.0
    return pd.Series(factors, name="ldf", dtype=float).rename_axis("dev_quarter")


def cdf_to_ultimate(factors: pd.Series) -> pd.Series:
    """CDF_d = producto de LDF_k para k >= d; el último desarrollo observado tiene CDF = 1 (cola = 1)."""
    last_dev = int(factors.index.max()) + 1 if len(factors) else 0
    reversed_product = factors.sort_index(ascending=False).cumprod().sort_index()
    cdf = pd.concat([reversed_product, pd.Series({last_dev: 1.0})])
    return cdf.rename("cdf").rename_axis("dev_quarter")


def chain_ladder(triangle: pd.DataFrame, value: str) -> pd.DataFrame:
    wide = _wide(triangle, value)
    cdf = cdf_to_ultimate(development_factors(triangle, value))
    latest_dev = wide.notna().iloc[:, ::-1].idxmax(axis=1)
    latest = pd.Series([wide.at[origin, dev] for origin, dev in latest_dev.items()], index=wide.index)
    origin_cdf = latest_dev.map(cdf)
    result = pd.DataFrame(
        {"origin_quarter": wide.index, "latest": latest.to_numpy(), "cdf": origin_cdf.to_numpy()}
    )
    result["ultimate"] = result.latest * result.cdf
    result["ibnr"] = result.ultimate - result.latest
    return result


def _trended_pure_premium(pure_premium: pd.Series, exposure: pd.Series, quarter_index: pd.Series) -> tuple[float, float]:
    """Ajuste ponderado por exposición de log(pp) = alfa + beta * t sobre los orígenes con pp > 0."""
    usable = pure_premium > 0
    if usable.sum() >= 2:
        beta, alpha = np.polyfit(
            quarter_index[usable], np.log(pure_premium[usable]), 1, w=np.sqrt(exposure[usable])
        )
        return float(alpha), float(beta)
    if usable.sum() == 1:
        return float(np.log(pure_premium[usable].iloc[0])), 0.0
    logger.warning("Cape Cod sin orígenes maduros con costo positivo: a priori = 0")
    return -np.inf, 0.0


def cape_cod(triangle: pd.DataFrame, value: str, exposure: pd.Series, recent_quarters: int) -> pd.DataFrame:
    result = chain_ladder(triangle, value)
    result["method"] = "chain_ladder"
    if recent_quarters <= 0:
        return result
    result["exposure"] = result.origin_quarter.map(exposure).fillna(0.0).to_numpy()
    result["t"] = np.arange(len(result), dtype=float)
    is_recent = result.index >= len(result) - recent_quarters
    mature = result[~is_recent & (result.exposure > 0)]
    alpha, beta = _trended_pure_premium(mature.ultimate / mature.exposure, mature.exposure, mature.t)
    recent = result[is_recent]
    a_priori = np.exp(alpha + beta * recent.t) * recent.exposure
    result.loc[is_recent, "ultimate"] = recent.latest + a_priori * (1 - 1 / recent.cdf)
    result.loc[is_recent, "method"] = "cape_cod"
    result["ibnr"] = result.ultimate - result.latest
    return result.drop(columns=["exposure", "t"])


def estimate_ibnr(development: pd.DataFrame, exposure_quarter: pd.DataFrame, cfg: PricingConfig) -> pd.DataFrame:
    """Últimos por tipo y trimestre de ocurrencia. Conteos siempre con chain-ladder; en los tipos Cape Cod el
    monto limitado de los orígenes recientes usa Cape Cod y el exceso sobre el umbral se toma como pagado."""
    development = development.assign(origin_quarter=pd.to_datetime(development.origin_quarter))
    exposure_quarter = exposure_quarter.assign(origin_quarter=pd.to_datetime(exposure_quarter.origin_quarter))
    frames = []
    for claim_type, triangle in development.groupby("claim_type"):
        amount = chain_ladder(triangle, "paid_uf_cum")
        count = chain_ladder(triangle, "n_claims_cum")
        if claim_type in cfg.cape_cod_claim_types:
            exposure = exposure_quarter[exposure_quarter.claim_type == claim_type].set_index("origin_quarter").exposure_years
            capped = cape_cod(triangle, "paid_capped_uf_cum", exposure, cfg.cape_cod_recent_quarters)
        else:
            capped = chain_ladder(triangle, "paid_capped_uf_cum")
            capped["method"] = "chain_ladder"
        is_cape_cod = (capped.method == "cape_cod").to_numpy()
        ultimate_uf = amount.ultimate.to_numpy().copy()
        excess_paid = amount.latest.to_numpy() - capped.latest.to_numpy()
        ultimate_uf[is_cape_cod] = capped.ultimate.to_numpy()[is_cape_cod] + excess_paid[is_cape_cod]
        frames.append(
            pd.DataFrame(
                {
                    "claim_type": claim_type,
                    "origin_quarter": amount.origin_quarter,
                    "paid_uf": amount.latest,
                    "ultimate_uf": ultimate_uf,
                    "paid_capped_uf": capped.latest,
                    "ultimate_capped_uf": capped.ultimate,
                    "n_paid": count.latest,
                    "n_ultimate": count.ultimate,
                    "cdf_amount": amount.cdf,
                    "cdf_capped": capped.cdf,
                    "cdf_count": count.cdf,
                    "method": capped.method,
                }
            )
        )
    result = pd.concat(frames, ignore_index=True)
    result["ibnr_uf"] = result.ultimate_uf - result.paid_uf
    return result
