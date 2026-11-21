"""Fanta Formazione: la formazione migliore per le tue leghe di fantacalcio.

App Streamlit con account personali (Supabase Auth). Ogni utente ha le sue leghe e
le sue rose; le notizie della giornata (probabili, infortuni, statistiche) sono comuni.
"""
import base64
import html
import os
import time
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client

from motore import Motore, arricchisci, chiave, ROLE_ORDER

_QUI = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(_QUI, "logo.png")
st.set_page_config(page_title="Fanta Formazione", page_icon=LOGO if os.path.exists(LOGO) else "⚽", layout="centered",
                   initial_sidebar_state="collapsed")

SQUADRE_DEFAULT = ["Atalanta", "Bologna", "Cagliari", "Como", "Fiorentina", "Frosinone", "Genoa",
                   "Inter", "Juventus", "Lazio", "Lecce", "Milan", "Monza", "Napoli", "Parma",
                   "Roma", "Sassuolo", "Torino", "Udinese", "Venezia"]
RUOLI = ["P", "D", "C", "A"]
NOMI_RUOLO = {"P": "Portiere", "D": "Difensore", "C": "Centrocampista", "A": "Attaccante"}

# ------------------------------------------------------------------ stile
st.markdown("""
<style>
#MainMenu, footer {visibility:hidden}
header[data-testid="stHeader"], [data-testid="stHeader"] {display:none !important}
.block-container, [data-testid="stMainBlockContainer"] {padding-top:3rem !important; padding-bottom:3rem; max-width:760px}
button[kind="primary"], [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"],
button[kind="primaryFormSubmit"] {background:#2f6fe4 !important; border-color:#2f6fe4 !important; color:#fff !important}
.stTabs [aria-selected="true"] p {color:#2f6fe4 !important}
.stTabs [data-baseweb="tab-highlight"] {background-color:#2f6fe4 !important}
.ff-head {display:flex; align-items:center; gap:12px; margin:8px 0 4px; padding-top:6px}
.ff-logo {width:56px; height:56px; flex:none; display:flex; align-items:center; justify-content:center; font-size:30px}
.ff-logo img {width:56px; height:56px; object-fit:contain}
.ff-stemma {display:flex; align-items:center; gap:10px; margin:6px 0}
.ff-stemma img {width:64px; height:64px; object-fit:contain}
.ff-stemma b {font-size:18px}
.ff-title {font-size:24px; font-weight:800; line-height:1.2}
.ff-sub {color:#64708a; font-size:13px}
.ff-badge {display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px;
  border-radius:7px; color:#fff; font-size:12px; font-weight:800; flex:none}
.ff-P {background:linear-gradient(145deg,#ffc23d,#e08a00)}
.ff-D {background:linear-gradient(145deg,#45c96a,#1f8a3d)}
.ff-C {background:linear-gradient(145deg,#5a8fff,#2152c9)}
.ff-A {background:linear-gradient(145deg,#ff5a6b,#c0202f)}
.ff-row {display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid rgba(128,128,128,.18)}
.ff-row:last-child {border-bottom:0}
.ff-info {flex:1; min-width:0}
.ff-info b {font-size:15px}
.ff-info small {display:block; color:#7b869c; font-size:12px; line-height:1.35}
.ff-pct {font-weight:700; font-size:14px; white-space:nowrap}
.ff-hi {color:#1d8a4a} .ff-mid {color:#c47a00} .ff-lo {color:#c4323f}
.ff-big {font-size:34px; font-weight:800; line-height:1.1}
.ff-card {border:1px solid rgba(128,128,128,.25); border-radius:14px; padding:12px 14px; margin:10px 0}
.ff-chip {display:inline-block; border:1px solid rgba(128,128,128,.35); border-radius:999px;
  padding:2px 10px; font-size:12px; margin:2px 4px 2px 0; color:#7b869c}
.ff-chip.on {border-color:#1d8a4a; color:#1d8a4a; font-weight:700}
.ff-n {color:#7b869c; width:20px; text-align:right; font-size:13px}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ Supabase
def sb():
    """Un client Supabase per ogni sessione del browser (mai condiviso tra utenti)."""
    if "sb" not in st.session_state:
        st.session_state.sb = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    return st.session_state.sb


def _con_rinnovo(fn):
    """Esegue una chiamata al database; se il token è scaduto lo rinnova e riprova."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        if "JWT" in str(e) or "expired" in str(e).lower():
            try:
                sess = sb().auth.refresh_session()
                if sess and sess.session:
                    sb().postgrest.auth(sess.session.access_token)
                return fn()
            except Exception:  # noqa: BLE001
                esci()
                st.warning("Sessione scaduta: entra di nuovo.")
                st.stop()
        raise


def utente():
    return st.session_state.get("user")


def entra(email, password):
    res = sb().auth.sign_in_with_password({"email": email.strip(), "password": password})
    _imposta_sessione(res)


def registra(nome, email, password):
    res = sb().auth.sign_up({"email": email.strip(), "password": password,
                             "options": {"data": {"nome": nome.strip()}}})
    if res.session:
        _imposta_sessione(res)
        return True
    return False  # serve la conferma via email


def _imposta_sessione(res):
    sb().postgrest.auth(res.session.access_token)
    st.session_state.user = {"id": res.user.id, "email": res.user.email,
                             "nome": (res.user.user_metadata or {}).get("nome") or res.user.email.split("@")[0]}
    st.session_state.pop("stato", None)


def esci():
    try:
        sb().auth.sign_out()
    except Exception:  # noqa: BLE001
        pass
    for k in ("sb", "user", "stato", "giornata"):
        st.session_state.pop(k, None)


def carica_giornata(forza=False):
    if forza or "giornata" not in st.session_state or time.time() - st.session_state.get("giornata_t", 0) > 300:
        r = _con_rinnovo(lambda: sb().table("fanta_giornata").select("dati,aggiornato").eq("id", 1).execute())
        st.session_state.giornata = (r.data[0]["dati"] if r.data else {}) or {}
        st.session_state.giornata_t = time.time()
    return st.session_state.giornata


def carica_stato():
    if "stato" in st.session_state:
        return st.session_state.stato
    uid = utente()["id"]
    r = _con_rinnovo(lambda: sb().table("fanta_stato").select("dati").eq("user_id", uid).execute())
    if r.data:
        stato = r.data[0]["dati"] or {}
    else:
        # primo accesso: se esistono rose preparate per questa email le carico
        stato = {"leghe": []}
        try:
            ri = sb().table("fanta_rose_iniziali").select("dati").execute()
            if ri.data:
                stato = ri.data[0]["dati"]
        except Exception:  # noqa: BLE001
            pass
        salva_stato(stato)
    stato.setdefault("leghe", [])
    stato.setdefault("override", {})
    st.session_state.stato = stato
    return stato


def salva_stato(stato):
    uid = utente()["id"]
    _con_rinnovo(lambda: sb().table("fanta_stato").upsert(
        {"user_id": uid, "dati": stato, "aggiornato": datetime.now(timezone.utc).isoformat()}).execute())
    st.session_state.stato = stato


# ------------------------------------------------------------------ pezzi grafici
def esc(s):
    return html.escape(str(s))


def cls_p(p):
    return "ff-hi" if p >= 75 else "ff-mid" if p >= 45 else "ff-lo"


def partita_txt(g, squadra):
    m = (g.get("partite") or {}).get(squadra)
    if not m:
        return ""
    return f"{'vs' if m.get('casa') else '@'} {m.get('vs', '')} · {m.get('quando', '')}"


def riga(pl, g, motore, numero=None):
    n = f'<span class="ff-n">{numero}</span>' if numero is not None else ""
    bonus = ""
    if pl["r"] != "P" and pl["p"] > 0:
        bonus = f" · bonus {round(motore.bonus_p(pl) * 100)}%"
    man = " · ✋ scelto da te" if pl.get("manuale") else ""
    return (f'<div class="ff-row">{n}<span class="ff-badge ff-{pl["r"]}">{pl["r"]}</span>'
            f'<div class="ff-info"><b>{esc(pl["n"])}</b>'
            f'<small>{esc(pl["t"])} {esc(partita_txt(g, pl["t"]))}{bonus}{man}</small>'
            f'<small>{esc(pl.get("nota", ""))}</small></div>'
            f'<span class="ff-pct {cls_p(pl["p"])}">{round(pl["p"])}%</span></div>')


def _logo_b64():
    if "logo_b64" not in st.session_state:
        try:
            with open(LOGO, "rb") as f:
                st.session_state.logo_b64 = base64.b64encode(f.read()).decode()
        except OSError:
            st.session_state.logo_b64 = ""
    return st.session_state.logo_b64


def logo_html():
    b = _logo_b64()
    return f'<img src="data:image/png;base64,{b}" alt="">' if b else "⚽"


def stemma_squadra(lega):
    """Lo stemma dei Desperados accanto al nome della squadra."""
    if "desperados" in lega.get("squadra", "").lower() and _logo_b64():
        st.markdown(f'<div class="ff-stemma">{logo_html()}<div><b>{esc(lega["squadra"])}</b>'
                    f'<div class="ff-sub">{esc(lega["nome"])}</div></div></div>', unsafe_allow_html=True)


def intestazione(g):
    sub = ""
    if g.get("giornata"):
        sub = f"{g['giornata']}ª giornata · schierare entro {g.get('scadenza', '')}"
    st.markdown(f'<div class="ff-head"><div class="ff-logo">{logo_html()}</div><div><div class="ff-title">Fanta Formazione</div>'
                f'<div class="ff-sub">{esc(sub)}</div></div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ schermate
def schermata_accesso():
    intestazione({})
    st.write("Entra con il tuo account per vedere la formazione migliore delle tue leghe.")
    t1, t2 = st.tabs(["Entra", "Crea account"])
    with t1:
        with st.form("login"):
            email = st.text_input("Email", autocomplete="email")
            pw = st.text_input("Password", type="password", autocomplete="current-password")
            ok = st.form_submit_button("Entra", type="primary", use_container_width=True)
        if ok:
            try:
                entra(email, pw)
                st.rerun()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "confirm" in msg.lower():
                    st.error("Devi prima confermare l'email: apri il link che ti è arrivato.")
                else:
                    st.error("Email o password sbagliate.")
    with t2:
        with st.form("signup"):
            nome = st.text_input("Il tuo nome")
            email2 = st.text_input("Email ", autocomplete="email")
            pw2 = st.text_input("Password (almeno 6 caratteri)", type="password", autocomplete="new-password")
            ok2 = st.form_submit_button("Crea account", type="primary", use_container_width=True)
        if ok2:
            if not nome or not email2 or len(pw2) < 6:
                st.error("Compila nome, email e una password di almeno 6 caratteri.")
            else:
                try:
                    if registra(nome, email2, pw2):
                        st.rerun()
                    else:
                        st.success("Account creato! Ti è arrivata un'email: apri il link di conferma, "
                                   "poi torna qui ed entra.")
                except Exception as e:  # noqa: BLE001
                    if "registered" in str(e).lower() or "exists" in str(e).lower():
                        st.error("Esiste già un account con questa email: usa «Entra».")
                    else:
                        st.error(f"Non sono riuscito a creare l'account: {e}")


def scheda_formazione(stato, g):
    leghe = stato["leghe"]
    if not leghe:
        st.info("Non hai ancora nessuna lega. Vai nella scheda **Rosa** e crea la tua squadra: "
                "poi qui trovi la formazione migliore.")
        return
    nomi = [f"{l['squadra']} · {l['nome']}" for l in leghe]
    idx = st.session_state.get("lega_idx", 0)
    idx = min(idx, len(leghe) - 1)
    scelta = st.radio("Lega", nomi, index=idx, horizontal=True, label_visibility="collapsed")
    idx = nomi.index(scelta)
    st.session_state.lega_idx = idx
    lega = leghe[idx]
    stemma_squadra(lega)

    ov = stato.get("override", {})
    ov_p = ov.get("p", {}) if ov.get("giornata") == g.get("giornata") else {}
    motore = Motore(g)
    rosa = arricchisci(lega["rosa"], g, ov_p)
    ris = motore.migliore(rosa, lega.get("modificatore", False))
    if not ris:
        st.warning("La rosa non basta per nessun modulo: servono almeno 1 portiere, 3 difensori, "
                   "3 centrocampisti e 1 attaccante. Completala nella scheda **Rosa**.")
        return
    win, bench = ris["win"], ris["bench"]
    titolari = [win["gk"]] + win["D"] + win["C"] + win["A"]

    mod_txt = f"di cui modificatore ≈ +{win['mb']:.1f}" if lega.get("modificatore") else "senza modificatore"
    chips = "".join(f'<span class="ff-chip {"on" if r is win else ""}">{r["m"]} · {r["tot"]:.1f}</span>'
                    for r in ris["results"])
    st.markdown(f'<div class="ff-card"><div style="display:flex;justify-content:space-between;align-items:end">'
                f'<div><div class="ff-sub">Modulo consigliato</div><div class="ff-big">{win["m"]}</div></div>'
                f'<div style="text-align:right"><div class="ff-sub">Punteggio atteso</div>'
                f'<div class="ff-big">{win["tot"]:.1f}</div><div class="ff-sub">{mod_txt}</div></div></div>'
                f'<div style="margin-top:8px">{chips}</div></div>', unsafe_allow_html=True)

    senza = [p for p in rosa if not p["notizie"] and not p.get("manuale")]
    if senza:
        st.warning(f"{len(senza)} giocatori senza notizie per questa giornata (li conto al 50%). "
                   "Se sai chi gioca, cambialo qui sotto in «Correggi un giocatore».")

    st.markdown("#### Titolari")
    st.markdown('<div class="ff-card">' + "".join(riga(p, g, motore) for p in titolari) + "</div>",
                unsafe_allow_html=True)

    st.markdown("#### Panchina (in ordine)")
    st.markdown('<div class="ff-card">' + "".join(riga(p, g, motore, i + 1) for i, p in enumerate(bench))
                + "</div>", unsafe_allow_html=True)

    assenti = [p for p in rosa if p["p"] == 0]
    dubbi = [p for p in titolari if 0 < p["p"] < 70]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Assenti")
        if assenti:
            for p in assenti:
                st.markdown(f"- **{esc(p['n'])}**: {esc(p.get('nota', ''))}")
        else:
            st.caption("Nessuno")
    with c2:
        st.markdown("#### Da ricontrollare")
        if dubbi:
            for p in dubbi:
                st.markdown(f"- **{esc(p['n'])}** ({round(p['p'])}%)")
        else:
            st.caption("Nessun titolare in dubbio")

    with st.expander("✋ Correggi un giocatore"):
        st.caption("Se sai che un giocatore gioca (o no) meglio delle notizie, cambialo qui. "
                   "La correzione vale solo per questa giornata.")
        ordinati = sorted(rosa, key=lambda p: (ROLE_ORDER[p["r"]], p["n"]))
        etichette = [f"{p['r']} · {p['n']} ({p['t']})" for p in ordinati]
        sel = st.selectbox("Giocatore", etichette)
        pl = ordinati[etichette.index(sel)]
        scelte = {"Titolare sicuro": 92, "Titolare in dubbio": 70, "Ballottaggio": 50,
                  "Panchina": 10, "Non gioca (infortunato/squalificato)": 0}
        c = st.radio("Secondo te", list(scelte.keys()), index=None, key=f"ov_{chiave(pl)}")
        b1, b2 = st.columns(2)
        if b1.button("Salva", type="primary", use_container_width=True, disabled=c is None):
            nuovo = {"giornata": g.get("giornata"), "p": dict(ov_p)}
            nuovo["p"][chiave(pl)] = scelte[c]
            stato["override"] = nuovo
            salva_stato(stato)
            st.rerun()
        if b2.button("Torna alle notizie", use_container_width=True, disabled=chiave(pl) not in ov_p):
            nuovo = {"giornata": g.get("giornata"), "p": {k: v for k, v in ov_p.items() if k != chiave(pl)}}
            stato["override"] = nuovo
            salva_stato(stato)
            st.rerun()


def scheda_rosa(stato, g):
    leghe = stato["leghe"]
    squadre = sorted((g.get("partite") or {}).keys()) or SQUADRE_DEFAULT
    opzioni = [f"{l['squadra']} · {l['nome']}" for l in leghe] + ["➕ Nuova lega"]
    scelta = st.selectbox("Lega da modificare", opzioni)
    nuova = scelta == "➕ Nuova lega"
    lega = {"id": f"lega{int(time.time())}", "nome": "", "squadra": "", "modificatore": False, "rosa": []} \
        if nuova else leghe[opzioni.index(scelta)]

    nome = st.text_input("Nome della lega", value=lega["nome"], key=f"nl_{lega['id']}")
    squadra = st.text_input("Nome della tua squadra", value=lega["squadra"], key=f"ns_{lega['id']}")
    mod = st.toggle("La lega usa il modificatore difesa", value=lega.get("modificatore", False),
                    key=f"md_{lega['id']}")

    st.markdown("**Giocatori**")
    st.caption("Scrivi il cognome come su Leghe Fantacalcio (es. «Martinez L.», «Taylor K.»). "
               "FVM = valore di mercato del giocatore (se non lo sai lascia 1). "
               "Tocca l'ultima riga per aggiungere un giocatore.")
    righe = [{"Nome": p["n"], "Squadra": p["t"], "Ruolo": p["r"], "FVM": int(p.get("fvm") or 1)}
             for p in sorted(lega["rosa"], key=lambda p: (ROLE_ORDER[p["r"]], p["n"]))]
    tab = st.data_editor(
        righe, num_rows="dynamic", use_container_width=True, hide_index=True, key=f"ed_{lega['id']}",
        column_config={
            "Nome": st.column_config.TextColumn("Nome", required=True),
            "Squadra": st.column_config.SelectboxColumn("Squadra", options=squadre, required=True),
            "Ruolo": st.column_config.SelectboxColumn("Ruolo", options=RUOLI, required=True, width="small"),
            "FVM": st.column_config.NumberColumn("FVM", min_value=1, max_value=500, step=1, default=1,
                                                 width="small"),
        })

    rosa = [{"n": str(r["Nome"]).strip(), "t": r["Squadra"], "r": r["Ruolo"], "fvm": int(r.get("FVM") or 1)}
            for r in tab if r.get("Nome") and r.get("Squadra") and r.get("Ruolo")]
    conta = {r: sum(1 for p in rosa if p["r"] == r) for r in RUOLI}
    st.caption(f"Portieri {conta['P']} · Difensori {conta['D']} · Centrocampisti {conta['C']} · "
               f"Attaccanti {conta['A']} · Totale {len(rosa)}")

    if st.button("💾 Salva la lega", type="primary", use_container_width=True):
        if not nome.strip() or not squadra.strip():
            st.error("Scrivi il nome della lega e della tua squadra.")
        else:
            lega2 = {"id": lega["id"], "nome": nome.strip(), "squadra": squadra.strip(),
                     "modificatore": mod, "rosa": rosa}
            if nuova:
                leghe.append(lega2)
            else:
                leghe[opzioni.index(scelta)] = lega2
            stato["leghe"] = leghe
            salva_stato(stato)
            st.success("Lega salvata.")
            st.rerun()

    if not nuova:
        with st.expander("🗑️ Elimina questa lega"):
            conferma = st.checkbox("Sì, voglio eliminarla")
            if st.button("Elimina", disabled=not conferma):
                leghe.pop(opzioni.index(scelta))
                stato["leghe"] = leghe
                salva_stato(stato)
                st.session_state.lega_idx = 0
                st.rerun()


def scheda_notizie(stato, g):
    if not g:
        st.info("Notizie della giornata non ancora disponibili.")
        return
    agg = str(g.get("aggiornato", "")).replace(" · INVIATA", "").replace(" · VERIFICATA", "") \
        .replace(" · aggiornamento manuale", "")
    st.markdown(f"**{g.get('giornata', '')}ª giornata** · notizie aggiornate {esc(agg)}")
    st.caption(f"Scadenza: {g.get('scadenza', '')}")
    partite = g.get("partite") or {}
    viste, righe = set(), []
    for sq, m in partite.items():
        if sq in viste:
            continue
        viste.update({sq, m.get("vs")})
        casa, ospite = (sq, m.get("vs")) if m.get("casa") else (m.get("vs"), sq)
        righe.append((m.get("quando", ""), f"{casa} - {ospite}"))
    st.markdown("#### Partite")
    st.markdown('<div class="ff-card">' + "".join(
        f'<div class="ff-row"><div class="ff-info"><b>{esc(p)}</b></div><span class="ff-sub">{esc(q)}</span></div>'
        for q, p in righe) + "</div>", unsafe_allow_html=True)
    with st.expander("Fonti"):
        st.caption(g.get("fonte", ""))
        st.caption(g.get("statistiche", ""))


def scheda_account(g):
    u = utente()
    st.markdown(f"Ciao **{esc(u['nome'])}** · {esc(u['email'])}")
    with st.expander("Cambia password"):
        with st.form("pw"):
            p1 = st.text_input("Nuova password", type="password", autocomplete="new-password")
            p2 = st.text_input("Ripeti la password", type="password", autocomplete="new-password")
            ok = st.form_submit_button("Cambia")
        if ok:
            if len(p1) < 6 or p1 != p2:
                st.error("Le password non coincidono o sono più corte di 6 caratteri.")
            else:
                try:
                    _con_rinnovo(lambda: sb().auth.update_user({"password": p1}))
                    st.success("Password cambiata.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"Non sono riuscito a cambiarla: {e}")
    if st.button("🔄 Ricarica le notizie", use_container_width=True):
        carica_giornata(forza=True)
        st.rerun()
    if st.button("Esci", use_container_width=True):
        esci()
        st.rerun()
    st.divider()
    st.caption("Come funziona: per ogni giocatore la probabilità di giocare viene dalle probabili "
               "formazioni e dal bollettino infortuni; il punteggio atteso tiene conto di avversario, "
               "casa/trasferta, gol, assist e rigori. L'app sceglie il modulo con il punteggio più alto.")
    st.caption("Per aggiungere l'app alla schermata Home: su iPhone Safari → Condividi → "
               "«Aggiungi alla schermata Home»; su Android Chrome → menu ⋮ → «Aggiungi a schermata Home».")


# ------------------------------------------------------------------ main
def main():
    if not utente():
        schermata_accesso()
        return
    g = carica_giornata()
    stato = carica_stato()
    intestazione(g)
    t1, t2, t3, t4 = st.tabs(["⚽ Formazione", "📋 Rosa", "📰 Notizie", "👤 Account"])
    with t1:
        scheda_formazione(stato, g)
    with t2:
        scheda_rosa(stato, g)
    with t3:
        scheda_notizie(stato, g)
    with t4:
        scheda_account(g)


main()
