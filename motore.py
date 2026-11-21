"""Calcolo della formazione migliore.

Stessa logica della pagina Fanta Formazione (versione JavaScript), portata in Python.
"""
import math

ROLE_ORDER = {"P": 0, "D": 1, "C": 2, "A": 3}
CAP = {"P": 40, "D": 60, "C": 120, "A": 200}
BASE = {"D": {"g": 0.07, "a": 0.08, "y": 0.22},
        "C": {"g": 0.30, "a": 0.25, "y": 0.18},
        "A": {"g": 0.65, "a": 0.20, "y": 0.12}}
MODULI_DEFAULT = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-3-2", "5-4-1"]
TAB_MOD_DEFAULT = [{"da": 6.0, "punti": 1}, {"da": 6.5, "punti": 3}, {"da": 7.0, "punti": 6}]
P_SENZA_NOTIZIE = 50


def chiave(pl):
    return f"{pl['n']}|{pl['t']}"


def arricchisci(rosa, giornata, override=None):
    """Unisce la rosa dell'utente con le notizie della giornata (p, nota, st, rig).

    override: {"Nome|Squadra": p} scelti a mano dall'utente.
    """
    gioc = (giornata or {}).get("giocatori", {})
    override = override or {}
    out = []
    for pl in rosa:
        k = chiave(pl)
        info = gioc.get(k, {})
        x = {"n": pl["n"], "t": pl["t"], "r": pl["r"], "fvm": float(pl.get("fvm") or 1)}
        if info:
            x["p"] = info.get("p", P_SENZA_NOTIZIE)
            x["nota"] = info.get("nota", "")
            x["notizie"] = True
        else:
            x["p"] = P_SENZA_NOTIZIE
            x["nota"] = "Nessuna notizia per questa giornata: controlla tu"
            x["notizie"] = False
        if "st" in info:
            x["st"] = info["st"]
        if "rig" in info:
            x["rig"] = info["rig"]
        if k in override and override[k] is not None:
            x["p"] = override[k]
            x["manuale"] = True
        out.append(x)
    return out


class Motore:
    def __init__(self, giornata):
        g = giornata or {}
        self.partite = g.get("partite", {})
        self.moduli = g.get("moduli") or MODULI_DEFAULT
        self.tab_mod = g.get("tabella_modificatore") or TAB_MOD_DEFAULT

    def _m(self, pl):
        return self.partite.get(pl["t"]) or {"diff": 3, "casa": False}

    def quality(self, pl):
        return max(0.0, min(1.0, math.log(1 + pl["fvm"]) / math.log(1 + CAP[pl["r"]])))

    def voto(self, pl):
        m = self._m(pl)
        return 6 + self.quality(pl) * 0.35 + (3 - m["diff"]) * 0.12 + (0.05 if m["casa"] else -0.03)

    def att_f(self, pl):
        m = self._m(pl)
        return max(0.5, 1 + (3 - m["diff"]) * 0.18) * (1.08 if m["casa"] else 0.95)

    def x_bonus(self, pl):
        if pl["r"] == "P":
            return {"g": 0, "a": 0, "y": 0}
        b = BASE[pl["r"]]
        q = self.quality(pl)
        lvl = 0.15 + 0.85 * q ** 1.5
        f = self.att_f(pl)
        K = 6
        g, a = b["g"] * lvl, b["a"] * lvl
        st = pl.get("st")
        if st and st.get("pr", 0) > 0:
            g = ((st["g"] - (st.get("gr") or 0)) + g * K) / (st["pr"] + K)
            a = (st["a"] + a * K) / (st["pr"] + K)
        return {"g": (g + 0.2 * (pl.get("rig") or 0)) * f, "a": a * f, "y": b["y"]}

    def bonus_p(self, pl):
        if pl["r"] == "P":
            return 0
        x = self.x_bonus(pl)
        return 1 - math.exp(-(x["g"] + x["a"]))

    def fanta(self, pl):
        m = self._m(pl)
        v = self.voto(pl)
        if pl["r"] == "P":
            ga = 0.45 + 0.3 * m["diff"]
            return v - ga + math.exp(-ga)
        x = self.x_bonus(pl)
        return v + 3 * x["g"] + x["a"] - 0.5 * x["y"]

    def score(self, pl):
        return pl["p"] / 100 * self.fanta(pl)

    @staticmethod
    def _norm_cdf(x):
        t = 1 / (1 + 0.2316419 * abs(x))
        d = 0.3989423 * math.exp(-x * x / 2)
        p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
        return 1 - p if x > 0 else p

    def mod_bonus(self, modificatore, gk, defs):
        if not modificatore or len(defs) < 4 or not gk:
            return 0
        best = sorted(defs, key=self.voto, reverse=True)[:3]
        players = [gk] + best
        mean = sum(self.voto(p) for p in players) / 4
        sd = 0.38
        exp = 0
        for i, row in enumerate(self.tab_mod):
            lo = row["da"]
            hi = self.tab_mod[i + 1]["da"] if i + 1 < len(self.tab_mod) else 99
            prob = self._norm_cdf((hi - mean) / sd) - self._norm_cdf((lo - mean) / sd)
            exp += prob * row["punti"]
        avail = 1
        for p in players:
            avail *= max(p["p"] / 100, 0.3)
        return exp * avail ** 0.5

    def migliore(self, rosa, modificatore):
        by = {"P": [], "D": [], "C": [], "A": []}
        for pl in rosa:
            by[pl["r"]].append(pl)
        for r in by:
            by[r].sort(key=self.score, reverse=True)
        results = []
        for m in self.moduli:
            d, c, a = map(int, m.split("-"))
            if not by["P"] or len(by["D"]) < d or len(by["C"]) < c or len(by["A"]) < a:
                continue
            gk, D, C, A = by["P"][0], by["D"][:d], by["C"][:c], by["A"][:a]
            base = sum(self.score(p) for p in [gk] + D + C + A)
            mb = self.mod_bonus(modificatore, gk, D)
            results.append({"m": m, "gk": gk, "D": D, "C": C, "A": A,
                            "base": base, "mb": mb, "tot": base + mb})
        if not results:
            return None
        results.sort(key=lambda r: r["tot"], reverse=True)
        win = results[0]
        used = {id(p) for p in [win["gk"]] + win["D"] + win["C"] + win["A"]}
        bench = [p for p in rosa if id(p) not in used]
        bench.sort(key=lambda p: (ROLE_ORDER[p["r"]], -self.score(p)))
        return {"results": results, "win": win, "bench": bench}
