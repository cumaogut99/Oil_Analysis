"""Rapor için trend grafiklerini PNG olarak üretir (ekran temasından bağımsız, açık stil)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "ui" / "assets"
X_LABELS = {"motor_hours": "Motor çalışma saati", "oil_hours": "Yağ çalışma saati",
            "date_taken": "Numune tarihi"}


def _tokens():
    try:
        return json.loads((ASSETS / "themes" / "light.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _x(s, xkey):
    v = getattr(s, xkey)
    if xkey == "date_taken":
        try:
            return dt.date.fromisoformat(v) if v else None
        except ValueError:
            return None
    return v


def trend_chart(path, samples, key, ev, settings, pmap, xkey="motor_hours", title=None,
                show_limits=True, width_in=7.4, height_in=3.1):
    """samples: grafikte gösterilecek numuneler (tek motor veya çok motor)."""
    import matplotlib.style
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    t = _tokens()
    status_col = {0: t.get("chart_ok", "#16a34a"), 1: t.get("chart_warn", "#d97706"),
                  2: t.get("chart_alarm", "#dc2626")}
    style = ASSETS / "mpl" / "light.mplstyle"
    ctx = matplotlib.style.context(str(style)) if style.exists() else matplotlib.style.context({})
    with ctx:
        fig = Figure(figsize=(width_in, height_in), dpi=160, layout="constrained")
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        groups = {}
        excluded = []
        for s in samples:
            y = s.values.get(key)
            x = _x(s, xkey)
            if y is None or x is None or s.is_fresh:
                continue
            e = ev.evaluate(s).get(key)
            if s.is_excluded(key):
                excluded.append((x, y))
                continue
            groups.setdefault(s.motor_no or "?", []).append((x, y, e.status if e else None, s))
        single = len(groups) == 1
        for mno, pts in sorted(groups.items()):
            pts.sort(key=lambda p: p[0])
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if single:
                ax.plot(xs, ys, "-", color=t.get("chart_line", "#475569"), lw=1.3, zorder=1)
                ax.scatter(xs, ys, c=[status_col.get(p[2], "#94a3b8") for p in pts], s=34, zorder=2,
                           edgecolors="white", linewidths=0.8)
                for x, y, _st, s in pts:
                    ax.annotate(s.sample_no, (x, y), fontsize=5.5, xytext=(3, 4),
                                textcoords="offset points", color="#64748b")
            else:
                (ln,) = ax.plot(xs, ys, "-", lw=1.0, alpha=0.85, label=mno)
                flagged = [p for p in pts if p[2] in (1, 2)]
                ax.scatter(xs, ys, s=12, color=ln.get_color(), zorder=2)
                if flagged:
                    ax.scatter([p[0] for p in flagged], [p[1] for p in flagged], s=46,
                               facecolors="none", edgecolors=[status_col[p[2]] for p in flagged],
                               linewidths=1.6, zorder=3)
        if excluded:
            ax.scatter([p[0] for p in excluded], [p[1] for p in excluded], marker="x", s=36,
                       color="#94a3b8", linewidths=1.3, zorder=3, label="İstatistik dışı")
        ref = next((s for s in reversed(samples) if not s.is_fresh), None)
        if show_limits and ref is not None:
            lim = ev.limits(ref, key)
            for v, c, ls in ((lim.hi_warn, status_col[1], "--"), (lim.hi_alarm, status_col[2], "--"),
                             (lim.lo_warn, status_col[1], ":"), (lim.lo_alarm, status_col[2], ":")):
                if v is not None:
                    ax.axhline(v, color=c, ls=ls, lw=1.0)
            if key == "visc100" and ref.oil_type:
                rng = (settings.get("visc_limits") or {}).get(ref.oil_type)
                if rng:
                    ax.axhspan(rng[0], rng[1], color=status_col[0], alpha=0.08)
        p = pmap.get(key)
        ax.set_title(title or (p.name if p else key), fontsize=9.5)
        if p is not None and p.unit:
            ax.set_ylabel(p.unit, fontsize=8)
        ax.set_xlabel(X_LABELS.get(xkey, xkey), fontsize=8)
        if not single and 1 < len(groups) <= 14:
            ax.legend(fontsize=6, ncol=1 if len(groups) <= 7 else 2, loc="center left",
                      bbox_to_anchor=(1.01, 0.5))
        if xkey == "date_taken":
            for lab in ax.get_xticklabels():
                lab.set_rotation(30)
                lab.set_ha("right")
        fig.savefig(str(path), dpi=160)
    return path
