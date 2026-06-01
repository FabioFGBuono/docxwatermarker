# docxwatermarker

Sostituisce una immagine dentro un template `.docx`, byte per byte, lasciando il resto del file dov'è.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

*[English version](README.md).*

## Cos'è

Questo repository è un tentativo di colmare un buco tra la didattica e il mondo reale, e nello stesso tempo uno strumento che fa un lavoro vero. La maggior parte del materiale sulla specifica formale è o un programma giocattolo scritto per illustrare il metodo o una dimostrazione pesante verificata dalla macchina su codice critico. Una specifica leggibile di una libreria ordinaria e funzionante, tenuta onesta da un test ordinario invece che da un assistente di dimostrazione, è più difficile da trovare.  Quello che troverete qui invece è una piccola libreria Python che sostituisce un'immagine dentro un documento Word, un'applicazione da riga di comando completa che la usa, e due documenti che descrivono l'insieme in termini formali, una specifica assiomatica della libreria e una semantica operazionale dello strumento da riga di comando. I documenti sono legati al codice da test, così non possono allontanarsene senza che ce ne accorga, e sono pensati in particolare per chi vuole vedere codice funzionante e specifica formale uno accanto all'altra. Un buon punto da cui partire, per quel lato, è [`STUDIO.pdf`](STUDIO.pdf), un breve percorso di lettura attraverso il codice, la specifica, e i test.

## Cosa fa

La libreria mette un watermark in un file `.docx` sostituendo un'immagine al suo interno. La libreria è adatta alla personalizzazione di documenti per destinatario, fra cui timbri di confidenzialità, marker di bozza, watermark per destinatario a fini di tracciabilità, e copie brandizzate per cliente.

Il package si usa da Python importando `docxwatermarker`, e `pip install` mette anche un comando `docxwatermarker` sul path che guida la stessa libreria dalla shell, così la libreria si può usare senza scrivere Python. Il *Quickstart* più sotto mostra entrambi.

## Quando docxwatermarker ha senso

`docxwatermarker` ha uno scopo ristretto, e per altri casi d'uso esistono strumenti più adatti.

