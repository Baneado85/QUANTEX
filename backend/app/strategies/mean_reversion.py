from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class MeanReversionConfig:
    lookback: int = 100
    entry_z: float = 2.0
    exit_z: float = 0.5
    max_hold_bars: int = 48
    adf_max_p: float = 0.05
    max_ar_order: int = 5
    ar_selection: str = "bic"
    atr_period: int = 14
    regime_percentile: float = 70.0
    use_regime_filter: bool = True
    stop_loss_atr: float = 2.5
    take_profit_atr: float = 3.0
    initial_capital: float = 10_000.0
    risk_per_trade: float = 0.02
    fee_pct: float = 0.001
    allow_short: bool = True
    direction: str = "both"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ARFitResult:
    order: int
    intercept: float
    coefficients: list[float]
    aic: float
    bic: float
    sigma_sq: float
    half_life: float
    selected_by: str = "bic"


class MeanReversionEngine:
    def __init__(self, config: Optional[MeanReversionConfig] = None):
        self.config = config or MeanReversionConfig()

    def is_stationary(self, prices: pd.Series) -> dict:
        y = pd.Series(prices).astype(float).dropna()
        if len(y) < 40:
            return {
                "stationary": False,
                "p_value": float("nan"),
                "statistic": float("nan"),
                "used_lag": 0,
                "reason": "insufficient_data",
            }

        max_lag = int(np.clip(4 * (len(y) / 100.0) ** (2.0 / 9.0), 1, 12))
        stat, p_value, used_lag = self._adf(y, max_lag=max_lag)
        return {
            "stationary": bool(p_value < self.config.adf_max_p),
            "p_value": float(p_value),
            "statistic": float(stat),
            "used_lag": int(used_lag),
            "critical_values": {
                "1%": -3.43,
                "5%": -2.86,
                "10%": -2.57,
            },
            "threshold": self.config.adf_max_p,
        }

    def _adf(
        self, y: pd.Series, max_lag: int = 8
    ) -> tuple[float, float, int]:
        levels = np.asarray(y, dtype=float)
        levels = levels[np.isfinite(levels)]
        deltas = np.diff(levels)

        if len(deltas) < 20:
            return 0.0, 1.0, 0

        candidates: list[tuple[float, float, int]] = []

        for lag in range(0, int(max_lag) + 1):
            rows = []
            targets = []
            for t in range(lag, len(deltas)):
                rows.append(
                    [float(levels[t])]
                    + [float(deltas[t - k]) for k in range(1, lag + 1)]
                )
                targets.append(float(deltas[t]))

            if len(rows) < 15:
                continue

            X = np.asarray(rows, dtype=float)
            target = np.asarray(targets, dtype=float)

            X = X - X.mean(axis=0)
            target = target - target.mean()

            if np.linalg.matrix_rank(X) < X.shape[1]:
                continue

            try:
                beta, residuals, _, _ = np.linalg.lstsq(X, target, rcond=None)
            except np.linalg.LinAlgError:
                continue
            if len(residuals) == 0:
                continue

            resid = target - X @ beta
            dof = max(len(target) - X.shape[1], 1)
            sigma_sq = float(resid @ resid) / dof
            if sigma_sq <= 0:
                continue

            xtx_inv = np.linalg.pinv(X.T @ X)
            se = float(np.sqrt(max(sigma_sq * xtx_inv[0, 0], 1e-24)))
            if se == 0:
                continue

            t_stat = float(beta[0] / se)
            k = X.shape[1]
            bic = float(
                len(target) * np.log(sigma_sq) + k * np.log(len(target))
            )
            candidates.append((bic, t_stat, lag))

        if not candidates:
            return 0.0, 1.0, 0

        _, t_stat, lag = min(candidates, key=lambda item: item[0])
        return t_stat, self._mac_kinnon_pvalue(t_stat), lag

    @staticmethod
    def _mac_kinnon_pvalue(t_stat: float) -> float:
        t_values = np.array([-4.0, -3.43, -2.86, -2.57, -2.26, -1.65, -0.44, 0.0])
        p_values = np.array([0.0001, 0.01, 0.05, 0.10, 0.20, 0.50, 0.90, 1.00])
        return float(np.interp(t_stat, t_values, p_values))

    def fit_ar(self, prices: pd.Series) -> ARFitResult:
        y = pd.Series(prices).astype(float).dropna().to_numpy(dtype=float)
        n = len(y)
        if n < self.config.max_ar_order + 15:
            raise ValueError(f"Serie demasiado corta para AR(p): {n} observaciones")

        mu = float(np.mean(y))
        yc = y - mu

        best: Optional[ARFitResult] = None
        for p in range(1, self.config.max_ar_order + 1):
            rows = []
            targets = []
            for t in range(p, n):
                rows.append([float(yc[t - k]) for k in range(1, p + 1)])
                targets.append(float(yc[t]))

            X = np.asarray(rows, dtype=float)
            target = np.asarray(targets, dtype=float)

            if len(X) < 10 or np.linalg.matrix_rank(X) < X.shape[1]:
                continue

            try:
                beta, residuals, _, _ = np.linalg.lstsq(X, target, rcond=None)
            except np.linalg.LinAlgError:
                continue
            if len(residuals) == 0:
                continue

            resid = target - X @ beta
            dof = max(len(target) - X.shape[1], 1)
            sigma_sq = float(resid @ resid) / dof
            if sigma_sq <= 0:
                continue

            k = p + 1
            llf = -0.5 * len(target) * (np.log(2 * np.pi) + np.log(sigma_sq) + 1)
            aic = float(-2 * llf + 2 * k)
            bic = float(-2 * llf + k * np.log(len(target)))
            intercept = float(mu * (1.0 - float(np.sum(beta))))

            if best is None or (
                bic if self.config.ar_selection == "bic" else aic
            ) < (best.bic if self.config.ar_selection == "bic" else best.aic):
                best = ARFitResult(
                    order=p,
                    intercept=intercept,
                    coefficients=[float(c) for c in beta],
                    aic=aic,
                    bic=bic,
                    sigma_sq=sigma_sq,
                    half_life=float("nan"),
                    selected_by=self.config.ar_selection,
                )

        if best is None:
            raise ValueError("No fue posible ajustar un modelo AR(p) válido")

        best.half_life = self.half_life(best)
        return best

    def half_life(self, fit: ARFitResult) -> float:
        if fit.order == 1:
            phi = fit.coefficients[0]
            if 0.0 < phi < 1.0:
                return float(-np.log(2.0) / np.log(phi))
            return float("inf")

        coeffs = np.asarray(fit.coefficients, dtype=float)
        max_lag = 200
        psi = np.zeros(max_lag, dtype=float)
        psi[0] = 1.0
        for k in range(1, max_lag):
            acc = 0.0
            for j in range(1, min(k, fit.order) + 1):
                acc += coeffs[j - 1] * psi[k - j]
            psi[k] = acc

        variance = psi ** 2
        cumulative = np.cumsum(variance)
        total = cumulative[-1]
        if total <= 0:
            return float("inf")

        idx = np.searchsorted(cumulative, total * 0.5)
        return float(min(idx + 1, max_lag))

    def zscore(self, prices: pd.Series) -> pd.Series:
        series = pd.Series(prices).astype(float)
        mean = series.rolling(self.config.lookback).mean()
        std = series.rolling(self.config.lookback).std(ddof=0)
        std = std.replace(0.0, np.nan)
        return (series - mean) / std

    def atr(self, df: pd.DataFrame) -> pd.Series:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return true_range.rolling(self.config.atr_period).mean()

    def regime_filter(self, df: pd.DataFrame) -> pd.Series:
        atr_values = self.atr(df)
        close = df["close"].astype(float)
        atr_pct = atr_values / close
        if not self.config.use_regime_filter:
            return pd.Series(False, index=df.index)

        threshold = atr_pct.rolling(self.config.lookback).quantile(
            self.config.regime_percentile / 100.0
        )
        return (atr_pct > threshold).fillna(False)

    def generate_signal(self, ohlcv: pd.DataFrame) -> dict:
        df = self._normalize(ohlcv)
        if len(df) < self.config.lookback + self.config.max_ar_order + 20:
            return {
                "action": "hold",
                "reason": "datos_insuficientes",
                "z_score": None,
                "z_score_prev": None,
                "bars_held": 0,
                "regime_trending": None,
                "price": float(df["close"].iloc[-1]),
                "timestamp": str(df.index[-1]) if hasattr(df.index[-1], "isoformat") else None,
            }

        z = self.zscore(df["close"])
        adf = self.is_stationary(df["close"])
        trending = self.regime_filter(df)

        z_last = z.iloc[-1]
        z_prev = z.iloc[-2]
        price = float(df["close"].iloc[-1])

        if not np.isfinite(z_last):
            return {
                "action": "hold",
                "reason": "z_score_no_valido",
                "z_score": None,
                "z_score_prev": None,
                "bars_held": 0,
                "regime_trending": bool(trending.iloc[-1]) if len(trending) else None,
                "price": price,
                "stationary": adf["stationary"],
            }

        if not adf["stationary"]:
            return {
                "action": "hold",
                "reason": f"serie_no_estacionaria_p={adf['p_value']:.4f}",
                "z_score": float(z_last),
                "z_score_prev": float(z_prev) if np.isfinite(z_prev) else None,
                "bars_held": 0,
                "regime_trending": bool(trending.iloc[-1]),
                "price": price,
                "stationary": False,
            }

        allow_long = self.config.direction in ("both", "long")
        allow_short = self.config.allow_short and self.config.direction in (
            "both",
            "short",
        )

        if bool(trending.iloc[-1]):
            return {
                "action": "hold",
                "reason": "regime_trending_pausa",
                "z_score": float(z_last),
                "z_score_prev": float(z_prev) if np.isfinite(z_prev) else None,
                "bars_held": 0,
                "regime_trending": True,
                "price": price,
                "stationary": True,
            }

        if allow_long and z_last <= -self.config.entry_z:
            action, reason = "buy", "sobreventa_extrema"
        elif allow_short and z_last >= self.config.entry_z:
            action, reason = "sell", "sobrecompra_extrema"
        elif abs(z_last) <= self.config.exit_z:
            action, reason = "close", "reversion_a_media"
        else:
            action, reason = "hold", "sin_señal"

        return {
            "action": action,
            "reason": reason,
            "z_score": float(z_last),
            "z_score_prev": float(z_prev) if np.isfinite(z_prev) else None,
            "bars_held": 0,
            "regime_trending": bool(trending.iloc[-1]),
            "price": price,
            "stationary": True,
        }

    def analyze(self, ohlcv: pd.DataFrame) -> dict:
        df = self._normalize(ohlcv)
        adf = self.is_stationary(df["close"])
        z = self.zscore(df["close"])

        ar_result: Optional[dict] = None
        try:
            fit = self.fit_ar(df["close"])
            ar_result = {
                "order": fit.order,
                "intercept": fit.intercept,
                "coefficients": fit.coefficients,
                "aic": fit.aic,
                "bic": fit.bic,
                "sigma_sq": fit.sigma_sq,
                "half_life": fit.half_life,
                "selected_by": fit.selected_by,
            }
        except ValueError as exc:
            ar_result = {"error": str(exc)}

        latest = z.dropna()
        result = {
            "adf": adf,
            "ar": ar_result,
            "z_score": float(latest.iloc[-1]) if len(latest) else None,
            "z_score_mean_30": float(latest.tail(30).mean()) if len(latest) else None,
            "price": float(df["close"].iloc[-1]),
            "regime_trending": bool(self.regime_filter(df).iloc[-1]),
            "config": self.config.to_dict(),
        }
        result["signal"] = self.generate_signal(df)
        return result

    def backtest(self, ohlcv: pd.DataFrame) -> dict:
        df = self._normalize(ohlcv)
        if len(df) < self.config.lookback + self.config.max_ar_order + 20:
            raise ValueError("Datos insuficientes para backtest")

        close = df["close"].astype(float)
        z = self.zscore(close)
        trending = self.regime_filter(df)
        atr_values = self.atr(df)

        capital = float(self.config.initial_capital)
        risk_amount = capital * self.config.risk_per_trade
        position = 0
        entry_price = 0.0
        entry_index = 0
        entry_z = 0.0
        stop_price = 0.0
        target_price = 0.0

        trades: list[dict] = []
        equity_curve: list[float] = []
        allow_long = self.config.direction in ("both", "long")
        allow_short = self.config.allow_short and self.config.direction in (
            "both",
            "short",
        )

        for i in range(len(df)):
            price = float(close.iloc[i])
            z_now = z.iloc[i]
            atr_now = atr_values.iloc[i]
            equity_curve.append(capital)

            if position != 0:
                bars_held = i - entry_index
                hit_stop = (
                    position == 1 and np.isfinite(atr_now) and price <= stop_price
                ) or (position == -1 and np.isfinite(atr_now) and price >= stop_price)
                hit_target = (
                    position == 1 and np.isfinite(atr_now) and price >= target_price
                ) or (
                    position == -1 and np.isfinite(atr_now) and price <= target_price
                )
                revert = np.isfinite(z_now) and abs(z_now) <= self.config.exit_z
                expired = bars_held >= self.config.max_hold_bars

                if hit_stop or hit_target or revert or expired:
                    reason = (
                        "stop_loss"
                        if hit_stop
                        else "take_profit"
                        if hit_target
                        else "mean_reversion"
                        if revert
                        else "max_hold"
                    )
                    pnl = (price - entry_price) * position
                    pnl -= abs(price) * self.config.fee_pct
                    capital += pnl
                    trades.append(
                        {
                            "entry_index": entry_index,
                            "exit_index": i,
                            "side": "long" if position == 1 else "short",
                            "entry_price": entry_price,
                            "exit_price": price,
                            "pnl": float(pnl),
                            "pnl_pct": float(pnl / entry_price * position * 100),
                            "bars_held": bars_held,
                            "z_score_at_entry": float(entry_z),
                            "exit_reason": reason,
                        }
                    )
                    position = 0
                    equity_curve[-1] = capital
                    continue

            if bool(trending.iloc[i]) or not np.isfinite(z_now):
                continue

            if position == 0:
                if allow_long and z_now <= -self.config.entry_z:
                    position = 1
                elif allow_short and z_now >= self.config.entry_z:
                    position = -1
                else:
                    continue

                entry_price = price
                entry_index = i
                entry_z = float(z_now)
                if np.isfinite(atr_now):
                    stop_price = entry_price - position * self.config.stop_loss_atr * atr_now
                    target_price = entry_price + position * self.config.take_profit_atr * atr_now
                else:
                    stop_price = entry_price
                    target_price = entry_price
                fee = abs(price) * self.config.fee_pct
                capital -= fee

        if position != 0:
            last_price = float(close.iloc[-1])
            pnl = (last_price - entry_price) * position
            pnl -= abs(last_price) * self.config.fee_pct
            capital += pnl
            trades.append(
                {
                    "entry_index": entry_index,
                    "exit_index": len(df) - 1,
                    "side": "long" if position == 1 else "short",
                    "entry_price": entry_price,
                    "exit_price": last_price,
                    "pnl": float(pnl),
                    "pnl_pct": float(pnl / entry_price * position * 100),
                    "bars_held": len(df) - 1 - entry_index,
                    "z_score_at_entry": float(entry_z),
                    "exit_reason": "open_at_end",
                }
            )
            equity_curve[-1] = capital

        returns = pd.Series(equity_curve).pct_change().dropna()
        total_return = (
            (capital / self.config.initial_capital - 1.0) * 100.0
            if self.config.initial_capital
            else 0.0
        )
        sharpe = (
            float(returns.mean() / returns.std(ddof=0) * np.sqrt(365))
            if len(returns) > 2 and returns.std(ddof=0) > 0
            else 0.0
        )
        equity = pd.Series(equity_curve)
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        max_drawdown = float(drawdown.min() * 100) if len(drawdown) else 0.0
        wins = [t for t in trades if t["pnl"] > 0]

        return {
            "initial_capital": self.config.initial_capital,
            "final_capital": float(capital),
            "total_return_pct": float(total_return),
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_drawdown,
            "win_rate": float(len(wins) / len(trades) * 100) if trades else 0.0,
            "total_trades": len(trades),
            "best_trade": max((t["pnl_pct"] for t in trades), default=0.0),
            "worst_trade": min((t["pnl_pct"] for t in trades), default=0.0),
            "trades": trades,
            "equity_curve": [float(v) for v in equity_curve],
            "z_scores": [None if not np.isfinite(v) else float(v) for v in z],
            "config": self.config.to_dict(),
        }

    def _normalize(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(ohlcv, pd.DataFrame):
            raise TypeError("ohlcv debe ser un pandas.DataFrame")
        df = ohlcv.copy()
        if df.empty:
            raise ValueError("ohlcv está vacío")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.columns = [str(c).lower() for c in df.columns]
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Faltan columnas OHLCV: {sorted(missing)}")

        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"])
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, errors="coerce")
            if df.index.isna().all():
                df.index = pd.RangeIndex(len(df))
        df = df.sort_index()
        return df
