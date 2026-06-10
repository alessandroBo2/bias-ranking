# Glossario dell'audit di bias su Google Shopping
*Spiegazione dei termini per un pubblico non tecnico (marketing).*

---

## L'idea in una frase
Addestriamo un modello a **indovinare l'ordine in cui Google ha disposto i prodotti** in pagina,
usando solo caratteristiche osservabili. Se per indovinare bene gli serve sapere *chi è il venditore*
(e non bastano prezzo e rilevanza), allora il venditore "pesa" oltre il merito: è lì che cerchiamo un
eventuale bias.

---

## I termini

**Merito** — Le caratteristiche che *legittimamente* dovrebbero spiegare una buona posizione:
rilevanza del titolo rispetto alla ricerca, prezzo, qualità/lunghezza del titolo, categoria, ricerca di
marca o generica. È il "perché meriti di stare in alto" misurabile.

**Solo merito** — Il modello a cui diamo **solo** le caratteristiche di merito. Non sa chi vende il
prodotto. Deve ricostruire l'ordine di Google con le mani legate.

**Merito + venditore** — Lo stesso identico modello, ma in più sa **chi vende**: se è Amazon, se è un
"gigante" del retail, e quanto spesso quel venditore compare nei dati (prevalenza).

**NDCG@10** — Il voto di quanto bene il modello ha indovinato l'ordine, concentrandosi sui **primi 10**
risultati (quelli che contano). Va circa da 0 a 1: più alto = ricostruzione più fedele.
*Attenzione:* non è una percentuale di "risposte giuste", e la linea del caso non è 0 ma ~0,40
(vedi baseline random). Lo spazio utile va quindi da ~0,40 (a caso) a 1,0 (perfetto).

**Lift** — L'**incremento** ottenuto aggiungendo una leva (stesso concetto dell'uplift in marketing).
Qui = quanto sale l'NDCG passando da "solo merito" a "merito + venditore".
Nei nostri dati IT il lift è **≈ +0,065**, stabile. Significa: sapere chi è il venditore aiuta a
ricostruire l'ordine *oltre* ciò che prezzo e rilevanza già spiegano.

**Baseline (random / prezzo crescente)** — Due "righelli" di riferimento. *Random* = ordine a caso
(~0,40). *Prezzo crescente* = dal più economico (~0,389). Servono a dimostrare che il modello "merito"
(~0,43) impara qualcosa di reale, e che **Google non ordina per prezzo** (ordinare per prezzo fa
peggio del caso).

**SHAP** — *SHapley Additive exPlanations.* Metodo che spiega, **per ogni singolo prodotto**, quanto e
in che direzione ciascuna caratteristica lo ha spinto in classifica. Si basa sugli *Shapley values*,
un concetto della teoria dei giochi (Lloyd Shapley, premio Nobel per l'economia) che ripartisce un
risultato di squadra tra i suoi membri in modo equo. In pratica scompone il punteggio finale di un
prodotto in tanti "+" e "−", uno per ogni leva.

---

## Come si legge il grafico SHAP (beeswarm)

- **Asse verticale**: le variabili, ordinate dalla **più importante (in alto)** alla meno.
- **Asse orizzontale**: il valore SHAP. **Destra = spinge in alto** in classifica, **sinistra = spinge
  in basso**. La linea sullo zero = nessun effetto.
- **Ogni puntino è un prodotto** (una riga del dataset).
- **Colore** = valore della caratteristica: **rosso = alto, blu = basso**.

Combinando colore e posizione si legge la *regola* appresa dal modello. Nei nostri grafici:

- `seller_freq_log` (prevalenza del venditore) — **la leva più forte**: i puntini rossi (venditore che
  compare spesso) stanno a destra → più è prevalente, più viene spinto in alto.
- `is_amazon` (binaria: rosso = è Amazon) — i puntini rossi stanno **a sinistra** (≈ −0,14):
  **essere Amazon spinge in basso**, non in alto → nessun favoritismo pro-Amazon.
- `log_price` — prezzo alto (rosso) tende leggermente a sinistra → piccola spinta verso il basso.
- `rel` (rilevanza) — effetto piccolo e in basso nella lista → la rilevanza testuale conta poco per
  l'ordine di Google.

---

## La conclusione in due righe
Il modello che conosce il venditore ricostruisce meglio l'ordine di Google (**lift ≈ +0,065**), ma quel
vantaggio viene dalla **prevalenza** del venditore (struttura di mercato), non dall'essere Amazon — che
anzi risulta penalizzato. Il risultato non cambia tra TF-IDF e MiniLM. **Nessuna prova di bias
pro-venditore nel ranking organico osservabile.**

> Perché l'NDCG è "solo" ~0,49 e va benissimo così: se bastassero prezzo, rilevanza e venditore a
> ricostruire l'ordine quasi alla perfezione, vorrebbe dire che l'ordine è tutto lì. Non riuscirci
> significa che gran parte di ciò che muove il ranking è **non osservabile** (sponsorizzato,
> personalizzazione, qualità) — esattamente il limite dei dati: mancano il **flag sponsorizzato** e i
> **rating**. L'audit dice "nessun bias evidente nel ranking organico misurabile", non "Google è neutrale".