- **[python-docx](https://python-docx.readthedocs.io)**: costruzione o modifica programmatica di documenti Word da zero. Va usato quando non si ha un template, o quando si deve modificare testo, tabelle, intestazioni, struttura.
- **[Aspose.Words](https://products.aspose.com/words/) / [GroupDocs](https://products.groupdocs.com/watermark/)**: automazione documentale commerciale e completa, inclusa la conversione fedele al layout verso molti formati. Vanno bene quando il budget lo permette e servono funzionalità enterprise.
- **[pypdf](https://pypdf.readthedocs.io) + [reportlab](https://www.reportlab.com)**: watermark di un PDF già esistente. Vanno usati quando si è già oltre la fase Word e l'input è già un PDF.

`docxwatermarker` occupa lo spazio fra questi strumenti.

## Quickstart

### Python

```python
from docxwatermarker import Template, make_text_watermark, make_marker_png

# Setup una volta sola: inserire questo PNG nel template Word, ancorato alla pagina.
with open("marker.png", "wb") as f:
    f.write(make_marker_png(1600))

# Personalizzazione e salvataggio:
watermark = make_text_watermark(["Copia per Mario Rossi", "mario@example.com"])
Template.open("template.docx").replace_image(watermark).save("personalizzato.docx")
```

### Riga di comando

```bash
docxwatermarker inspect template.docx
docxwatermarker stamp template.docx -o out.docx --preset confidential --pdf
docxwatermarker stamp template.docx -o out.docx \
    --watermark-text "Copia per Mario Rossi" \
    --watermark-text "mario@example.com"
```

## La filosofia template-first

In `docxwatermarker` Word è la fonte di verità per il layout. Un'alternativa comune genera i watermark in modo programmatico e ignora del tutto il layout di Word. Un'altra modifica l'XML del documento, soluzione fragile che tende a rompere l'ancoraggio di pagina o a interagire male con le proprietà di sezione. Abbiamo scelto contro entrambe.

Il template si prepara una volta sola, in Word.

1. Generare un PNG placeholder con `docxwatermarker`: `python -c "from docxwatermarker import make_marker_png; open('marker.png','wb').write(make_marker_png())"`. Il PNG porta un marker embedded che permette alla libreria di identificarlo in seguito.
2. In Word, *Inserisci > Immagine > Da file* e selezionare `marker.png`.
3. Tasto destro sull'immagine, *Disponi testo > Dietro al testo*, in modo che l'immagine viva come layer di watermark.
4. *Formato immagine > Posizione > Ancora alla pagina*, e non al paragrafo (il default di Word), che è la ragione per cui la maggior parte dei watermark "scivola" fra le pagine.
5. Ridimensionare e posizionare l'immagine in modo che copra l'area da marchiare. Salvare il template.

Da quel momento, ogni chiamata a `Template.replace_image()` sostituisce i byte dell'immagine lasciando intatti l'ancoraggio, la disposizione del testo e la posizione. Ogni altra entry del documento resta intatta, con gli stessi nomi, contenuti e metadati per entry, così il risultato si apre in Word come se l'immagine fosse stata sostituita a mano. La entry modificata viene ri-marcata con l'ora corrente. La sezione *Build riproducibili* più sotto copre l'output byte-identico fra esecuzioni.

> **Nota.** La funzione *Filigrana* incorporata in Word (*Progettazione > Filigrana*) è comoda, ma usa un oggetto `WordArt` nell'intestazione anziché una immagine ancorata alla pagina, e il risultato non è sempre fedele in conversione PDF. `docxwatermarker` lavora con immagini ordinarie.


## Riferimento CLI

```
docxwatermarker stamp <template.docx> [opzioni]
docxwatermarker inspect <template.docx>
```

### `stamp`

```
Sorgente (solo una richiesta, salvo -i):
  --image FILE             Usa un file immagine (formato deve combaciare col target)
  --watermark-text TEXT    Genera una watermark di testo (ripetibile, una per linea)
  --preset NAME            Usa un preset built-in: confidential | draft | copy

Selezione del target (default: auto = prima marker, poi euristica):
  --use-marker             Punta al PNG marker univoco
  --target-filename PATH   Punta a un path interno preciso, p.es. word/media/image3.png

Stile della watermark (solo con --watermark-text / --preset):
  --size N                 Lato del canvas in pixel (default 1600)
  --rotation DEG           Rotazione in gradi (default 45 o valore del preset)

Output:
  -o, --output PATH        Path .docx di output
  --pdf                    Produce anche un PDF accanto al DOCX
  --pdf-only               Produce solo il PDF (rimuove il DOCX intermedio)

Modalità:
  -i, --interactive        Chiede le linee della watermark se non è dato un flag sorgente
  -v, --verbose            Messaggi diagnostici a livello INFO
  --debug                  Diagnostica a livello DEBUG + check di invarianti interni
```

### `inspect`

```
PATH                    FORMAT  WIDTHxHEIGHT  SIZE   MARKER
word/media/image1.png   png     1600x1600     10061  yes
word/media/image2.jpeg  jpeg    640x480       5428   no
```

### Codici di uscita (per lo scripting)

| Code | Significato |
|------|-------------|
| 0 | Successo |
| 1 | Errore inatteso (catch-all) |
| 2 | Errore di parsing argomenti |
| 3 | Template non trovato o non valido |
| 4 | Nessuna immagine ha matchato il selettore |
| 5 | Più immagini hanno matchato (ambiguità) |
| 6 | Formato dell'immagine di rimpiazzo != formato del target |
| 7 | Conversione PDF fallita |
| 130 | Interruzione (Ctrl-C) |

## API Python

Importare `docxwatermarker` dà accesso a diciotto nomi, tutto il resto è interno.

**Core**: `Template`, `ImageMatcher`, `ImageInfo`, `make_marker_png`.

**Generazione di watermark**: `make_text_watermark`, `WatermarkPreset`, `PRESETS`.

**PDF**: `from docxwatermarker.pdf import to_pdf, find_libreoffice`.

**Debug e diagnostica**: `enable_debug`, `disable_debug`, `is_debug_enabled`, `configure_invariants`, `is_ensure_raising`.

**Eccezioni**: `DocxWatermarkerError` (base), `ImageNotFoundError`, `MultipleImagesError`, `FormatMismatchError`, `PDFConversionError`, `InvariantError`. Tutte portano un campo `.context` strutturato e un metodo `.to_dict()` JSON-safe.

In [`examples/`](examples/) ci sono script eseguibili.

## Esempi

| File | Cosa mostra |
|------|-------------|
| [`01_basic_replace.py`](examples/01_basic_replace.py) | Sostituisce una immagine con una da disco |
| [`02_text_watermark.py`](examples/02_text_watermark.py) | Genera una watermark di testo e la applica |
| [`03_preset_with_pdf.py`](examples/03_preset_with_pdf.py) | Usa un preset e produce un PDF |
| [`04_personalize_for_recipient.py`](examples/04_personalize_for_recipient.py) | Una copia personalizzata per destinatario |
| [`05_batch_csv.py`](examples/05_batch_csv.py) | Batch da CSV (~20 righe sopra l'API) |

Per partire, `python examples/make_sample_template.py` produce un template minimo valido, e gli script sopra possono poi essere eseguiti su quello.

## Note di design e pratiche di sviluppo

Alcune scelte nel codice meritano una nota.

### Niente manipolazione di XML

`docxwatermarker` non legge né scrive l'XML di Word, il `.docx` è un file ZIP, e così lo trattiamo, scambiando i byte di una entry e riimpacchettando l'archivio. È la scelta di design portante della libreria, ed è ciò che rende il comportamento affidabile fra versioni di Word, lingue, layout complessi e varianti OOXML, al costo di richiedere una immagine placeholder nel template.

### Il template è immutabile

`Template.replace_image()` ritorna un nuovo `Template`, e l'originale non viene mai mutato. Questo elimina una classe di bug di stato che si manifestano nei loop batch, e rende sicuro il chaining. Il costo è una copia in memoria dei byte dello zip per ogni sostituzione, trascurabile alle dimensioni tipiche dei documenti.

### Architettura a livelli, confine pubblico/interno

Il package è organizzato in modo che la superficie pubblica resti piccola e stabile e gli helper interni possano cambiare senza rompere i chiamanti.

```
docxwatermarker/
├── core.py            ← pubblico: Template, ImageMatcher
├── watermark.py       ← pubblico: make_text_watermark, PRESETS
├── pdf.py             ← pubblico: to_pdf, find_libreoffice
├── errors.py          ← pubblico: gerarchia delle eccezioni
├── cli.py             ← pubblico: entry point della CLI
├── _zipops.py         ← interno: lettura/scrittura zip con metadati
├── _imagedetect.py    ← interno: enumerazione immagini, logica del marker
├── _logging.py        ← interno: logger + debug mode
└── _invariants.py     ← interno: require / ensure
```

I moduli con underscore stanno fuori dal contratto e qualsiasi cosa importata direttamente da `docxwatermarker`, senza punti ulteriori, sta dentro.

### Le eccezioni portano un contesto strutturato

Ogni eccezione della libreria deriva da `DocxWatermarkerError` e accetta argomenti keyword arbitrari memorizzati in `.context`. Un raise tipico ha la forma `ImageNotFoundError("...", matcher="auto", candidates=[...])`. La forma stringa stampa il contesto in linea per un debug ergonomico, e `.to_dict()` produce una rappresentazione JSON-safe, dove i valori non serializzabili sono convertiti tramite `repr()` ricorsivamente. La stessa eccezione alimenta log machine-readable e messaggi umani.

### Design-by-contract interno

- **`require(condition, message, *, spec=None, **context)`** per le precondizioni, ovvero i controlli di contratto pubblico. È sempre attivo e solleva sempre `InvariantError`.
- **`ensure(condition, message, *, spec=None, **context)`** per postcondizioni e self-check. È attivo solo in debug mode. Di default avverte e prosegue, e il comportamento passa al raise tramite `configure_invariants(raise_on_failure=True)`.

L'argomento opzionale `spec` nomina la clausola della specifica formale che un controllo realizza (per esempio `spec="I2"`). È il legame durevole fra codice e specifica, descritto nella sezione *Specifica assiomatica* più sotto.

La distinzione fra `require` e `ensure` riflette chi è responsabile della violazione. Un `require` fallito significa che il chiamante ha sbagliato qualcosa, e fail-fast è la risposta giusta. Un `ensure` fallito significa che abbiamo scoperto un'inconsistenza interna dopo aver prodotto un output corretto, e in produzione un warning è preferibile a una pipeline interrotta. In dev e CI, lo switch va nell'altro senso. Il campo `kind` su `InvariantError` è riservato. Passare `kind=` come kwarg a `require` o `ensure` solleva `TypeError`, così la sorgente di ogni violazione resta univoca.

### Rilevazione del marker tramite chunk PNG `tEXt`

`make_marker_png()` produce un PNG con un chunk `tEXt` sotto la chiave standard `Description`, che porta una stringa marker lunga e univoca. La rilevazione è una ricerca di sottostringa a basso costo sui primi byte del file, e la libreria non istanzia mai un parser di chunk PNG. La scelta della chiave standard `Description` è importante perché gli strumenti che rimuovono i metadati PNG custom lasciano in genere intatte le chiavi standard, e il marker sopravvive a una ri-codifica accidentale del PNG.

### Approccio ai test

Il repository contiene oltre 300 assertion di test in `tests/`. I foundation test fissano il contratto pubblico delle primitive di base (errori, logging, invarianti) e girano ovunque. Gli unit test fissano il contratto di ciascun modulo, con uso intenso di fixture in memoria, per cui un `.docx` reale viene costruito da zero ad ogni test tramite `zipfile` e non vengono committati blob binari nel repo. Gli integration test esercitano l'intera pipeline incluso LibreOffice, sono marcati con `@pytest.mark.requires_libreoffice` e si auto-skippano quando LibreOffice non è installato. Mentre l'interazione col sottoprocesso PDF è mockata in `test_pdf.py`, che gira ovunque, ed esercitata davvero in `test_pdf_integration.py`, che richiede LibreOffice. I mock fissano la logica del nostro wrapper, gli integration test intercettano cambiamenti nella CLI di LibreOffice, e i due livelli sono tenuti entrambi per questa ragione.

`test_spec_crossref.py` mantiene allineati codice e specifica formale. Estrae dal sorgente ogni annotazione `spec=`, la confronta col catalogo in `_invariants.SPEC_REALIZATIONS`, e confronta quel catalogo con le tabelle degli invarianti nei documenti di semantica. Una clausola rinominata in un punto solo fa fallire la build.

### Build riproducibili (opzionale)

La funzione interna `_zipops.write_zip()` accetta un flag `reproducible=True` che azzera tutti i timestamp al minimo DOS (1980-01-01). Con questo flag due esecuzioni sullo stesso input producono output byte-identici. Il flag non è ancora esposto attraverso `Template.save()`, e arriverà in v0.2.

### Specifica assiomatica (lettura opzionale)

Il repository contiene una specifica formale dell'API pubblica nello stile delle triple di Hoare: [`SEMANTICA.pdf`](SEMANTICA.pdf), con sorgente LaTeX in [`SEMANTICA.tex`](SEMANTICA.tex) e una versione Markdown per la lettura in browser in [`SEMANTICA.md`](SEMANTICA.md). La versione inglese è in [`SEMANTICS.pdf`](SEMANTICS.pdf) con sorgenti in [`SEMANTICS.tex`](SEMANTICS.tex) e [`SEMANTICS.md`](SEMANTICS.md).

Una libreria di questa scala riceve di rado questo tipo di trattamento, il codice dichiara già un contratto parziale attraverso le sue primitive `require` ed `ensure`, nella tradizione del design-by-contract, e una specifica formale chiude un cerchio che il codice apre soltanto a metà, perché ogni asserzione runtime guadagna un enunciato matematico corrispondente, e ogni proprietà nel documento dovrebbe mappare a un `require` o un `ensure` nel codice. Codice e specifica condividono un identificatore, in particolare ogni `require`/`ensure` che realizza una clausola della specifica porta un valore `spec=` (come `spec="I2"`), lo stesso valore che la tabella degli invarianti usa nella specifica. Le bozze precedenti puntavano dal documento al codice con i numeri di riga, che invecchiano appena il codice si sposta e non danno alcun avviso quando accade. L'identificatore `spec=` resta attaccato al suo controllo ovunque cadano le righe, e `test_spec_crossref.py` fa fallire la build se codice, catalogo e documento escono dall'accordo.

### Semantica operazionale (lettura facoltativa)

La specifica assiomatica si adatta alla libreria, le cui operazioni pubbliche sono funzioni pure caratterizzate da ciò che garantiscono. Lo strumento da riga di comando è un oggetto di natura diversa, un processo che attraversa fasi ed esce con un codice che registra dove si è fermato. Quel processo è modellato in [`OPERAZIONALE.pdf`](OPERAZIONALE.pdf) (con [`OPERAZIONALE.tex`](OPERAZIONALE.tex) e [`OPERAZIONALE.md`](OPERAZIONALE.md), e un'edizione inglese in [`OPERATIONAL.pdf`](OPERATIONAL.pdf), [`OPERATIONAL.tex`](OPERATIONAL.tex), [`OPERATIONAL.md`](OPERATIONAL.md)) come sistema di transizioni nello stile degli appunti di Mancarella, dove `stamp` diventa una sequenza di configurazioni e i codici d'uscita sono i suoi stati terminali. I due documenti mostrano lo stesso progetto sotto le due semantiche, ciascuna usata dove serve. Il legame col codice è controllato come lo è quello assiomatico. `test_spec_crossref.py` estrae i codici d'uscita che `cmd_stamp` e `cmd_inspect` restituiscono e li confronta con i codici che entrambi i documenti operazionali tabulano, così un codice non può allontanarsi dalla sua specifica senza che ce ne accorga.

Il documento è scritto nella tradizione delle *Note di semantica assiomatica* di Mancarella e di *Formal Semantics of Programming Languages* di Winskel.


## Limitazioni e questioni note

- **Una immagine per chiamata.** `Template.replace_image()` sostituisce una immagine, il multi-image swap è sulla roadmap di v0.2.
- **Il formato deve combaciare.** Sostituire un PNG con un JPEG solleva `FormatMismatchError`, dato che le dichiarazioni di `[Content_Types].xml` andrebbero altrimenti fuori sincrono. Va ricodificato l'input prima, se necessario.
- **Niente comando CLI per il batch CSV** in v0.1. Il loop in `examples/05_batch_csv.py` copre il caso d'uso in circa 20 righe.
- **Il backend PDF è solo LibreOffice.** L'automazione Office tramite docx2pdf non è supportata in v0.1. I fallimenti di conversione PDF mappano su `PDFConversionError` con un campo `reason` specifico.
- **Il marker deve essere un PNG.** Altri formati restano sostituibili tramite `--target-filename` o `ImageMatcher.by_filename()`. Il meccanismo del marker poggia su un chunk `tEXt`, che è una feature PNG-only.
- **L'API è alpha.** La forma cambierà prima della 1.0. Da pinnare a `~=0.1` in caso di dipendenza.


## Licenza

[MIT](LICENSE).

Questo è un progetto personale, scritto nel tempo libero e rilasciato sotto licenza MIT perché possa essere utile a chi ne ha bisogno.

## Ringraziamenti

I documenti di specifica si appoggiano al lavoro di altri in particolare la notazione assiomatica segue gli appunti di Mancarella sulla semantica assiomatica, quella operazionale gli appunti di Barbuti, Mancarella e Turini, entrambi dell'Università di Pisa, e la trattazione poggia sul lavoro fondativo di Hoare, Dijkstra, Winskel, Meyer e Plotkin. Ogni documento porta i riferimenti completi. Un grazie ai loro autori per materiale scritto per essere insegnato, e liberamente disponibile, che è ciò che ha reso possibile questo caso di studio.
